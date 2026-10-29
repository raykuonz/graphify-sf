"""Static resolution of Apex HTTP callout endpoints.

Finds every ``<receiver>.setEndpoint(<expr>)`` call and decides, without executing anything, which Named
Credential or external host it reaches and how sure we can be:

* The call must be real code: it is located on the *scrubbed* copy of the source (comments and string
  contents blanked), and the endpoint text is then read from the raw source at the same offsets.
* ``<expr>`` is evaluated as a ``+`` concatenation of string literals and ``static``/instance ``final String``
  constants of the same file. Anything else (a method call, ``String.format``, a ternary, another class's constant,
  ``this.x``, a local variable) is dynamic.
* ``EXTRACTED`` only when the target is proven: the whole expression is constant, or the constant prefix already
  contains a delimiter after the credential/host (``callout:NC/...``, ``https://h/...``). ``callout:NC + suffix``
  is ``INFERRED`` (``dynamic_suffix``, or ``non_final_static`` when the dynamic part is a non-final field): the
  suffix could extend the credential name. A partial host is never an endpoint, so it yields no edge.
* The receiver is classified: *proven* ``HttpRequest`` (declaration or ``new HttpRequest()``), *disproven* (declared
  as another type: not a callout at all, no edge, not a site) or *unknown* (``INFERRED``, ``receiver_unproven``).
* ``test_context`` marks sites inside ``@IsTest`` classes or methods and ``testMethod`` methods.

The module is a leaf (no imports from ``apex.py``); the caller passes in the method regex and brace matcher.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

_SET_ENDPOINT_RE = re.compile(r"\.\s*setEndpoint\s*\(", re.IGNORECASE)
_ANY_CLASS_HEADER_RE = re.compile(r"\b(?:class|interface|enum)\s+\w+[^{;]*\{", re.IGNORECASE)
_IS_TEST_RE = re.compile(r"@\s*isTest\b", re.IGNORECASE)
_FIELD_RE = re.compile(
    r"((?:\b(?:public|private|protected|global|static|final|transient)\s+)*)\bString\s+(\w+)\s*=\s*([^;]+);",
    re.IGNORECASE,
)
_NOT_A_TYPE = frozenset(
    {
        "return", "new", "else", "throw", "case", "instanceof", "delete", "insert", "update",
        "upsert", "undelete", "merge", "and", "or", "not", "in", "if", "while", "for", "do",
    }
)  # fmt: skip
_HTTP_REQUEST_TYPES = frozenset({"httprequest", "system.httprequest"})
# Every form of ``Type name`` declaration (field, property, local, parameter, for-each variable): the lookahead is
# what follows a declared name. Built once per file.
_DECL_RE = re.compile(
    r"(?<![\w.])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?:<[^<>;(){}]*>)?(?:\[\])?\s+([A-Za-z_]\w*)\b\s*(?=[=;,):{])",
    re.IGNORECASE,
)
_EXTRA_DECL_RE = re.compile(r",\s*([A-Za-z_]\w*)\s*=(?!=)")  # second and later declarators: ``String a = 'x', b = 'y'``
_LOWER_PRECEDENCE = frozenset("?:=!<>&|")  # operators that bind looser than ``+``: the string is not a concatenation
_RECEIVER_WINDOW = 512
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)  # contents are already blank; this removes the delimiters
_MAX_DEPTH = 8


@dataclass(frozen=True)
class Callout:
    """One resolved call site."""

    kind: str  # "namedcredential" | "externalendpoint"
    name: str  # the credential name (original case) or the lower-cased host
    confidence: str  # "EXTRACTED" | "INFERRED"
    reason: str | None  # why INFERRED: dynamic_suffix | non_final_static | receiver_unproven
    test_context: bool
    line: int


@dataclass(frozen=True)
class CalloutAnalysis:
    callouts: list[Callout]
    sites: int  # setEndpoint calls on a proven or unknown HttpRequest receiver
    unresolved: int  # of those, sites that did not end in an EXTRACTED edge


@dataclass(frozen=True)
class _Val:
    text: str  # the constant prefix of the value
    complete: bool  # the prefix is the whole value
    reason: str | None  # when incomplete: dynamic_suffix | non_final_static


class _Index:
    """Per-file lookup tables, built once: declared types per name, extra declarators, newline offsets."""

    def __init__(self, scrubbed: str) -> None:
        self.types: dict[str, list[str]] = {}
        for m in _DECL_RE.finditer(scrubbed):
            t = m.group(1).lower()
            if t not in _NOT_A_TYPE:
                self.types.setdefault(m.group(2).lower(), []).append(t)
        self.extra: dict[str, int] = {}
        for m in _EXTRA_DECL_RE.finditer(scrubbed):
            self.extra[m.group(1).lower()] = self.extra.get(m.group(1).lower(), 0) + 1
        self.newlines = [i for i, c in enumerate(scrubbed) if c == "\n"]

    def declarations(self, name: str) -> int:
        key = name.lower()
        return len(self.types.get(key, ())) + self.extra.get(key, 0)

    def line(self, offset: int) -> int:
        return bisect_right(self.newlines, offset - 1) + 1


def analyze_callouts(
    text: str,
    scrubbed: str,
    *,
    method_re: re.Pattern[str],
    brace_end: Callable[[str, int], int],
) -> CalloutAnalysis:
    """Resolve every ``setEndpoint`` call in one Apex source file."""
    calls = list(_SET_ENDPOINT_RE.finditer(scrubbed))
    if not calls:
        return CalloutAnalysis([], 0, 0)

    scrubbed = _COMMENT_RE.sub(lambda m: " " * len(m.group()), scrubbed)  # the scrubber keeps comment delimiters
    index = _Index(scrubbed)
    fields = _collect_fields(text, scrubbed, method_re, brace_end, index)
    test_spans = _test_spans(scrubbed, method_re, brace_end)
    callouts: list[Callout] = []
    sites = unresolved = 0

    for m in calls:
        receiver = _classify_receiver(scrubbed, m.start(), index)
        if receiver == "disproven":
            continue
        sites += 1
        arg_end = _paren_end(scrubbed, m.end() - 1)
        if arg_end < 0:
            unresolved += 1
            continue
        value = _evaluate(text, scrubbed, m.end(), arg_end, fields, set(), 0)
        callout = _resolve(value)
        if callout is None:
            unresolved += 1
            continue
        kind, name, confidence, reason = callout
        if confidence == "EXTRACTED" and receiver == "unknown":
            confidence, reason = "INFERRED", "receiver_unproven"
        if confidence != "EXTRACTED":
            unresolved += 1
        in_test = any(start <= m.start() < end for start, end in test_spans)
        callouts.append(Callout(kind, name, confidence, reason, in_test, index.line(m.start())))
    return CalloutAnalysis(callouts, sites, unresolved)


# ── receiver ─────────────────────────────────────────────────────────────────────────


def _classify_receiver(scrubbed: str, dot: int, index: _Index) -> str:
    """'proven', 'disproven' or 'unknown' for the expression before the ``.setEndpoint``."""
    before = scrubbed[max(0, dot - _RECEIVER_WINDOW) : dot].rstrip()
    if before.endswith(")"):
        open_paren = _open_paren_before(before, len(before) - 1)
        head = before[:open_paren].rstrip() if open_paren >= 0 else ""
        m = re.search(r"\bnew\s+([\w.]+)$", head, re.IGNORECASE)
        if m:
            return "proven" if m.group(1).lower() in _HTTP_REQUEST_TYPES else "disproven"
        return "unknown"
    chain = re.search(r"([A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)$", before)
    if not chain:
        return "unknown"
    parts = [p.strip() for p in chain.group(1).split(".")]
    if len(parts) > 2 or (len(parts) == 2 and parts[0].lower() != "this"):
        return "unknown"  # obj.field / this.a.b: the type is not visible here
    types = set(index.types.get(parts[-1].lower(), ()))
    if not types:
        return "unknown"
    if types <= _HTTP_REQUEST_TYPES:
        return "proven"
    if not types & _HTTP_REQUEST_TYPES:
        return "disproven"
    return "unknown"  # shadowed under different types


# ── value ────────────────────────────────────────────────────────────────────────────


def _collect_fields(
    text: str, scrubbed: str, method_re: re.Pattern[str], brace_end: Callable[[str, int], int], index: _Index
) -> dict[str, tuple[int, int, bool, bool]]:
    """Class-level ``String`` fields: lower-cased name -> (expr_start, expr_end, is_final, is_static).

    A name counts only if the whole file declares it exactly once, in any form (field, property, local, parameter,
    for-each variable, later declarator). Anything shadowed or redeclared anywhere is dynamic: failing closed here
    also covers locals the method-span check below misses (constructors, methods without modifiers).
    """
    method_spans = []
    for mm in method_re.finditer(scrubbed):
        method_spans.append((mm.start(), brace_end(scrubbed, mm.end() - 1)))
    fields: dict[str, tuple[int, int, bool, bool]] = {}
    for fm in _FIELD_RE.finditer(scrubbed):
        if any(start <= fm.start() < end for start, end in method_spans):
            continue
        mods = fm.group(1).lower()
        key = fm.group(2).lower()
        if index.declarations(key) != 1:
            fields[key] = (-1, -1, False, False)
            continue
        # a name declared twice is ambiguous: keep none of them
        if key in fields:
            fields[key] = (-1, -1, False, False)
            continue
        fields[key] = (
            fm.start(3),
            fm.end(3),
            bool(re.search(r"\bfinal\b", mods)),
            bool(re.search(r"\bstatic\b", mods)),
        )
    return fields


def _split_plus(scrubbed: str, start: int, end: int) -> list[tuple[int, int]]:
    """Top-level ``+`` operand ranges of ``scrubbed[start:end]`` (strings are already blanked)."""
    spans, depth, begin = [], 0, start
    for i in range(start, end):
        c = scrubbed[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "+" and depth == 0:
            spans.append((begin, i))
            begin = i + 1
    spans.append((begin, end))
    return spans


def _evaluate(
    text: str,
    scrubbed: str,
    start: int,
    end: int,
    fields: dict[str, tuple[int, int, bool, bool]],
    seen: set[str],
    depth: int,
) -> _Val:
    if _has_lower_precedence_operator(scrubbed, start, end):
        return _Val("", False, "dynamic_suffix")  # a ternary / comparison / assignment: not a plain concatenation
    prefix, complete, reason = "", True, None
    for a, b in _split_plus(scrubbed, start, end):
        if not complete:
            break
        a, b = _trim(scrubbed, a, b)
        while scrubbed[a:b].startswith("(") and _paren_end(scrubbed, a) == b - 1:
            a, b = _trim(scrubbed, a + 1, b - 1)
        op = _operand(text[a:b], scrubbed[a:b], text, scrubbed, fields, seen, depth)
        prefix += op.text
        if not op.complete:
            complete, reason = False, op.reason
    return _Val(prefix, complete, reason)


def _trim(scrubbed: str, a: int, b: int) -> tuple[int, int]:
    """Shrink [a, b) past surrounding whitespace *and blanked comments* (scrubbed text keeps offsets in step)."""
    seg = scrubbed[a:b]
    lead = len(seg) - len(seg.lstrip())
    return a + lead, b - (len(seg) - len(seg.rstrip()))


def _has_lower_precedence_operator(scrubbed: str, start: int, end: int) -> bool:
    depth = 0
    for i in range(start, end):
        c = scrubbed[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and c in _LOWER_PRECEDENCE:
            return True
    return False


def _operand(
    raw_op: str,
    scrub_op: str,
    text: str,
    scrubbed: str,
    fields: dict[str, tuple[int, int, bool, bool]],
    seen: set[str],
    depth: int,
) -> _Val:
    literal = re.fullmatch(r"(['\"]) *\1", scrub_op)
    if literal and raw_op[:1] == literal.group(1) and raw_op[-1:] == literal.group(1) and len(raw_op) >= 2:
        value = _unescape(raw_op[1:-1])
        if value is None:
            return _Val("", False, "dynamic_suffix")
        return _Val(value, True, None)
    if re.fullmatch(r"[A-Za-z_]\w*", scrub_op):
        key = scrub_op.lower()
        info = fields.get(key)
        if info is None or info[0] < 0 or depth >= _MAX_DEPTH or key in seen:
            return _Val("", False, "dynamic_suffix")
        a, b, is_final, is_static = info
        if not is_final:
            return _Val("", False, "non_final_static" if is_static else "dynamic_suffix")
        return _evaluate(text, scrubbed, a, b, fields, seen | {key}, depth + 1)
    return _Val("", False, "dynamic_suffix")


_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"'}


def _unescape(s: str) -> str | None:
    """Decode a string literal body, or None if it uses an escape this resolver does not model (``\\u``, ``\\r``...)."""
    out, i = [], 0
    while i < len(s):
        if s[i] != "\\":
            out.append(s[i])
            i += 1
            continue
        nxt = s[i + 1 : i + 2]
        if nxt not in _SIMPLE_ESCAPES:
            return None
        out.append(_SIMPLE_ESCAPES[nxt])
        i += 2
    return "".join(out)


def _resolve(value: _Val) -> tuple[str, str, str, str | None] | None:
    """(kind, name, confidence, reason) for an evaluated endpoint expression, or None if nothing is known."""
    prefix = value.text.strip()
    low = prefix.lower()
    if low.startswith("callout:"):
        rest = prefix[len("callout:") :]
        name_m = re.match(r"[^/?#\s]+", rest)
        if not name_m:
            return None
        name = name_m.group(0)
        terminated = len(rest) > len(name)
        if value.complete or terminated:
            return "namedcredential", name, "EXTRACTED", None
        return "namedcredential", name, "INFERRED", value.reason or "dynamic_suffix"
    if low.startswith(("http://", "https://")):
        authority_end = re.search(r"[/?#]", prefix[prefix.index("//") + 2 :])
        terminated = authority_end is not None
        if not (value.complete or terminated):
            return None  # a partial host is not an endpoint
        try:
            host = urlparse(prefix).hostname
        except ValueError:
            host = None
        if not host:
            return None
        return "externalendpoint", host, "EXTRACTED", None
    return None


# ── test context ─────────────────────────────────────────────────────────────────────


def _lead(scrubbed: str, start: int) -> str:
    """Text between the previous statement/brace boundary and *start* (annotations and modifiers live here)."""
    boundary = max(scrubbed.rfind(";", 0, start), scrubbed.rfind("}", 0, start), scrubbed.rfind("{", 0, start))
    return scrubbed[boundary + 1 : start]


def _test_spans(
    scrubbed: str, method_re: re.Pattern[str], brace_end: Callable[[str, int], int]
) -> list[tuple[int, int]]:
    """Character spans that are test code: @IsTest classes, @IsTest methods, ``testMethod`` methods."""
    spans: list[tuple[int, int]] = []
    for cm in _ANY_CLASS_HEADER_RE.finditer(scrubbed):
        if _IS_TEST_RE.search(_lead(scrubbed, cm.start())):
            spans.append((cm.start(), brace_end(scrubbed, cm.end() - 1)))
    for mm in method_re.finditer(scrubbed):
        signature = scrubbed[mm.start() : mm.end()].lower()
        if _IS_TEST_RE.search(_lead(scrubbed, mm.start())) or re.search(r"\btestmethod\b", signature):
            spans.append((mm.start(), brace_end(scrubbed, mm.end() - 1)))
    return spans


# ── small bracket helpers ────────────────────────────────────────────────────────────


def _paren_end(s: str, open_pos: int) -> int:
    """Index of the ``)`` matching the ``(`` at *open_pos* (strings must already be blanked), or -1."""
    depth = 0
    for i in range(open_pos, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _open_paren_before(s: str, close_pos: int) -> int:
    depth = 0
    for i in range(close_pos, -1, -1):
        if s[i] == ")":
            depth += 1
        elif s[i] == "(":
            depth -= 1
            if depth == 0:
                return i
    return -1

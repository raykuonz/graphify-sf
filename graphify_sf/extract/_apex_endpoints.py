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

    fields = _collect_fields(text, scrubbed, method_re, brace_end)
    test_spans = _test_spans(scrubbed, method_re, brace_end)
    callouts: list[Callout] = []
    sites = unresolved = 0

    for m in calls:
        receiver = _classify_receiver(scrubbed, m.start())
        if receiver == "disproven":
            continue
        arg_end = _paren_end(scrubbed, m.end() - 1)
        if arg_end < 0:
            sites += 1
            unresolved += 1
            continue
        sites += 1
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
        line = scrubbed.count("\n", 0, m.start()) + 1
        in_test = any(start <= m.start() < end for start, end in test_spans)
        callouts.append(Callout(kind, name, confidence, reason, in_test, line))
    return CalloutAnalysis(callouts, sites, unresolved)


# ── receiver ─────────────────────────────────────────────────────────────────────────


def _classify_receiver(scrubbed: str, dot: int) -> str:
    """'proven', 'disproven' or 'unknown' for the expression before the ``.setEndpoint``."""
    before = scrubbed[:dot].rstrip()
    if before.endswith(")"):
        open_paren = _open_paren_before(before, len(before) - 1)
        head = before[:open_paren].rstrip() if open_paren >= 0 else ""
        m = re.search(r"\bnew\s+([\w.]+)$", head, re.IGNORECASE)
        if m and m.group(1).lower() in _HTTP_REQUEST_TYPES:
            return "proven"
        return "unknown"
    chain = re.search(r"([A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)$", before)
    if not chain:
        return "unknown"
    parts = [p.strip() for p in chain.group(1).split(".")]
    if len(parts) > 1 and parts[0].lower() != "this":
        return "unknown"  # obj.field: its type is not visible here
    name = parts[-1]
    types = _declared_types(scrubbed, name)
    if not types:
        return "unknown"
    if types <= _HTTP_REQUEST_TYPES:
        return "proven"
    if not types & _HTTP_REQUEST_TYPES:
        return "disproven"
    return "unknown"  # shadowed under different types


def _declared_types(scrubbed: str, name: str) -> set[str]:
    pattern = re.compile(
        r"(?<![\w.])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?:<[^<>;(){}]*>)?(?:\[\])?\s+"
        + re.escape(name)
        + r"\b\s*(?=[=;,):])",
        re.IGNORECASE,
    )
    types = {m.group(1).lower() for m in pattern.finditer(scrubbed)}
    return {t for t in types if t not in _NOT_A_TYPE}


# ── value ────────────────────────────────────────────────────────────────────────────


def _collect_fields(
    text: str, scrubbed: str, method_re: re.Pattern[str], brace_end: Callable[[str, int], int]
) -> dict[str, tuple[int, int, bool, bool]]:
    """Class-level ``String`` fields: lower-cased name -> (expr_start, expr_end, is_final, is_static).

    Declarations inside a method body are locals and are skipped.
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
    prefix, complete, reason = "", True, None
    for a, b in _split_plus(scrubbed, start, end):
        raw_op, scrub_op = text[a:b].strip(), scrubbed[a:b].strip()
        while scrub_op.startswith("(") and scrub_op.endswith(")") and _paren_end(scrub_op, 0) == len(scrub_op) - 1:
            raw_op, scrub_op = raw_op[1:-1].strip(), scrub_op[1:-1].strip()
        op = _operand(raw_op, scrub_op, text, scrubbed, fields, seen, depth)
        if not complete:
            continue
        prefix += op.text
        if not op.complete:
            complete, reason = False, op.reason
    return _Val(prefix, complete, reason)


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
        return _Val(_unescape(raw_op[1:-1]), True, None)
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


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


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

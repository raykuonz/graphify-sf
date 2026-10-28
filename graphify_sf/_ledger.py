"""The coverage ledger: which analyses a graph.json was really built with.

graph.json carries a top-level ``graphify_sf`` block written only by a full pipeline run::

    {"version": "0.6.0",
     "analysis": {"callout-edges.apex": {"status": "complete", "eligible": 71, "analyzed": 71,
                                         "failed": 0, "sites": 3, "unresolved": 1}, ...},
     "capabilities": ["callout-edges.apex", ...]}

``capabilities`` lists the analyzers whose status is ``complete`` and is always *derived* from
``analysis`` (`derive_capabilities`). A consumer reads it to learn whether an absence of edges means
"nothing there" or "never looked": a graph without the block was never analysed. Graph-rewriting
commands (``cluster-only``, ``export json``) carry the block through untouched; the merge commands
write a status-only meet (`merged_ledger`), never counters.
"""

from __future__ import annotations

# Scope: "complete" is relative to what ``detect`` handed the extractors (so files skipped by .gitignore /
# .forceignore / .graphifysfignore, or in formats it does not read, are not "eligible"), and only single-file
# metadata is accounted: bundle (LWC / Aura) and document extraction are not part of any analyzer here.

# Analyzers the coordinator accounts for. ``enabled`` flips to True when the extractor that does the
# work ships; until then the analyzer reports ``not_run`` and no capability is advertised.
ANALYZERS: dict[str, dict] = {
    "callout-edges.apex": {"suffixes": (".cls", ".trigger"), "enabled": False},
    "callout-edges.flow-http": {"suffixes": (".flow-meta.xml",), "enabled": False},
}

# Worst to best. A merge keeps the lowest rank.
_RANK = {"not_run": 0, "failed": 1, "partial": 2, "complete": 3}


def status_for(eligible: int, failed: int) -> str:
    """Status of an analyzer that ran: complete iff nothing failed (zero eligible files is complete)."""
    if failed == 0:
        return "complete"
    return "failed" if failed >= eligible else "partial"


def derive_capabilities(analysis: dict) -> list[str]:
    """Names of the analyzers whose status is ``complete``, sorted."""
    return sorted(name for name, entry in (analysis or {}).items() if (entry or {}).get("status") == "complete")


def build_analysis(eligible_by_analyzer: dict[str, set], outcomes: dict) -> dict:
    """Per-analyzer ledger entries from the coordinator's outcome record.

    *eligible_by_analyzer* maps analyzer -> the set of eligible file paths; *outcomes* maps a path
    to ``(ok, sites, unresolved)`` for every file whose extractor returned. A path with no outcome
    (an exception, a lost worker) counts as failed, so ``analyzed + failed == eligible`` always holds.
    """
    analysis: dict[str, dict] = {}
    for name, spec in ANALYZERS.items():
        if not spec["enabled"]:
            analysis[name] = {"status": "not_run"}
            continue
        paths = eligible_by_analyzer.get(name, set())
        done = {p: outcomes[p] for p in paths if p in outcomes and outcomes[p][0]}
        eligible, analyzed = len(paths), len(done)
        failed = eligible - analyzed
        analysis[name] = {
            "status": status_for(eligible, failed),
            "eligible": eligible,
            "analyzed": analyzed,
            "failed": failed,
            "sites": sum(o[1] for o in done.values()),
            "unresolved": sum(o[2] for o in done.values()),
        }
    return analysis


def build_ledger(version: str, analysis: dict) -> dict:
    """The block a full pipeline run writes."""
    return {"version": version, "analysis": analysis, "capabilities": derive_capabilities(analysis)}


def merged_ledger(blocks: list[dict | None]) -> dict | None:
    """Status-only meet of several inputs' blocks, or None when no input has one.

    An input without a block, or without the analyzer, counts as ``not_run`` for it. The merged block
    carries no counters (eligible/analyzed/failed/sites of a merged graph have no truthful meaning) but
    lists the tool versions that produced the inputs. Malformed entries count as ``not_run``.
    """
    blocks = [b if isinstance(b, dict) else None for b in blocks]
    if not any(blocks):
        return None

    def analysis_of(block: dict | None) -> dict:
        analysis = (block or {}).get("analysis")
        return analysis if isinstance(analysis, dict) else {}

    def status_of(block: dict | None, name: str) -> str:
        entry = analysis_of(block).get(name)
        status = entry.get("status") if isinstance(entry, dict) else None
        return status if status in _RANK else "not_run"

    names = sorted({name for b in blocks for name in analysis_of(b)})
    analysis = {name: {"status": min((status_of(b, name) for b in blocks), key=_RANK.get)} for name in names}
    versions = sorted({str(b["version"]) for b in blocks if b and b.get("version")})
    merged = {"scope": "merged", "analysis": analysis, "capabilities": derive_capabilities(analysis)}
    if versions:
        merged["versions"] = versions
    return merged

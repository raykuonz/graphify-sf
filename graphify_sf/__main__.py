"""graphify-sf CLI — Salesforce SFDX project → knowledge graph."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("graphify-sf")
except Exception:
    __version__ = "dev"

_DEFAULT_OUT = os.environ.get("GRAPHIFY_SF_OUT", "graphify-sf-out")


def _default_graph_path() -> str:
    return str(Path(_DEFAULT_OUT) / "graph.json")


def _load_graph_from_json(path: Path):
    """Load a NetworkX graph from graph.json."""
    from networkx.readwrite import json_graph as _jg

    raw = json.loads(path.read_text(encoding="utf-8"))
    if "links" not in raw and "edges" in raw:
        raw = dict(raw, links=raw["edges"])
    try:
        return _jg.node_link_graph(raw, edges="links"), raw
    except TypeError:
        return _jg.node_link_graph(raw), raw


def _derive_community_labels(G, communities: dict) -> dict[int, str]:
    """Derive community label from the highest-degree non-method node."""
    labels: dict[int, str] = {}
    from graphify_sf.analyze import _is_file_node

    for cid, nodes in communities.items():
        real_nodes = [n for n in nodes if not _is_file_node(G, n)]
        if not real_nodes:
            labels[cid] = f"Community {cid}"
            continue
        top = max(real_nodes, key=lambda n: G.degree(n))
        label = G.nodes[top].get("label", top)
        labels[cid] = label
    return labels


def _run_llm_extraction(
    target: Path,
    detection: dict,
    extraction: dict,
    backend: str,
    token_budget: int,
    token_cost: dict,
) -> None:
    """Run LLM semantic extraction and merge results into *extraction* in-place.

    Collects all metadata files from the detection result, sends them to the
    LLM backend in token-budget chunks, and appends any new nodes/edges
    (marked INFERRED) into *extraction["nodes"]* / *extraction["edges"]*.

    Mutates *token_cost* with ``{"input": N, "output": N}`` for the report.
    """
    from graphify_sf.llm import (
        BACKENDS,
        estimate_cost,
        extract_corpus_parallel,
    )
    from graphify_sf.llm import (
        detect_backend as _detect_backend,
    )

    # Resolve backend (auto-detect if not specified)
    effective_backend = backend
    if effective_backend == "auto":
        effective_backend = _detect_backend()
        if not effective_backend:
            print(
                "[graphify-sf] --backend auto: no API key found "
                "(ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, etc.) — "
                "skipping LLM extraction",
                file=sys.stderr,
            )
            return
        print(f"[graphify-sf] --backend auto → detected backend: {effective_backend}")

    if effective_backend not in BACKENDS:
        print(
            f"[graphify-sf] unknown backend '{effective_backend}'. Available: {sorted(BACKENDS)}",
            file=sys.stderr,
        )
        return

    # Collect all metadata files from the detection result
    all_files: list[Path] = []
    files_by_type = detection.get("files", {})
    for _ftype, file_list in files_by_type.items():
        for f in file_list:
            p = Path(f)
            if p.exists():
                all_files.append(p)

    if not all_files:
        print("[graphify-sf] LLM extraction: no files to process — skipping", file=sys.stderr)
        return

    total_chunks_done = [0]
    total_chunks = [0]  # filled after chunking

    def _on_chunk_done(idx: int, total: int, result: dict) -> None:
        total_chunks[0] = total
        total_chunks_done[0] += 1
        n_in = result.get("input_tokens", 0)
        n_out = result.get("output_tokens", 0)
        n_nodes = len(result.get("nodes", []))
        n_edges = len(result.get("edges", []))
        elapsed = result.get("elapsed_seconds", 0.0)
        cost = estimate_cost(effective_backend, n_in, n_out)
        print(
            f"[graphify-sf] LLM chunk {total_chunks_done[0]}/{total}: "
            f"{n_nodes} nodes, {n_edges} edges "
            f"({n_in}→{n_out} tokens, ${cost:.4f}, {elapsed:.1f}s)",
            flush=True,
        )

    print(
        f"[graphify-sf] LLM extraction: {len(all_files)} files → backend={effective_backend} "
        f"token-budget={token_budget}",
        flush=True,
    )

    try:
        llm_result = extract_corpus_parallel(
            all_files,
            backend=effective_backend,
            root=target,
            on_chunk_done=_on_chunk_done,
            token_budget=token_budget,
        )
    except Exception as exc:
        print(f"[graphify-sf] LLM extraction failed: {exc}", file=sys.stderr)
        return

    llm_nodes = llm_result.get("nodes", [])
    llm_edges = llm_result.get("edges", [])
    in_tok = llm_result.get("input_tokens", 0)
    out_tok = llm_result.get("output_tokens", 0)
    total_cost = estimate_cost(effective_backend, in_tok, out_tok)

    print(
        f"[graphify-sf] LLM extraction complete: "
        f"{len(llm_nodes)} nodes, {len(llm_edges)} edges "
        f"({in_tok}→{out_tok} tokens, ${total_cost:.4f})",
        flush=True,
    )

    # Merge into static extraction (LLM may produce nodes that already exist by label;
    # deduplicate_by_label in the pipeline will consolidate them)
    extraction["nodes"].extend(llm_nodes)
    extraction["edges"].extend(llm_edges)

    # Record token cost for the report
    token_cost["input"] += in_tok
    token_cost["output"] += out_tok


def _run_pipeline(
    target: Path,
    out_dir: Path,
    *,
    update: bool = False,
    directed: bool = False,
    no_viz: bool = False,
    max_workers: int | None = None,
    force: bool = False,
    backend: str | None = None,
    token_budget: int = 40_000,
) -> None:
    """Full pipeline: detect → extract → [LLM] → build → cluster → report → export."""
    from graphify_sf.analyze import god_nodes, suggest_questions, surprising_connections
    from graphify_sf.build import build_from_json, build_merge_sf, deduplicate_by_label
    from graphify_sf.cluster import cluster, score_all
    from graphify_sf.detect import detect, detect_incremental, save_manifest
    from graphify_sf.export import to_html, to_json
    from graphify_sf.extract import extract
    from graphify_sf.report import generate

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    graph_json_path = out_dir / "graph.json"

    incremental = update and manifest_path.exists() and graph_json_path.exists()

    if incremental:
        print(f"[graphify-sf] incremental scan of {target}")
        detection = detect_incremental(target, manifest_path=str(manifest_path))
    else:
        print(f"[graphify-sf] scanning {target}")
        detection = detect(target)

    total = detection.get("total_files", 0)
    skipped = detection.get("skipped", 0)
    warning = detection.get("warning", "")
    if warning:
        print(f"[graphify-sf] WARNING: {warning}", file=sys.stderr)

    print(f"[graphify-sf] {total} metadata files found, {skipped} skipped")

    if total == 0:
        print("[graphify-sf] no Salesforce metadata files found — nothing to extract", file=sys.stderr)
        sys.exit(1)

    # Phase 1+2: Extract all metadata (static XML/source parsing)
    print("[graphify-sf] extracting metadata...", flush=True)
    extraction = extract(detection, parallel=True, max_workers=max_workers)
    n_nodes = len(extraction.get("nodes", []))
    n_edges = len(extraction.get("edges", []))
    print(f"[graphify-sf] extracted {n_nodes} nodes, {n_edges} edges")

    # Phase 2b: LLM semantic extraction (optional — only when --backend is given)
    token_cost: dict = {"input": 0, "output": 0}
    if backend:
        _run_llm_extraction(target, detection, extraction, backend, token_budget, token_cost)

    # Dedup by label
    nodes, edges = deduplicate_by_label(extraction["nodes"], extraction["edges"])

    new_extraction = {"nodes": nodes, "edges": edges}

    # Build graph (incremental or fresh)
    if incremental:
        print("[graphify-sf] merging with existing graph...", flush=True)
        G = build_merge_sf(new_extraction, graph_json_path, directed=directed)
    else:
        G = build_from_json(new_extraction, directed=directed)

    print(f"[graphify-sf] graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    if G.number_of_nodes() == 0:
        print("[graphify-sf] error: graph is empty after extraction", file=sys.stderr)
        sys.exit(1)

    # Cluster
    print("[graphify-sf] clustering...", flush=True)
    communities = cluster(G)
    cohesion = score_all(G, communities)
    print(f"[graphify-sf] {len(communities)} communities found")

    # Analysis
    labels = _derive_community_labels(G, communities)
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)
    questions = suggest_questions(G, communities, labels)

    # Report
    from graphify_sf.export import _git_head

    commit = _git_head()
    report = generate(
        G,
        communities,
        cohesion,
        labels,
        gods,
        surprises,
        detection,
        token_cost,
        str(target),
        suggested_questions=questions,
        built_at_commit=commit,
    )
    report_path = out_dir / "GRAPH_REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"[graphify-sf] wrote {report_path}")

    # Write graph.json
    written = to_json(G, communities, str(graph_json_path), force=force, built_at_commit=commit)
    if written:
        print(f"[graphify-sf] wrote {graph_json_path}")
    else:
        print(
            "[graphify-sf] WARNING: graph.json not updated (new graph is smaller — use --force to override)",
            file=sys.stderr,
        )

    # Write community labels sidecar
    labels_path = out_dir / ".graphify_sf_labels.json"
    labels_path.write_text(
        json.dumps({str(k): v for k, v in labels.items()}, ensure_ascii=False),
        encoding="utf-8",
    )

    # Save manifest
    try:
        save_manifest(detection.get("files", {}), manifest_path=str(manifest_path))
    except Exception as exc:
        print(f"[graphify-sf] WARNING: could not write manifest: {exc}", file=sys.stderr)

    # HTML viz
    html_path = out_dir / "graph.html"
    if no_viz:
        if html_path.exists():
            html_path.unlink()
        print("[graphify-sf] skipped graph.html (--no-viz)")
    else:
        try:
            to_html(
                G,
                communities,
                str(html_path),
                community_labels=labels,
                node_limit=int(os.environ.get("GRAPHIFY_SF_VIZ_NODE_LIMIT", "5000")),
            )
            print(f"[graphify-sf] wrote {html_path}")
        except ValueError as exc:
            print(f"[graphify-sf] WARNING: {exc}", file=sys.stderr)
            if html_path.exists():
                html_path.unlink()

    print("\n[graphify-sf] done")
    print(f"  {G.number_of_nodes()} nodes · {G.number_of_edges()} edges · {len(communities)} communities")
    print(f"  Report: {report_path}")
    print(f"  Graph:  {graph_json_path}")
    if not no_viz and html_path.exists():
        print(f"  HTML:   {html_path}")


def _cmd_cluster_only(target: Path, out_dir: Path, *, no_viz: bool = False, graph_path: Path | None = None) -> None:
    """Re-cluster an existing graph.json and regenerate report + html."""
    from graphify_sf.analyze import god_nodes, suggest_questions, surprising_connections
    from graphify_sf.cluster import cluster, score_all
    from graphify_sf.export import _git_head, to_html, to_json
    from graphify_sf.report import generate

    gp = graph_path or (out_dir / "graph.json")
    if not gp.exists():
        print(f"error: no graph found at {gp} — run graphify-sf first", file=sys.stderr)
        sys.exit(1)

    print(f"[graphify-sf] loading {gp} for re-clustering...")
    G, raw = _load_graph_from_json(gp)
    print(f"[graphify-sf] graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    print("[graphify-sf] clustering...", flush=True)
    communities = cluster(G)
    cohesion = score_all(G, communities)

    labels_path = out_dir / ".graphify_sf_labels.json"
    if labels_path.exists():
        try:
            labels = {int(k): v for k, v in json.loads(labels_path.read_text(encoding="utf-8")).items()}
        except Exception:
            labels = _derive_community_labels(G, communities)
    else:
        labels = _derive_community_labels(G, communities)

    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)
    questions = suggest_questions(G, communities, labels)

    token_cost = {"input": 0, "output": 0}
    commit = _git_head()
    report = generate(
        G,
        communities,
        cohesion,
        labels,
        gods,
        surprises,
        {"warning": "cluster-only mode — file stats not available"},
        token_cost,
        str(target),
        suggested_questions=questions,
        built_at_commit=commit,
    )
    report_path = out_dir / "GRAPH_REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    to_json(G, communities, str(gp), built_at_commit=commit)
    labels_path.write_text(
        json.dumps({str(k): v for k, v in labels.items()}, ensure_ascii=False),
        encoding="utf-8",
    )

    html_path = out_dir / "graph.html"
    if no_viz:
        if html_path.exists():
            html_path.unlink()
        print(f"Done — {len(communities)} communities. GRAPH_REPORT.md and graph.json updated (--no-viz).")
    else:
        try:
            to_html(G, communities, str(html_path), community_labels=labels)
            print(f"Done — {len(communities)} communities. GRAPH_REPORT.md, graph.json, graph.html updated.")
        except ValueError as exc:
            if html_path.exists():
                html_path.unlink()
            print(f"Skipped graph.html: {exc}")
            print(f"Done — {len(communities)} communities. GRAPH_REPORT.md and graph.json updated.")


def _cmd_query(question: str, graph_path: Path, *, use_dfs: bool = False, budget: int = 2000) -> None:
    """BFS/DFS traversal of graph.json for a question."""
    G, _ = _load_graph_from_json(graph_path)
    tokens = question.lower().split()
    # Score nodes by label overlap with question tokens
    scores: list[tuple[float, str]] = []
    for nid, data in G.nodes(data=True):
        label = data.get("label", nid).lower()
        score = sum(1 for t in tokens if t in label)
        if score > 0:
            scores.append((score, nid))
    if not scores:
        print(f"No matching nodes found for: {question}")
        return
    scores.sort(reverse=True)
    top_nid = scores[0][1]
    top_label = G.nodes[top_nid].get("label", top_nid)

    # BFS/DFS traversal
    visited: set[str] = set()
    result_lines: list[str] = []
    result_lines.append(f"Nodes related to: {question}")
    result_lines.append(f"Starting from: {top_label}")
    result_lines.append("")

    from collections import deque

    queue: deque[tuple[str, int]] = deque([(top_nid, 0)])
    char_budget = budget * 4  # rough tokens→chars

    while queue and sum(len(ln) for ln in result_lines) < char_budget:
        nid, depth = queue.popleft() if not use_dfs else queue.pop()
        if nid in visited:
            continue
        visited.add(nid)
        indent = "  " * depth
        data = G.nodes[nid]
        label = data.get("label", nid)
        sf_type = data.get("sf_type", "")
        source = data.get("source_file", "")
        type_tag = f" ({sf_type})" if sf_type else ""
        source_tag = f" — {source}" if source else ""
        result_lines.append(f"{indent}• {label}{type_tag}{source_tag}")

        if depth < 2:
            for nb in sorted(G.neighbors(nid), key=lambda n: G.degree(n), reverse=True)[:5]:
                queue.append((nb, depth + 1))

    print("\n".join(result_lines))


def _cmd_path(source_label: str, target_label: str, graph_path: Path) -> None:
    """Shortest path between two nodes."""
    import networkx as _nx

    G, _ = _load_graph_from_json(graph_path)

    def _find(label: str) -> str | None:
        q = label.lower()
        candidates: list[tuple[int, str]] = []
        for nid, data in G.nodes(data=True):
            lbl = data.get("label", nid).lower()
            if q == lbl:
                return nid
            if q in lbl:
                candidates.append((len(lbl), nid))
        if candidates:
            return min(candidates, key=lambda x: x[0])[1]
        return None

    src_nid = _find(source_label)
    if not src_nid:
        print(f"No node matching '{source_label}' found.")
        sys.exit(1)
    tgt_nid = _find(target_label)
    if not tgt_nid:
        print(f"No node matching '{target_label}' found.")
        sys.exit(1)

    try:
        path_nodes = _nx.shortest_path(G, src_nid, tgt_nid)
    except (_nx.NetworkXNoPath, _nx.NodeNotFound):
        print(f"No path found between '{source_label}' and '{target_label}'.")
        sys.exit(0)

    from graphify_sf.build import edge_data

    hops = len(path_nodes) - 1
    segments = []
    for i in range(len(path_nodes) - 1):
        u, v = path_nodes[i], path_nodes[i + 1]
        edata = edge_data(G, u, v)
        rel = edata.get("relation", "")
        conf = edata.get("confidence", "")
        conf_str = f" [{conf}]" if conf else ""
        if i == 0:
            segments.append(G.nodes[u].get("label", u))
        segments.append(f"--{rel}{conf_str}--> {G.nodes[v].get('label', v)}")
    print(f"Shortest path ({hops} hops):\n  " + " ".join(segments))


def _cmd_explain(label: str, graph_path: Path, relation: str | None = None) -> None:
    """Explain a node and its neighbors.

    When *relation* is provided only connections with that edge relation are
    shown and the top-20 cap is lifted so every match is visible.
    """
    G, _ = _load_graph_from_json(graph_path)

    q = label.lower()
    candidates: list[tuple[int, str]] = []
    for nid, data in G.nodes(data=True):
        lbl = data.get("label", nid).lower()
        if q == lbl:
            candidates = [(0, nid)]
            break
        if q in lbl:
            candidates.append((len(lbl), nid))
    if not candidates:
        print(f"No node matching '{label}' found.")
        sys.exit(0)
    nid = min(candidates, key=lambda x: x[0])[1]

    d = G.nodes[nid]
    print(f"Node: {d.get('label', nid)}")
    print(f"  ID:        {nid}")
    print(f"  SF Type:   {d.get('sf_type', '')}")
    print(f"  File Type: {d.get('file_type', '')}")
    print(f"  Source:    {d.get('source_file', '')} {d.get('source_location', '')}".rstrip())
    print(f"  Community: {d.get('community', '')}")
    print(f"  Degree:    {G.degree(nid)}")
    neighbors = list(G.neighbors(nid))
    if neighbors:
        from graphify_sf.build import edge_data

        if relation:
            # Filter to matching relation — show ALL matches (no cap)
            filtered = [nb for nb in neighbors if edge_data(G, nid, nb).get("relation") == relation]
            print(f"\nConnections with relation={relation} ({len(filtered)}):")
            for nb in sorted(filtered, key=lambda n: G.degree(n), reverse=True):
                edata = edge_data(G, nid, nb)
                conf = edata.get("confidence", "")
                print(f"  --> {G.nodes[nb].get('label', nb)} [{relation}] [{conf}]")
            if not filtered:
                print("  (none)")
        else:
            print(f"\nConnections ({len(neighbors)}):")
            for nb in sorted(neighbors, key=lambda n: G.degree(n), reverse=True)[:20]:
                edata = edge_data(G, nid, nb)
                rel = edata.get("relation", "")
                conf = edata.get("confidence", "")
                print(f"  --> {G.nodes[nb].get('label', nb)} [{rel}] [{conf}]")
            if len(neighbors) > 20:
                print(f"  ... and {len(neighbors) - 20} more")


def _cmd_stats(graph_path: Path) -> None:
    """Print detailed graph statistics: type distribution, density, degree stats."""
    from collections import Counter

    G, _ = _load_graph_from_json(graph_path)

    n_nodes = G.number_of_nodes()
    n_edges = G.number_of_edges()
    density = (2 * n_edges / (n_nodes * (n_nodes - 1))) if n_nodes > 1 else 0.0

    # Node type distribution
    sf_types = Counter(d.get("sf_type", "unknown") or "unknown" for _, d in G.nodes(data=True))
    file_types = Counter(d.get("file_type", "unknown") or "unknown" for _, d in G.nodes(data=True))

    # Edge relation distribution
    relations = Counter(d.get("relation", "unknown") or "unknown" for _, _, d in G.edges(data=True))
    confidences = Counter(d.get("confidence", "EXTRACTED") or "EXTRACTED" for _, _, d in G.edges(data=True))

    # Degree stats
    degrees = [d for _, d in G.degree()]
    avg_deg = sum(degrees) / len(degrees) if degrees else 0.0
    max_deg = max(degrees, default=0)
    isolated = sum(1 for d in degrees if d == 0)

    # Community distribution
    community_counts: Counter = Counter()
    for _, data in G.nodes(data=True):
        cid = data.get("community")
        if cid is not None:
            community_counts[int(cid)] += 1

    print("Graph Statistics")
    print(f"  Nodes:          {n_nodes}")
    print(f"  Edges:          {n_edges}")
    print(f"  Communities:    {len(community_counts)}")
    print(f"  Density:        {density:.6f}")
    print(f"  Avg degree:     {avg_deg:.2f}")
    print(f"  Max degree:     {max_deg}")
    print(f"  Isolated nodes: {isolated}")
    print()

    print("Node Types (sf_type):")
    for sf_type, count in sf_types.most_common():
        bar = "#" * min(count, 40)
        print(f"  {sf_type:30s} {count:5d}  {bar}")
    print()

    if len(file_types) > 1:
        print("Node Types (file_type):")
        for ft, count in file_types.most_common():
            bar = "#" * min(count, 40)
            print(f"  {ft:30s} {count:5d}  {bar}")
        print()

    print("Edge Relations:")
    for rel, count in relations.most_common():
        bar = "#" * min(count, 40)
        print(f"  {rel:30s} {count:5d}  {bar}")
    print()

    print("Edge Confidence:")
    for conf, count in confidences.most_common():
        bar = "#" * min(count, 40)
        print(f"  {conf:30s} {count:5d}  {bar}")
    print()

    print("Top 10 Nodes by Degree:")
    top = sorted(G.nodes(data=True), key=lambda x: G.degree(x[0]), reverse=True)[:10]
    for nid, data in top:
        label = data.get("label", nid)
        sf_type = data.get("sf_type", "")
        deg = G.degree(nid)
        type_tag = f" ({sf_type})" if sf_type else ""
        print(f"  {deg:4d}  {label}{type_tag}")


def _cmd_check_update(target: Path, out_dir: Path) -> None:
    """Dry-run diff: report what files have changed since last run without extracting."""
    from graphify_sf.detect import detect_incremental, load_manifest

    manifest_path = out_dir / "manifest.json"

    if not manifest_path.exists():
        print(f"[graphify-sf] no manifest found at {manifest_path}")
        print("[graphify-sf] run 'graphify-sf <path>' first to build the initial graph")
        sys.exit(1)

    print(f"[graphify-sf] scanning {target} for changes since last run...")
    detection = detect_incremental(target, manifest_path=str(manifest_path))

    new_files = detection.get("new_files", {})
    unchanged_files = detection.get("unchanged_files", {})
    total_files = detection.get("total_files", 0)

    changed_count = sum(len(v) for v in new_files.values())
    unchanged_count = sum(len(v) for v in unchanged_files.values())

    # Detect deleted files (in manifest but not in current scan)
    manifest = load_manifest(str(manifest_path))
    all_current = {f for files in detection.get("files", {}).values() for f in files}
    deleted = [f for f in manifest if f not in all_current]

    print(f"[graphify-sf] {total_files} files scanned")
    print(f"  changed:   {changed_count}")
    print(f"  deleted:   {len(deleted)}")
    print(f"  unchanged: {unchanged_count}")

    if changed_count > 0:
        print()
        print("Changed files:")
        for ftype, files in sorted(new_files.items()):
            for f in sorted(files):
                rel = f
                try:
                    rel = str(Path(f).relative_to(target))
                except ValueError:
                    pass
                print(f"  M {ftype:12s}  {rel}")

    if deleted:
        print()
        print("Deleted files:")
        for f in sorted(deleted):
            rel = f
            try:
                rel = str(Path(f).relative_to(target))
            except ValueError:
                pass
            print(f"  D              {rel}")

    if changed_count == 0 and not deleted:
        print("[graphify-sf] no changes detected — graph is up to date")
        sys.exit(0)
    else:
        print()
        print(f"[graphify-sf] {changed_count + len(deleted)} file(s) would be re-extracted by --update")
        sys.exit(1)


def _cmd_merge_graphs(graph_paths: list[Path], out_path: Path, *, no_viz: bool = False) -> None:
    """Merge multiple graph.json files into a single combined graph."""

    from graphify_sf.analyze import god_nodes, suggest_questions, surprising_connections
    from graphify_sf.build import build_from_json, deduplicate_by_label
    from graphify_sf.cluster import cluster, score_all
    from graphify_sf.export import _git_head, to_html, to_json
    from graphify_sf.report import generate

    if len(graph_paths) < 2:
        print("error: merge-graphs requires at least 2 graph.json paths", file=sys.stderr)
        sys.exit(1)

    for gp in graph_paths:
        if not gp.exists():
            print(f"error: graph not found: {gp}", file=sys.stderr)
            sys.exit(1)

    # Load all graphs
    import networkx as nx

    merged = nx.Graph()
    for gp in graph_paths:
        print(f"[graphify-sf] loading {gp}...")
        G_i, raw_i = _load_graph_from_json(gp)
        print(f"  {G_i.number_of_nodes()} nodes, {G_i.number_of_edges()} edges")
        merged.update(G_i)

    print(f"[graphify-sf] merged: {merged.number_of_nodes()} nodes, {merged.number_of_edges()} edges (before dedup)")

    # Dedup by label
    nodes_data = [{"id": nid, **data} for nid, data in merged.nodes(data=True)]
    edges_data = [{"source": u, "target": v, **data} for u, v, data in merged.edges(data=True)]
    nodes_dedup, edges_dedup = deduplicate_by_label(nodes_data, edges_data)
    G = build_from_json({"nodes": nodes_dedup, "edges": edges_dedup})

    print(f"[graphify-sf] after dedup: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Cluster
    print("[graphify-sf] clustering...", flush=True)
    communities = cluster(G)
    cohesion = score_all(G, communities)
    labels = _derive_community_labels(G, communities)
    print(f"[graphify-sf] {len(communities)} communities")

    # Analysis
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)
    questions = suggest_questions(G, communities, labels)

    # Report + export
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    token_cost = {"input": 0, "output": 0}
    commit = _git_head()
    report = generate(
        G,
        communities,
        cohesion,
        labels,
        gods,
        surprises,
        {"warning": f"merged from {len(graph_paths)} graphs"},
        token_cost,
        "merged",
        suggested_questions=questions,
        built_at_commit=commit,
    )
    report_path = out_dir / "GRAPH_REPORT.md"
    report_path.write_text(report, encoding="utf-8")

    to_json(G, communities, str(out_path), force=True, built_at_commit=commit)

    import json as _json

    labels_path = out_dir / ".graphify_sf_labels.json"
    labels_path.write_text(
        _json.dumps({str(k): v for k, v in labels.items()}, ensure_ascii=False),
        encoding="utf-8",
    )

    if not no_viz:
        html_path = out_dir / "graph.html"
        try:
            to_html(G, communities, str(html_path), community_labels=labels)
            print(f"[graphify-sf] wrote {html_path}")
        except ValueError as exc:
            print(f"[graphify-sf] WARNING: {exc}", file=sys.stderr)

    print("\n[graphify-sf] merge done")
    print(f"  {G.number_of_nodes()} nodes · {G.number_of_edges()} edges · {len(communities)} communities")
    print(f"  Report: {report_path}")
    print(f"  Graph:  {out_path}")


def _cmd_merge_driver(base: Path, ours: Path, theirs: Path) -> None:
    """Git merge driver for graph.json: union merge instead of text conflict.

    Registered via: graphify-sf merge-driver install
    Git calls it as: graphify-sf merge-driver run %O %A %B

    The result is written to `ours` (the %A file) in-place, which is what
    git expects from a custom merge driver.
    """
    from graphify_sf.build import build_from_json, deduplicate_by_label
    from graphify_sf.cluster import cluster
    from graphify_sf.export import to_json

    def _load(p: Path):
        if not p.exists():
            return {"nodes": [], "links": []}
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if "links" not in raw and "edges" in raw:
                raw["links"] = raw["edges"]
            return raw
        except Exception:
            return {"nodes": [], "links": []}

    base_data = _load(base)
    our_data = _load(ours)
    their_data = _load(theirs)

    # Union all nodes and edges by id
    all_nodes: dict[str, dict] = {}
    all_edges: list[dict] = []
    seen_edges: set[tuple] = set()

    for data in (base_data, our_data, their_data):
        for node in data.get("nodes", []):
            nid = node.get("id", "")
            if nid and nid not in all_nodes:
                all_nodes[nid] = node
        links_key = "links" if "links" in data else "edges"
        for edge in data.get(links_key, []):
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            rel = edge.get("relation", "")
            key = (src, tgt, rel)
            if key not in seen_edges:
                seen_edges.add(key)
                all_edges.append(edge)

    extraction = {"nodes": list(all_nodes.values()), "edges": all_edges}
    nodes_dedup, edges_dedup = deduplicate_by_label(extraction["nodes"], extraction["edges"])
    G = build_from_json({"nodes": nodes_dedup, "edges": edges_dedup})
    communities = cluster(G)
    to_json(G, communities, str(ours), force=True)
    print(f"[graphify-sf] merge-driver: merged {G.number_of_nodes()} nodes, {G.number_of_edges()} edges → {ours}")


def _cmd_merge_driver_setup(action: str) -> None:
    """Install or uninstall the graphify-sf git merge driver."""
    git_root = _find_git_root()
    if git_root is None:
        print("error: not inside a git repository", file=sys.stderr)
        sys.exit(1)

    gitattributes = git_root / ".gitattributes"
    gitconfig = git_root / ".git" / "config"

    _DRIVER_ATTR = "graph.json merge=graphify-sf-merge"
    _DRIVER_CONF = '[merge "graphify-sf-merge"]\n\tname = graphify-sf graph.json merge driver\n\tdriver = graphify-sf merge-driver run %O %A %B\n'

    if action == "install":
        # .gitattributes
        if gitattributes.exists():
            content = gitattributes.read_text(encoding="utf-8")
            if "graphify-sf-merge" not in content:
                content = content.rstrip() + "\n" + _DRIVER_ATTR + "\n"
                gitattributes.write_text(content, encoding="utf-8")
        else:
            gitattributes.write_text(_DRIVER_ATTR + "\n", encoding="utf-8")

        # .git/config
        conf_content = gitconfig.read_text(encoding="utf-8") if gitconfig.exists() else ""
        if "graphify-sf-merge" not in conf_content:
            with gitconfig.open("a", encoding="utf-8") as f:
                f.write("\n" + _DRIVER_CONF)

        print("graphify-sf merge driver installed")
        print(f"  .gitattributes: {gitattributes}")
        print(f"  .git/config:    {gitconfig}")

    elif action == "uninstall":
        import re as _re

        if gitattributes.exists():
            content = gitattributes.read_text(encoding="utf-8")
            updated = "\n".join(ln for ln in content.splitlines() if "graphify-sf-merge" not in ln)
            gitattributes.write_text(updated.strip() + "\n" if updated.strip() else "", encoding="utf-8")

        if gitconfig.exists():
            content = gitconfig.read_text(encoding="utf-8")
            updated = _re.sub(
                r'\n?\[merge "graphify-sf-merge"\][^\[]*',
                "",
                content,
                flags=_re.DOTALL,
            ).rstrip()
            gitconfig.write_text(updated + "\n", encoding="utf-8")

        print("graphify-sf merge driver uninstalled")


# ---------------------------------------------------------------------------
# Install: platform config
# Each entry maps platform name → relative skills subdir (no leading slash).
# For --scope global  the base is Path.home().
# For --scope project the base is Path(".").
# All platforms (including Cursor) use SKILL.md — no per-platform transforms needed.
# ---------------------------------------------------------------------------
_PLATFORM_SKILLS_DIR: dict[str, str] = {
    "claude": ".claude/skills/graphify-sf",
    "codex": ".agents/skills/graphify-sf",
    "cursor": ".cursor/skills/graphify-sf",
    "opencode": ".config/opencode/skills/graphify-sf",
    "aider": ".aider/graphify-sf",
    "copilot": ".copilot/skills/graphify-sf",
    "kiro": ".kiro/skills/graphify-sf",
    "gemini": ".gemini/skills/graphify-sf",
    "trae": ".trae/skills/graphify-sf",
    "trae-cn": ".trae-cn/skills/graphify-sf",
    "hermes": ".hermes/skills/graphify-sf",
    "droid": ".factory/skills/graphify-sf",
    "pi": ".pi/agent/skills/graphify-sf",
    "antigravity": ".agents/skills/graphify-sf",
    "kimi": ".kimi/skills/graphify-sf",
}

_ALL_PLATFORMS = sorted(_PLATFORM_SKILLS_DIR)


def _atomic_write(dest: Path, src: Path) -> None:
    """Copy src → dest atomically using a temp file + os.replace()."""
    import shutil

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# Platforms whose install dir IS .agents/skills/graphify-sf — the canonical location
_AGENTS_NATIVE_PLATFORMS = {k for k, v in _PLATFORM_SKILLS_DIR.items() if v == ".agents/skills/graphify-sf"}


def _install_with_link(platform: str, scope: str, skill_src: Path) -> None:
    """Write one canonical copy to .agents/skills/graphify-sf/ and symlink from platform path.

    Project scope:  ./.agents/skills/graphify-sf/SKILL.md  (relative symlink — portable)
    Global scope:  ~/.agents/skills/graphify-sf/SKILL.md  (absolute symlink — reliable)

    All platforms (including Cursor) use the same SKILL.md format — no transforms needed.
    """
    import shutil

    base = Path(".") if scope == "project" else Path.home()
    scope_label = "project" if scope == "project" else "global"

    # ── write canonical ───────────────────────────────────────────
    canonical_dir = base / ".agents" / "skills" / "graphify-sf"
    canonical_dir.mkdir(parents=True, exist_ok=True)
    canonical = canonical_dir / "SKILL.md"
    _atomic_write(canonical, skill_src)
    (canonical_dir / ".graphify_sf_version").write_text(__version__, encoding="utf-8")
    print(f"graphify-sf canonical skill → {canonical}")

    # Platforms that already live in .agents/ — canonical IS their install path
    if platform in _AGENTS_NATIVE_PLATFORMS:
        _print_install_footer(scope)
        return

    # ── resolve platform destination ──────────────────────────────
    if platform == "claude" and os.environ.get("CLAUDE_CONFIG_DIR") and scope == "global":
        dest_dir = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "skills" / "graphify-sf"
    else:
        dest_dir = base / _PLATFORM_SKILLS_DIR[platform]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "SKILL.md"

    # Remove stale file or old symlink
    if dest.is_symlink() or dest.exists():
        dest.unlink(missing_ok=True)

    # Relative symlink for project scope (stays valid if the project dir moves),
    # absolute for global scope (stays valid regardless of cwd).
    link_target: Path
    if scope == "project":
        link_target = Path(os.path.relpath(canonical, dest_dir))
    else:
        link_target = canonical.resolve()

    try:
        dest.symlink_to(link_target)
        print(f"graphify-sf symlink [{platform}/{scope_label}] → {dest} → {link_target}")
    except OSError as exc:
        # Fallback for Windows (symlinks need elevated permissions by default)
        print(
            f"warning: symlink failed ({exc}) — falling back to regular copy",
            file=sys.stderr,
        )
        shutil.copy2(skill_src, dest)
        print(f"graphify-sf skill installed [{platform}/{scope_label}] → {dest}")

    _print_install_footer(scope)


def _cmd_install(platform: str = "claude", scope: str = "global", link: bool = False) -> None:
    """Install the graphify-sf skill into the agentic IDE config directory.

    scope="global"  → installs under ~/.<platform>/   (active in all projects)
    scope="project" → installs under ./.<platform>/   (active in this project only)

    Supported platforms: claude, codex, opencode, aider, copilot, kiro,
                         gemini, trae, trae-cn, hermes, droid, pi,
                         antigravity, kimi, cursor
    """
    if scope not in ("global", "project"):
        print(f"error: unknown scope '{scope}'. Use: global, project", file=sys.stderr)
        sys.exit(1)

    if platform not in _ALL_PLATFORMS:
        print(
            f"error: unknown platform '{platform}'.\nSupported: {', '.join(_ALL_PLATFORMS)}",
            file=sys.stderr,
        )
        sys.exit(1)

    skill_src = Path(__file__).parent / "_bundled_skill.md"
    if not skill_src.exists():
        print("error: _bundled_skill.md not found in package — reinstall graphify-sf", file=sys.stderr)
        sys.exit(1)

    # --link: write canonical to .agents/skills/ and symlink from platform path
    if link:
        _install_with_link(platform, scope, skill_src)
        return

    # Resolve base directory
    if platform == "claude" and os.environ.get("CLAUDE_CONFIG_DIR") and scope == "global":
        base = Path(os.environ["CLAUDE_CONFIG_DIR"])
        # CLAUDE_CONFIG_DIR already IS the .claude dir, so skills/ is a direct child
        dest_dir = base / "skills" / "graphify-sf"
    else:
        base = Path(".") if scope == "project" else Path.home()
        dest_dir = base / _PLATFORM_SKILLS_DIR[platform]

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "SKILL.md"
    _atomic_write(dest, skill_src)

    # Version stamp so future installs can detect stale copies
    (dest_dir / ".graphify_sf_version").write_text(__version__, encoding="utf-8")

    scope_label = "project" if scope == "project" else "global"
    print(f"graphify-sf skill installed [{platform}/{scope_label}] → {dest}")
    _print_install_footer(scope)


def _print_install_footer(scope: str) -> None:
    print()
    if scope == "project":
        print("Skill is active for this project only.")
    else:
        print("Skill is active in all projects for this IDE.")
    print()
    print("Use it by typing:")
    print("  /graphify-sf <path-to-sfdx-project>")
    print()
    print("To update the skill after upgrading graphify-sf:")
    print("  graphify-sf install             # re-run — always overwrites with latest")
    print("  graphify-sf install --link      # if using --link: one canonical update covers all symlinked IDEs")


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------


def _cmd_uninstall(platform: str = "claude", scope: str = "global") -> None:
    """Remove the graphify-sf skill from the agentic IDE config directory."""
    if scope not in ("global", "project"):
        print(f"error: unknown scope '{scope}'. Use: global, project", file=sys.stderr)
        sys.exit(1)

    if platform not in _ALL_PLATFORMS:
        print(
            f"error: unknown platform '{platform}'.\nSupported: {', '.join(_ALL_PLATFORMS)}",
            file=sys.stderr,
        )
        sys.exit(1)

    if platform == "cursor":
        base = Path(".") if scope == "project" else Path.home()
        rules_dir = base / ".cursor" / "rules"
        targets = [
            rules_dir / "graphify-sf.mdc",
            rules_dir / ".graphify_sf_version",
        ]
    else:
        if platform == "claude" and os.environ.get("CLAUDE_CONFIG_DIR") and scope == "global":
            dest_dir = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "skills" / "graphify-sf"
        else:
            base = Path(".") if scope == "project" else Path.home()
            dest_dir = base / _PLATFORM_SKILLS_DIR[platform]
        targets = [dest_dir / "SKILL.md", dest_dir / ".graphify_sf_version"]

    removed: list[Path] = []
    for f in targets:
        if f.exists():
            f.unlink()
            removed.append(f)

    scope_label = "project" if scope == "project" else "global"
    if removed:
        print(f"graphify-sf skill removed [{platform}/{scope_label}]")
        for f in removed:
            print(f"  deleted {f}")
        # Clean up empty skill dir
        if platform != "cursor":
            try:
                if dest_dir.exists() and not any(dest_dir.iterdir()):
                    dest_dir.rmdir()
            except OSError:
                pass
    else:
        print(f"graphify-sf skill not found [{platform}/{scope_label}] — nothing to remove")


# ---------------------------------------------------------------------------
# claude install / uninstall  (always-on CLAUDE.md registration)
# ---------------------------------------------------------------------------

_CLAUDE_MD_MARKER = "<!-- graphify-sf -->"
_CLAUDE_MD_SECTION = """\
<!-- graphify-sf -->
## graphify-sf

This project's Salesforce metadata is indexed by [graphify-sf](https://github.com/graphify-sf/graphify-sf).

- Run `graphify-sf .` to build or rebuild the knowledge graph from SFDX metadata
- If `graphify-sf-out/graph.json` exists, use `/graphify-sf query "<question>"` to explore it
- Run `graphify-sf . --update` after metadata changes for an incremental refresh

<!-- /graphify-sf -->
"""


def _cmd_claude(action: str, scope: str = "global") -> None:
    """Write or remove the graphify-sf section in CLAUDE.md."""
    if action not in ("install", "uninstall"):
        print(f"error: unknown action '{action}'. Use: install, uninstall", file=sys.stderr)
        sys.exit(1)

    if scope == "project":
        claude_md = Path("CLAUDE.md")
    else:
        claude_md_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        claude_md = Path(claude_md_dir) / "CLAUDE.md"

    if action == "install":
        if claude_md.exists():
            content = claude_md.read_text(encoding="utf-8")
            if _CLAUDE_MD_MARKER in content:
                print("CLAUDE.md already has graphify-sf section — no change")
                print(f"  {claude_md}")
                return
            updated = content.rstrip() + "\n\n" + _CLAUDE_MD_SECTION
        else:
            claude_md.parent.mkdir(parents=True, exist_ok=True)
            updated = _CLAUDE_MD_SECTION
        tmp = claude_md.with_suffix(".tmp")
        tmp.write_text(updated, encoding="utf-8")
        os.replace(tmp, claude_md)
        print(f"graphify-sf registered in {claude_md}")

    elif action == "uninstall":
        if not claude_md.exists():
            print(f"CLAUDE.md not found at {claude_md} — nothing to remove")
            return
        content = claude_md.read_text(encoding="utf-8")
        if _CLAUDE_MD_MARKER not in content:
            print(f"graphify-sf section not found in {claude_md} — nothing to remove")
            return
        import re as _re

        updated = _re.sub(
            r"\n*<!-- graphify-sf -->.*?<!-- /graphify-sf -->\n?",
            "",
            content,
            flags=_re.DOTALL,
        ).rstrip()
        if updated:
            updated += "\n"
        tmp = claude_md.with_suffix(".tmp")
        tmp.write_text(updated, encoding="utf-8")
        os.replace(tmp, claude_md)
        print(f"graphify-sf section removed from {claude_md}")


# ---------------------------------------------------------------------------
# agents install / uninstall  (AGENTS.md registration — all agents)
# ---------------------------------------------------------------------------

_AGENTS_MD_MARKER = "<!-- graphify-sf -->"
_AGENTS_MD_SECTION = """\
<!-- graphify-sf -->
## graphify-sf

This Salesforce project's metadata is indexed by graphify-sf at graphify-sf-out/.

Rules:
- Before answering questions about Salesforce metadata relationships, dependencies, or impact analysis, read `graphify-sf-out/GRAPH_REPORT.md` for god nodes and community structure
- If `graphify-sf-out/wiki/index.md` exists, navigate it instead of reading raw metadata files
- Use `graphify-sf query "<question>"` to answer structural questions instead of grep/find/Read on metadata files
- After modifying metadata files (.cls, .trigger, .flow-meta.xml, *-meta.xml), run `graphify-sf . --update --no-viz` to keep the graph current (no API cost)
<!-- /graphify-sf -->
"""


def _cmd_agents(action: str) -> None:
    """Write or remove the graphify-sf section in AGENTS.md (project-scoped, all agents)."""
    if action not in ("install", "uninstall"):
        print(f"error: unknown action '{action}'. Use: install, uninstall", file=sys.stderr)
        sys.exit(1)

    agents_md = Path("AGENTS.md")

    if action == "install":
        if agents_md.exists():
            content = agents_md.read_text(encoding="utf-8")
            if _AGENTS_MD_MARKER in content:
                print("AGENTS.md already has graphify-sf section — no change")
                print(f"  {agents_md.resolve()}")
                return
            updated = content.rstrip() + "\n\n" + _AGENTS_MD_SECTION
        else:
            updated = _AGENTS_MD_SECTION
        tmp = agents_md.with_suffix(".tmp")
        tmp.write_text(updated, encoding="utf-8")
        os.replace(tmp, agents_md)
        print(f"graphify-sf registered in {agents_md.resolve()}")
        print()
        print("AGENTS.md is read automatically by: Claude Code, Codex, Cursor, Kiro,")
        print("Gemini CLI, aider, Copilot, and most other AI coding agents.")

    elif action == "uninstall":
        if not agents_md.exists():
            print("AGENTS.md not found — nothing to remove")
            return
        content = agents_md.read_text(encoding="utf-8")
        if _AGENTS_MD_MARKER not in content:
            print("graphify-sf section not found in AGENTS.md — nothing to remove")
            return
        import re as _re

        updated = _re.sub(
            r"\n*<!-- graphify-sf -->.*?<!-- /graphify-sf -->\n?",
            "",
            content,
            flags=_re.DOTALL,
        ).rstrip()
        if updated:
            updated += "\n"
        tmp = agents_md.with_suffix(".tmp")
        tmp.write_text(updated, encoding="utf-8")
        os.replace(tmp, agents_md)
        print(f"graphify-sf section removed from {agents_md.resolve()}")


# ---------------------------------------------------------------------------
# hook install / uninstall / status  (git post-commit + post-checkout hooks)
# ---------------------------------------------------------------------------

_HOOK_MARKER_START = "# graphify-sf-hook-start"
_HOOK_MARKER_END = "# graphify-sf-hook-end"
_CHECKOUT_MARKER_START = "# graphify-sf-checkout-hook-start"
_CHECKOUT_MARKER_END = "# graphify-sf-checkout-hook-end"

# Shared Python-interpreter detection snippet (handles uv, pipx, venv, system)
_PYTHON_DETECT = """\
GSF_BIN=$(command -v graphify-sf 2>/dev/null)
if [ -n "$GSF_BIN" ]; then
    case "$GSF_BIN" in
        *.exe) _SHEBANG="" ;;
        *)     _SHEBANG=$(head -1 "$GSF_BIN" | sed 's/^#![[:space:]]*//') ;;
    esac
    case "$_SHEBANG" in
        *[!a-zA-Z0-9/_.@-]*) GSF_PYTHON="" ;;
        *) GSF_PYTHON="$_SHEBANG" ;;
    esac
    if [ -n "$GSF_PYTHON" ] && ! "$GSF_PYTHON" -c "import graphify_sf" 2>/dev/null; then
        GSF_PYTHON=""
    fi
fi
if [ -z "$GSF_PYTHON" ]; then
    for _PY in python3 python; do
        if command -v "$_PY" >/dev/null 2>&1 && "$_PY" -c "import graphify_sf" 2>/dev/null; then
            GSF_PYTHON="$_PY"; break
        fi
    done
fi
[ -z "$GSF_PYTHON" ] && exit 0
"""

_HOOK_BLOCK = (
    """\
# graphify-sf-hook-start
# Auto-rebuild Salesforce metadata graph after each commit.
# Installed by: graphify-sf hook install

# Skip during rebase / merge / cherry-pick — avoids blocking --continue
GIT_DIR_PATH=$(git rev-parse --git-dir 2>/dev/null)
[ -d "${GIT_DIR_PATH}/rebase-merge" ]  && exit 0
[ -d "${GIT_DIR_PATH}/rebase-apply" ]  && exit 0
[ -f "${GIT_DIR_PATH}/MERGE_HEAD" ]    && exit 0
[ -f "${GIT_DIR_PATH}/CHERRY_PICK_HEAD" ] && exit 0

GSF_CHANGED=$(git diff --name-only HEAD~1 HEAD 2>/dev/null | \\
    grep -cE '\\.(cls|trigger|flow-meta\\.xml|.*-meta\\.xml)$' || true)
[ "${GSF_CHANGED:-0}" -eq 0 ] && exit 0

"""
    + _PYTHON_DETECT
    + """
_GSF_LOG="${HOME}/.cache/graphify-sf-rebuild.log"
mkdir -p "$(dirname "$_GSF_LOG")"
echo "[graphify-sf hook] ${GSF_CHANGED} metadata file(s) changed — rebuilding graph in background..."
nohup "$GSF_PYTHON" -m graphify_sf . --update --no-viz \\
    > "$_GSF_LOG" 2>&1 < /dev/null &
disown 2>/dev/null || true
# graphify-sf-hook-end
"""
)

_CHECKOUT_HOOK_BLOCK = (
    """\
# graphify-sf-checkout-hook-start
# Auto-rebuild Salesforce metadata graph when switching branches.
# Installed by: graphify-sf hook install

PREV_HEAD=$1
NEW_HEAD=$2
BRANCH_SWITCH=$3

# Only run on branch switches, not file checkouts
[ "$BRANCH_SWITCH" != "1" ] && exit 0

# Only run if graphify-sf-out/ exists (graph has been built before)
[ ! -d "graphify-sf-out" ] && exit 0

# Skip during rebase / merge / cherry-pick
GIT_DIR_PATH=$(git rev-parse --git-dir 2>/dev/null)
[ -d "${GIT_DIR_PATH}/rebase-merge" ]  && exit 0
[ -d "${GIT_DIR_PATH}/rebase-apply" ]  && exit 0
[ -f "${GIT_DIR_PATH}/MERGE_HEAD" ]    && exit 0
[ -f "${GIT_DIR_PATH}/CHERRY_PICK_HEAD" ] && exit 0

"""
    + _PYTHON_DETECT
    + """
_GSF_LOG="${HOME}/.cache/graphify-sf-rebuild.log"
mkdir -p "$(dirname "$_GSF_LOG")"
echo "[graphify-sf hook] branch switched — rebuilding graph in background..."
nohup "$GSF_PYTHON" -m graphify_sf . --update --no-viz \\
    > "$_GSF_LOG" 2>&1 < /dev/null &
disown 2>/dev/null || true
# graphify-sf-checkout-hook-end
"""
)


def _find_git_root() -> Path | None:
    """Walk up from cwd to find the .git directory."""
    p = Path.cwd()
    for _ in range(20):
        if (p / ".git").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return None


def _hooks_dir(git_root: Path) -> Path:
    """Return the git hooks directory, respecting core.hooksPath (Husky compatibility)."""
    import configparser as _cp

    try:
        cfg = _cp.RawConfigParser()
        cfg.read(git_root / ".git" / "config", encoding="utf-8")
        # configparser lowercases option names; git's hooksPath → hookspath
        custom = cfg.get("core", "hookspath", fallback="").strip()
        if custom:
            p = Path(custom).expanduser()
            if not p.is_absolute():
                p = git_root / p
            # Validate the resolved path stays within the repository root
            # to prevent supply-chain attacks via malicious core.hooksPath values
            try:
                p.resolve().relative_to(git_root.resolve())
            except ValueError:
                pass  # escapes repo root — fall through to default
            else:
                p.mkdir(parents=True, exist_ok=True)
                return p
    except (_cp.Error, OSError) as exc:
        print(
            f"[graphify-sf hooks] could not read core.hooksPath from {git_root / '.git' / 'config'}: {exc}",
            file=sys.stderr,
        )
    d = git_root / ".git" / "hooks"
    d.mkdir(exist_ok=True)
    return d


def _install_single_hook(hooks_dir: Path, name: str, script: str, marker: str) -> str:
    """Append *script* to hooks_dir/name, creating the file if absent."""
    hook_path = hooks_dir / name
    if hook_path.exists():
        content = hook_path.read_text(encoding="utf-8")
        if marker in content:
            return f"already installed at {hook_path}"
        updated = content.rstrip() + "\n\n" + script
    else:
        updated = "#!/bin/sh\n\n" + script
    tmp = hook_path.with_suffix(".tmp")
    tmp.write_text(updated, encoding="utf-8")
    os.replace(tmp, hook_path)
    hook_path.chmod(0o755)
    return f"installed at {hook_path}"


def _uninstall_single_hook(hooks_dir: Path, name: str, marker_start: str, marker_end: str) -> str:
    """Remove the graphify-sf section from hooks_dir/name."""
    hook_path = hooks_dir / name
    if not hook_path.exists():
        return f"no {name} hook found — nothing to remove"
    content = hook_path.read_text(encoding="utf-8")
    if marker_start not in content:
        return f"graphify-sf section not found in {name}"
    import re as _re

    updated = _re.sub(
        rf"\n*{_re.escape(marker_start)}\n.*?{_re.escape(marker_end)}\n?",
        "",
        content,
        flags=_re.DOTALL,
    ).rstrip()
    if not updated or updated in ("#!/bin/sh", "#!/bin/bash"):
        hook_path.unlink()
        return f"removed (deleted now-empty {hook_path})"
    tmp = hook_path.with_suffix(".tmp")
    tmp.write_text(updated + "\n", encoding="utf-8")
    os.replace(tmp, hook_path)
    return f"removed from {hook_path}"


def _cmd_hook(action: str) -> None:
    """Manage the graphify-sf git hooks (post-commit + post-checkout)."""
    if action not in ("install", "uninstall", "status"):
        print(f"error: unknown action '{action}'. Use: install, uninstall, status", file=sys.stderr)
        sys.exit(1)

    git_root = _find_git_root()
    if git_root is None:
        print("error: not inside a git repository", file=sys.stderr)
        sys.exit(1)

    hdir = _hooks_dir(git_root)

    if action == "status":

        def _check(name: str, marker: str) -> str:
            p = hdir / name
            if not p.exists():
                return "not installed"
            return (
                "installed"
                if marker in p.read_text(encoding="utf-8")
                else "not installed (hook file exists but graphify-sf section not found)"
            )

        print(f"post-commit:   {_check('post-commit', _HOOK_MARKER_START)}")
        print(f"post-checkout: {_check('post-checkout', _CHECKOUT_MARKER_START)}")
        return

    if action == "install":
        commit_msg = _install_single_hook(hdir, "post-commit", _HOOK_BLOCK, _HOOK_MARKER_START)
        checkout_msg = _install_single_hook(hdir, "post-checkout", _CHECKOUT_HOOK_BLOCK, _CHECKOUT_MARKER_START)
        print(f"post-commit:   {commit_msg}")
        print(f"post-checkout: {checkout_msg}")
        print()
        print("Rebuilds run in the background — git commit/checkout return immediately.")
        print("Rebuild log: ~/.cache/graphify-sf-rebuild.log")
        return

    if action == "uninstall":
        commit_msg = _uninstall_single_hook(hdir, "post-commit", _HOOK_MARKER_START, _HOOK_MARKER_END)
        checkout_msg = _uninstall_single_hook(hdir, "post-checkout", _CHECKOUT_MARKER_START, _CHECKOUT_MARKER_END)
        print(f"post-commit:   {commit_msg}")
        print(f"post-checkout: {checkout_msg}")


def _load_dotenv(path: str = ".env") -> None:
    """Load key=value pairs from a .env file into os.environ.

    Rules:
    - Only sets variables NOT already present in the environment (shell wins).
    - Skips blank lines and # comments.
    - Strips an optional leading 'export ' prefix.
    - Strips surrounding single or double quotes from values.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strip optional 'export ' prefix
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        # Strip inline comments (value part only, outside quotes)
        value = value.strip()
        if value and value[0] in ('"', "'"):
            quote = value[0]
            end = value.find(quote, 1)
            value = value[1:end] if end != -1 else value[1:]
        else:
            # Strip trailing inline comment
            value = value.split(" #")[0].strip()
        # Never override a variable that is already set in the shell
        if key not in os.environ:
            os.environ[key] = value


def main() -> None:
    _load_dotenv()
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(f"graphify-sf v{__version__} — Salesforce SFDX metadata knowledge graph")
        print()
        print("Usage:")
        print("  graphify-sf <path>               build knowledge graph from SFDX project")
        print("    --out <dir>                      output directory (default: graphify-sf-out)")
        print("    --update                         incremental update (re-extract changed files)")
        print("    --directed                       build directed graph")
        print("    --no-viz                         skip graph.html generation")
        print("    --force                          overwrite graph.json even if new graph is smaller")
        print("    --max-workers N                  parallel extraction worker count")
        print("    --backend <name>                 add AI semantic extraction layer")
        print("      backends: claude, gemini, kimi, openai, bedrock, ollama, auto")
        print("      API keys: ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, MOONSHOT_API_KEY")
        print("    --token-budget N                 tokens per LLM chunk (default: 40000)")
        print()
        print("  graphify-sf install               install /graphify-sf skill into agentic IDE")
        print("    --scope global                   install for all projects (default)")
        print("    --scope project                  install into current project only")
        print("    --platform <name>                target IDE (default: claude)")
        print(f"      platforms: {', '.join(_ALL_PLATFORMS)}")
        print("    --link                           write canonical to .agents/skills/ and symlink")
        print("                                     from the platform path (one file, many IDEs)")
        print()
        print("  graphify-sf uninstall             remove /graphify-sf skill")
        print("    --scope global|project           same as install (default: global)")
        print("    --platform <name>                target IDE (default: claude)")
        print()
        print("  graphify-sf claude install        register graphify-sf in CLAUDE.md (always-on)")
        print("  graphify-sf claude uninstall      remove graphify-sf section from CLAUDE.md")
        print("    --scope global                   write to ~/.claude/CLAUDE.md (default)")
        print("    --scope project                  write to ./CLAUDE.md")
        print()
        print("  graphify-sf agents install        write AGENTS.md enforcement rules (all agents)")
        print("  graphify-sf agents uninstall      remove graphify-sf section from AGENTS.md")
        print("    (always project-scoped — writes ./AGENTS.md)")
        print()
        print("  graphify-sf hook install          add git post-commit hook (auto-rebuild)")
        print("  graphify-sf hook uninstall        remove the hook")
        print("  graphify-sf hook status           check if hook is installed")
        print()
        print("  graphify-sf check-update <path>   dry-run diff — what would --update re-extract?")
        print("    --out <dir>                      output directory (default: graphify-sf-out)")
        print()
        print("  graphify-sf merge-graphs <g1> <g2> [<gN>...]   merge multiple graph.json files")
        print("    --out <path>                     output graph.json path")
        print("    --no-viz                         skip graph.html")
        print()
        print("  graphify-sf cluster-only <path>   re-cluster existing graph.json")
        print("    --out <dir>                      output directory (default: graphify-sf-out)")
        print("    --no-viz                         skip graph.html")
        print("    --graph <path>                   explicit graph.json path")
        print()
        print('  graphify-sf query "<question>"    BFS traversal for a question')
        print("    --dfs                            use DFS instead of BFS")
        print("    --budget N                       token budget (default 2000)")
        print("    --graph <path>                   explicit graph.json path")
        print()
        print('  graphify-sf path "<A>" "<B>"      shortest path between two nodes')
        print("    --graph <path>                   explicit graph.json path")
        print()
        print('  graphify-sf explain "<node>"      node details and neighbors')
        print("    --graph <path>                   explicit graph.json path")
        print()
        print("  graphify-sf stats                 detailed graph statistics (type distribution, density)")
        print("    --graph <path>                   explicit graph.json path")
        print()
        print("  graphify-sf export <format>       re-export from existing graph.json")
        print("    formats: html, obsidian, graphml, cypher, neo4j, json, wiki, svg, tree, callflow-html")
        print("    --graph <path>                   explicit graph.json path")
        print("    --out <dir>                      output directory")
        print("    neo4j: --push                    push directly to a running Neo4j instance")
        print("      --uri bolt://localhost:7687     Bolt URI")
        print("      --user neo4j                   username")
        print("      --password <pw>                password")
        print("    svg: requires pip install graphify-sf[svg]")
        print()
        print("  graphify-sf merge-driver install  register git merge driver for graph.json")
        print("  graphify-sf merge-driver uninstall")
        print("  graphify-sf merge-driver run %O %A %B  (called by git automatically)")
        print()
        print("  graphify-sf watch <path>          auto-rebuild on metadata file changes")
        print("    --out <dir>                      output directory (default: graphify-sf-out)")
        print("    --debounce N                     seconds to wait after last change (default: 3)")
        print("    --directed                       build directed graph")
        print("    --viz                            also regenerate graph.html on each rebuild")
        print()
        print("  graphify-sf serve                 MCP stdio server for agent graph access")
        print("    --graph <path>                   explicit graph.json path")
        print()
        return

    cmd = args[0]

    # ── install ────────────────────────────────────────────────────
    if cmd == "install":
        platform = "claude"
        scope = "global"
        link = False
        i = 1
        while i < len(args):
            a = args[i]
            if a == "--platform" and i + 1 < len(args):
                platform = args[i + 1]
                i += 2
            elif a.startswith("--platform="):
                platform = a.split("=", 1)[1]
                i += 1
            elif a == "--scope" and i + 1 < len(args):
                scope = args[i + 1]
                i += 2
            elif a.startswith("--scope="):
                scope = a.split("=", 1)[1]
                i += 1
            elif a == "--link":
                link = True
                i += 1
            else:
                i += 1
        _cmd_install(platform, scope, link)
        return

    # ── uninstall ──────────────────────────────────────────────────
    if cmd == "uninstall":
        platform = "claude"
        scope = "global"
        i = 1
        while i < len(args):
            a = args[i]
            if a == "--platform" and i + 1 < len(args):
                platform = args[i + 1]
                i += 2
            elif a.startswith("--platform="):
                platform = a.split("=", 1)[1]
                i += 1
            elif a == "--scope" and i + 1 < len(args):
                scope = args[i + 1]
                i += 2
            elif a.startswith("--scope="):
                scope = a.split("=", 1)[1]
                i += 1
            else:
                i += 1
        _cmd_uninstall(platform, scope)
        return

    # ── claude ─────────────────────────────────────────────────────
    if cmd == "claude":
        if len(args) < 2:
            print("Usage: graphify-sf claude <install|uninstall> [--scope global|project]", file=sys.stderr)
            sys.exit(1)
        action = args[1]
        scope = "global"
        i = 2
        while i < len(args):
            a = args[i]
            if a == "--scope" and i + 1 < len(args):
                scope = args[i + 1]
                i += 2
            elif a.startswith("--scope="):
                scope = a.split("=", 1)[1]
                i += 1
            else:
                i += 1
        _cmd_claude(action, scope)
        return

    # ── agents ─────────────────────────────────────────────────────
    if cmd == "agents":
        if len(args) < 2:
            print("Usage: graphify-sf agents <install|uninstall>", file=sys.stderr)
            sys.exit(1)
        _cmd_agents(args[1])
        return

    # ── hook ───────────────────────────────────────────────────────
    if cmd == "hook":
        if len(args) < 2:
            print("Usage: graphify-sf hook <install|uninstall|status>", file=sys.stderr)
            sys.exit(1)
        _cmd_hook(args[1])
        return

    # ── check-update ───────────────────────────────────────────────
    if cmd == "check-update":
        target_str = "."
        out_dir_str = _DEFAULT_OUT
        i = 1
        while i < len(args):
            a = args[i]
            if a == "--out" and i + 1 < len(args):
                out_dir_str = args[i + 1]
                i += 2
            elif a.startswith("--out="):
                out_dir_str = a.split("=", 1)[1]
                i += 1
            elif not a.startswith("-"):
                target_str = a
                i += 1
            else:
                i += 1
        _cmd_check_update(Path(target_str).resolve(), Path(out_dir_str))
        return

    # ── merge-graphs ───────────────────────────────────────────────
    if cmd == "merge-graphs":
        graph_path_args: list[Path] = []
        out_path_str = str(Path(_DEFAULT_OUT) / "graph.json")
        no_viz = False
        i = 1
        while i < len(args):
            a = args[i]
            if a == "--out" and i + 1 < len(args):
                out_path_str = args[i + 1]
                i += 2
            elif a.startswith("--out="):
                out_path_str = a.split("=", 1)[1]
                i += 1
            elif a == "--no-viz":
                no_viz = True
                i += 1
            elif not a.startswith("-"):
                graph_path_args.append(Path(a))
                i += 1
            else:
                i += 1
        if len(graph_path_args) < 2:
            print(
                "Usage: graphify-sf merge-graphs <graph1.json> <graph2.json> [...] [--out merged.json] [--no-viz]",
                file=sys.stderr,
            )
            sys.exit(1)
        _cmd_merge_graphs(graph_path_args, Path(out_path_str), no_viz=no_viz)
        return

    # ── stats ──────────────────────────────────────────────────────
    if cmd == "stats":
        graph_path = Path(_default_graph_path())
        i = 1
        while i < len(args):
            a = args[i]
            if a == "--graph" and i + 1 < len(args):
                graph_path = Path(args[i + 1])
                i += 2
            elif a.startswith("--graph="):
                graph_path = Path(a.split("=", 1)[1])
                i += 1
            else:
                i += 1
        if not graph_path.exists():
            print(f"error: graph not found: {graph_path}", file=sys.stderr)
            sys.exit(1)
        _cmd_stats(graph_path)
        return

    # ── merge-driver ────────────────────────────────────────────────
    if cmd == "merge-driver":
        if len(args) < 2:
            print("Usage: graphify-sf merge-driver <install|uninstall|run> [%O %A %B]", file=sys.stderr)
            sys.exit(1)
        sub = args[1]
        if sub == "run":
            if len(args) < 5:
                print("Usage: graphify-sf merge-driver run <base> <ours> <theirs>", file=sys.stderr)
                sys.exit(1)
            _cmd_merge_driver(Path(args[2]), Path(args[3]), Path(args[4]))
        elif sub in ("install", "uninstall"):
            _cmd_merge_driver_setup(sub)
        else:
            print(f"error: unknown merge-driver action '{sub}'. Use: install, uninstall, run", file=sys.stderr)
            sys.exit(1)
        return

    # ── watch ──────────────────────────────────────────────────────
    if cmd == "watch":
        target_str = "."
        out_dir_str = _DEFAULT_OUT
        debounce = 3.0
        directed = False
        no_viz = True

        i = 1
        while i < len(args):
            a = args[i]
            if a == "--out" and i + 1 < len(args):
                out_dir_str = args[i + 1]
                i += 2
            elif a.startswith("--out="):
                out_dir_str = a.split("=", 1)[1]
                i += 1
            elif a == "--debounce" and i + 1 < len(args):
                debounce = float(args[i + 1])
                i += 2
            elif a.startswith("--debounce="):
                debounce = float(a.split("=", 1)[1])
                i += 1
            elif a == "--directed":
                directed = True
                i += 1
            elif a == "--viz":
                no_viz = False
                i += 1
            elif not a.startswith("-"):
                target_str = a
                i += 1
            else:
                i += 1

        from graphify_sf.watch import watch as _watch

        _watch(
            Path(target_str).resolve(),
            Path(out_dir_str),
            debounce=debounce,
            directed=directed,
            no_viz=no_viz,
        )
        return

    # ── serve ───────────────────────────────────────────────────────
    if cmd == "serve":
        graph_path = Path(_default_graph_path())
        i = 1
        while i < len(args):
            a = args[i]
            if a == "--graph" and i + 1 < len(args):
                graph_path = Path(args[i + 1])
                i += 2
            elif a.startswith("--graph="):
                graph_path = Path(a.split("=", 1)[1])
                i += 1
            else:
                i += 1
        if not graph_path.exists():
            print(f"error: graph not found: {graph_path}", file=sys.stderr)
            sys.exit(1)
        from graphify_sf.serve import serve as _serve

        _serve(str(graph_path))
        return

    # ── Main pipeline ──────────────────────────────────────────────
    if not cmd.startswith("-") and cmd not in (
        "cluster-only",
        "query",
        "path",
        "explain",
        "export",
        "install",
        "uninstall",
        "claude",
        "agents",
        "hook",
        "--version",
        "check-update",
        "merge-graphs",
        "watch",
        "serve",
        "stats",
        "merge-driver",
    ):
        # Positional arg: SFDX project path
        target = Path(cmd).resolve()
        if not target.exists():
            print(f"error: path not found: {target}", file=sys.stderr)
            sys.exit(1)

        out_dir_str = _DEFAULT_OUT
        update = False
        directed = False
        no_viz = False
        force = os.environ.get("GRAPHIFY_SF_FORCE", "").lower() in ("1", "true", "yes")
        max_workers = None
        backend: str | None = None
        token_budget = 40_000

        i = 1
        while i < len(args):
            a = args[i]
            if a == "--out" and i + 1 < len(args):
                out_dir_str = args[i + 1]
                i += 2
            elif a.startswith("--out="):
                out_dir_str = a.split("=", 1)[1]
                i += 1
            elif a == "--update":
                update = True
                i += 1
            elif a == "--directed":
                directed = True
                i += 1
            elif a == "--no-viz":
                no_viz = True
                i += 1
            elif a == "--force":
                force = True
                i += 1
            elif a == "--max-workers" and i + 1 < len(args):
                max_workers = int(args[i + 1])
                i += 2
            elif a.startswith("--max-workers="):
                max_workers = int(a.split("=", 1)[1])
                i += 1
            elif a == "--backend" and i + 1 < len(args):
                backend = args[i + 1]
                i += 2
            elif a.startswith("--backend="):
                backend = a.split("=", 1)[1]
                i += 1
            elif a == "--token-budget" and i + 1 < len(args):
                token_budget = int(args[i + 1])
                i += 2
            elif a.startswith("--token-budget="):
                token_budget = int(a.split("=", 1)[1])
                i += 1
            else:
                i += 1

        out_dir = Path(out_dir_str)
        _run_pipeline(
            target,
            out_dir,
            update=update,
            directed=directed,
            no_viz=no_viz,
            max_workers=max_workers,
            force=force,
            backend=backend,
            token_budget=token_budget,
        )
        return

    # ── Version ────────────────────────────────────────────────────
    if cmd == "--version":
        print(f"graphify-sf v{__version__}")
        return

    # ── cluster-only ───────────────────────────────────────────────
    if cmd == "cluster-only":
        target_str = "."
        out_dir_str = _DEFAULT_OUT
        no_viz = False
        graph_override: Path | None = None

        i = 1
        while i < len(args):
            a = args[i]
            if a == "--no-viz":
                no_viz = True
                i += 1
            elif a == "--out" and i + 1 < len(args):
                out_dir_str = args[i + 1]
                i += 2
            elif a.startswith("--out="):
                out_dir_str = a.split("=", 1)[1]
                i += 1
            elif a == "--graph" and i + 1 < len(args):
                graph_override = Path(args[i + 1])
                i += 2
            elif a.startswith("--graph="):
                graph_override = Path(a.split("=", 1)[1])
                i += 1
            elif not a.startswith("-"):
                target_str = a
                i += 1
            else:
                i += 1

        out_dir = Path(out_dir_str)
        _cmd_cluster_only(Path(target_str), out_dir, no_viz=no_viz, graph_path=graph_override)
        return

    # ── query ──────────────────────────────────────────────────────
    if cmd == "query":
        if len(args) < 2:
            print('Usage: graphify-sf query "<question>" [--dfs] [--budget N] [--graph path]', file=sys.stderr)
            sys.exit(1)
        question = args[1]
        use_dfs = "--dfs" in args
        budget = 2000
        graph_path = Path(_default_graph_path())

        i = 2
        while i < len(args):
            a = args[i]
            if a == "--budget" and i + 1 < len(args):
                budget = int(args[i + 1])
                i += 2
            elif a.startswith("--budget="):
                budget = int(a.split("=", 1)[1])
                i += 1
            elif a == "--graph" and i + 1 < len(args):
                graph_path = Path(args[i + 1])
                i += 2
            elif a.startswith("--graph="):
                graph_path = Path(a.split("=", 1)[1])
                i += 1
            else:
                i += 1

        if not graph_path.exists():
            print(f"error: graph not found: {graph_path}", file=sys.stderr)
            sys.exit(1)
        _cmd_query(question, graph_path, use_dfs=use_dfs, budget=budget)
        return

    # ── path ───────────────────────────────────────────────────────
    if cmd == "path":
        if len(args) < 3:
            print('Usage: graphify-sf path "<source>" "<target>" [--graph path]', file=sys.stderr)
            sys.exit(1)
        source_label = args[1]
        target_label = args[2]
        graph_path = Path(_default_graph_path())

        i = 3
        while i < len(args):
            a = args[i]
            if a == "--graph" and i + 1 < len(args):
                graph_path = Path(args[i + 1])
                i += 2
            elif a.startswith("--graph="):
                graph_path = Path(a.split("=", 1)[1])
                i += 1
            else:
                i += 1

        if not graph_path.exists():
            print(f"error: graph not found: {graph_path}", file=sys.stderr)
            sys.exit(1)
        _cmd_path(source_label, target_label, graph_path)
        return

    # ── explain ────────────────────────────────────────────────────
    if cmd == "explain":
        if len(args) < 2:
            print('Usage: graphify-sf explain "<node>" [--relation <rel>] [--graph path]', file=sys.stderr)
            sys.exit(1)
        label = args[1]
        graph_path = Path(_default_graph_path())
        explain_relation: str | None = None

        i = 2
        while i < len(args):
            a = args[i]
            if a == "--graph" and i + 1 < len(args):
                graph_path = Path(args[i + 1])
                i += 2
            elif a.startswith("--graph="):
                graph_path = Path(a.split("=", 1)[1])
                i += 1
            elif a == "--relation" and i + 1 < len(args):
                explain_relation = args[i + 1]
                i += 2
            elif a.startswith("--relation="):
                explain_relation = a.split("=", 1)[1]
                i += 1
            else:
                i += 1

        if not graph_path.exists():
            print(f"error: graph not found: {graph_path}", file=sys.stderr)
            sys.exit(1)
        _cmd_explain(label, graph_path, relation=explain_relation)
        return

    # ── export ─────────────────────────────────────────────────────
    if cmd == "export":
        if len(args) < 2:
            print(
                "Usage: graphify-sf export <html|obsidian|graphml|cypher|json> [--graph path] [--out dir]",
                file=sys.stderr,
            )
            sys.exit(1)
        fmt = args[1]
        graph_path = Path(_default_graph_path())
        out_dir = Path(_DEFAULT_OUT)

        i = 2
        while i < len(args):
            a = args[i]
            if a == "--graph" and i + 1 < len(args):
                graph_path = Path(args[i + 1])
                i += 2
            elif a.startswith("--graph="):
                graph_path = Path(a.split("=", 1)[1])
                i += 1
            elif a == "--out" and i + 1 < len(args):
                out_dir = Path(args[i + 1])
                i += 2
            elif a.startswith("--out="):
                out_dir = Path(a.split("=", 1)[1])
                i += 1
            else:
                i += 1

        if not graph_path.exists():
            print(f"error: graph not found: {graph_path}", file=sys.stderr)
            sys.exit(1)

        # ── neo4j --push (special: doesn't need full graph load up front) ──
        if fmt in ("neo4j",):
            neo4j_uri = "bolt://localhost:7687"
            neo4j_user = "neo4j"
            neo4j_password = "neo4j"
            neo4j_db: str | None = None
            push = "--push" in args[2:]
            j = 2
            while j < len(args):
                a2 = args[j]
                if a2 == "--uri" and j + 1 < len(args):
                    neo4j_uri = args[j + 1]
                    j += 2
                elif a2.startswith("--uri="):
                    neo4j_uri = a2.split("=", 1)[1]
                    j += 1
                elif a2 == "--user" and j + 1 < len(args):
                    neo4j_user = args[j + 1]
                    j += 2
                elif a2.startswith("--user="):
                    neo4j_user = a2.split("=", 1)[1]
                    j += 1
                elif a2 == "--password" and j + 1 < len(args):
                    neo4j_password = args[j + 1]
                    j += 2
                elif a2.startswith("--password="):
                    neo4j_password = a2.split("=", 1)[1]
                    j += 1
                elif a2 == "--database" and j + 1 < len(args):
                    neo4j_db = args[j + 1]
                    j += 2
                elif a2.startswith("--database="):
                    neo4j_db = a2.split("=", 1)[1]
                    j += 1
                else:
                    j += 1
            G_n, _ = _load_graph_from_json(graph_path)
            cypher_out = str(out_dir / "cypher.txt")
            out_dir.mkdir(parents=True, exist_ok=True)
            if push:
                from graphify_sf.export import push_to_neo4j

                stats = push_to_neo4j(
                    G_n,
                    cypher_out,
                    uri=neo4j_uri,
                    user=neo4j_user,
                    password=neo4j_password,
                    database=neo4j_db,
                )
                print(f"neo4j push done — {stats['nodes_merged']} nodes, {stats['edges_merged']} edges merged")
                print(f"cypher.txt audit written to {cypher_out}")
            else:
                from graphify_sf.export import to_cypher

                to_cypher(G_n, cypher_out)
                print(f"cypher.txt written to {cypher_out}")
                print("Tip: add --push --uri bolt://host:7687 --user neo4j --password <pw> to push directly")
            return

        G, raw = _load_graph_from_json(graph_path)
        labels_path = graph_path.parent / ".graphify_sf_labels.json"
        labels: dict[int, str] = {}
        if labels_path.exists():
            try:
                labels = {int(k): v for k, v in json.loads(labels_path.read_text(encoding="utf-8")).items()}
            except Exception:
                pass
        communities: dict[int, list[str]] = {}

        # Re-derive communities from node community attribute
        for nid, data in G.nodes(data=True):
            cid = data.get("community")
            if cid is not None:
                communities.setdefault(int(cid), []).append(nid)

        if not communities:
            from graphify_sf.cluster import cluster

            communities = cluster(G)

        if fmt in ("html", "viz"):
            from graphify_sf.export import to_html

            out_path = out_dir / "graph.html"
            to_html(G, communities, str(out_path), community_labels=labels or None)
            print(f"graph.html written to {out_path}")

        elif fmt == "obsidian":
            from graphify_sf.export import to_obsidian

            obs_dir = out_dir / "obsidian"
            n = to_obsidian(G, communities, str(obs_dir), community_labels=labels or None)
            print(f"Obsidian vault: {n} notes in {obs_dir}/")

        elif fmt == "graphml":
            from graphify_sf.export import to_graphml

            out_path = out_dir / "graph.graphml"
            to_graphml(G, communities, str(out_path))
            print(f"graph.graphml written to {out_path}")

        elif fmt == "cypher":
            from graphify_sf.export import to_cypher

            out_path = out_dir / "cypher.txt"
            to_cypher(G, str(out_path))
            print(f"cypher.txt written to {out_path}")

        elif fmt == "json":
            from graphify_sf.export import to_json

            out_path = out_dir / "graph.json"
            to_json(G, communities, str(out_path), force=True)
            print(f"graph.json written to {out_path}")

        elif fmt == "wiki":
            from graphify_sf.export import to_wiki

            n = to_wiki(G, communities, str(out_dir), community_labels=labels or None)
            print(f"wiki written to {out_dir / 'wiki'}/ ({n} files)")

        elif fmt == "svg":
            from graphify_sf.export import to_svg

            out_path = out_dir / "graph.svg"
            to_svg(G, communities, str(out_path), community_labels=labels or None)
            print(f"graph.svg written to {out_path}")

        elif fmt == "tree":
            from graphify_sf.export import to_tree_html

            out_path = out_dir / "graph-tree.html"
            to_tree_html(G, communities, str(out_path), community_labels=labels or None)
            print(f"graph-tree.html written to {out_path}")

        elif fmt in ("callflow-html", "callflow"):
            from graphify_sf.export import to_callflow_html

            out_path = out_dir / "callflow.html"
            n = to_callflow_html(G, str(out_path))
            print(f"callflow.html written to {out_path} ({n} nodes)")

        else:
            print(
                f"error: unknown export format '{fmt}'. Use: html, obsidian, graphml, cypher, neo4j, json, wiki, svg, tree, callflow-html",
                file=sys.stderr,
            )
            sys.exit(1)
        return

    print(f"error: unknown command '{cmd}'", file=sys.stderr)
    print("Run 'graphify-sf --help' for usage.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()

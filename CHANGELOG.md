# Changelog

All notable changes to graphify-sf are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.3.1] — 2026-06-04

### Fixed
- **Scaffolding directories no longer pollute the graph.** Detection now skips agentic-tooling
  and repo-meta directories (`.agents`, `.claude`, `.cursor`, `.github`, `.omc`, etc.) that hold
  skill templates and sample `.cls` files but no real org metadata. On a large real org this
  removed ~2,100 phantom nodes (18% of the graph). `.graphifysfignore` overrides still apply.
- **Reference-file nodes now carry a real `sf_type`.** Document, PDF, and image file nodes are
  typed `Document`; headings and in-document sub-nodes are typed `DocumentSection` (previously
  `None`, which made them invisible to type-filtered queries).
- **FlexiPage record pages now link to their object.** `extract_flexipage` reads `<sobjectType>`
  and emits a `record_page_for` (EXTRACTED) edge to the target object, and no longer emits noise
  `contains` edges for standard (non-`c:`) components. Previously all FlexiPage nodes were isolated.
- **Corrected the repo URLs in package metadata.** The GitHub username was misspelled in
  `pyproject.toml` project URLs, the CHANGELOG compare links, `SECURITY.md`, the issue-template
  config, and the `AGENTS.md` block emitted by `graphify-sf agents install`. They now all point at
  `github.com/raykuonz/graphify-sf`.

### Docs
- Added a **"Why this exists"** positioning section and a **"Maturity & limitations"** section to
  the README, documenting the EXTRACTED-vs-INFERRED provenance model, the `calls`-edge
  false-positive rate, and the static-only scope honestly.

---

## [0.3.0] — 2026-05-21

### Added

#### Edge extraction improvements
- Record-Triggered Flows now emit `triggers` edges to the target object with `EXTRACTED` confidence
- Flows emit `invokes` edges for subflow references and `calls` edges for Apex action calls
- Custom Fields emit `references` (Lookup) and `master_detail` (MasterDetail) edges to target objects
- ValidationRule formula fields emit `INFERRED references` edges to the fields they reference
- Agentforce: `GenAiPlannerBundle` local actions parsed as inline `GenAiFunction` nodes; `conversationDefinitionPlanners` XML path supported for `BotVersion` planner references; `PromptTemplate` `flexTemplateActionCalls` create reference edges
- `build.py` exports `_resolve_apex_calls`, `_derive_object_edges`, and `_ensure_stub_nodes` for use in the extract pipeline

### Fixed
- Standard-object edges (Lead, Account, etc.) were incorrectly downgraded from `EXTRACTED` to `INFERRED` confidence because `_ensure_stub_nodes` ran after `_resolve_cross_references`; ordering is now correct
- Apex `calls` edges had ~96% false-positive rate from local variable method calls; new `_looks_like_apex_class()` heuristic reduces noise to ~36%
- Pinned `idna>=3.15` to resolve CVE-2026-45409 (transitive via `requests`)

### Changed
- 65 new tests → 268 total (up from 203); new `test_extract_pipeline.py` with regression test for the stub-node ordering fix

---

## [0.2.0] — 2026-05-14

### Added

#### Reference file support
- Detect and index non-Salesforce reference files co-existing in SFDX repos
- **Documents** (`.md`, `.mdx`, `.txt`, `.rst`, `.html`) — headings extracted as sub-nodes; Salesforce component name mentions create `references` edges
- **PDFs** (`.pdf`) — text extracted via `pypdf`; SF name mentions detected
- **Spreadsheets** (`.xlsx`) — structural nodes: workbook → sheet → named table → column headers; content converted to markdown sidecar
- **Word documents** (`.docx`) — converted to markdown sidecar via `python-docx`, then processed as document
- **Images** (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.svg`) — metadata node, no text extraction
- Office file sidecar conversion to `graphify-sf-out/converted/` (stable SHA-256 filename)
- New optional extra `graphify-sf[docs]` for `pypdf`, `python-docx`, `openpyxl`
- Graceful degradation: missing optional libraries skip files with a warning, never crash
- `detect()` returns new `doc_files` key; `detect_incremental()` tracks doc file changes

---

## [0.1.0] — 2026-05-12

### Added

#### Core pipeline
- Full offline SFDX metadata extraction — no org connection, no Salesforce CLI required
- Two-pass extraction: per-file structural pass + cross-file reference resolution
- `EXTRACTED` / `INFERRED` / `AMBIGUOUS` confidence tags on every edge
- Community detection via Louvain (default) and optional Leiden algorithm
- Plain-language `GRAPH_REPORT.md` with god nodes, surprising connections, and suggested questions
- Incremental updates (`--update`) with SHA-256 file hash manifest
- Dry-run diff with `check-update` (exits 1 if changes exist — CI-friendly)
- Parallel extraction with `--max-workers`

#### Supported metadata types
- `ApexClass`, `ApexTrigger`, `ApexMethod` — Apex source with SOQL, DML, callout, extends/implements extraction
- `Flow` — Flow/Process Builder with subflow, object, and field references
- `CustomObject`, `CustomField`, `ValidationRule`, `RecordType`, `Layout`
- `LWCBundle`, `AuraBundle` — component controller and child-component references
- `Profile`, `PermissionSet` — object/field/class permission edges
- `CustomLabel`, `NamedCredential`, `ExternalService`, `CustomMetadata`
- `Bot`, `BotVersion`, `GenAiPlugin`, `GenAiFunction`, `GenAiPlannerBundle`, `AiAuthoringBundle`, `PromptTemplate` — full Agentforce metadata graph

#### Export formats
- Interactive force-directed HTML (`graph.html`) with search, community filter, node inspector
- GraphRAG-ready JSON (`graph.json`) with node/edge provenance and community assignments
- D3 collapsible tree (`export tree`)
- Mermaid call-flow diagram (`export callflow-html`)
- Static SVG graph image (`export svg` — requires `[svg]` extra)
- Obsidian vault (`export obsidian`)
- GraphML for Gephi / yEd (`export graphml`)
- Neo4j Cypher statements + direct push (`export cypher` / `export neo4j`)
- Agent-crawlable Markdown wiki (`export wiki`)
- Graph merge (`merge-graphs`) with deduplication and re-clustering

#### Exploration CLI
- `query` — BFS/DFS traversal with token budget
- `explain` — full node details with `--relation` filter (no cap when filtered)
- `path` — shortest path between two metadata nodes
- `stats` — type distribution, edge relations, degree stats, density

#### LLM semantic extraction
- Six backends: Claude, Gemini, Kimi K2, OpenAI, AWS Bedrock, Ollama
- Auto-detect backend from available API keys (`--backend auto`)
- Adaptive retry with exponential back-off on rate-limit errors (429)
- Configurable token budget per chunk (`--token-budget`)

#### Integrations
- Agentic skill for Claude Code, Cursor, Codex, Kiro, Gemini CLI, aider, Copilot, and 10+ more IDEs
- `--link` flag for symlinked multi-IDE skill install
- AGENTS.md enforcement block (`agents install`) for always-on graph-first agent behavior
- CLAUDE.md block (`claude install`) for Claude Code
- Git post-commit + post-checkout hooks for automatic background rebuilds
- Git merge driver for conflict-free `graph.json` merges
- MCP stdio server with 8 tools and 6 resources
- File watcher with debounce and incremental rebuild
- `.graphifysfignore` for exclude patterns (gitignore syntax)

[Unreleased]: https://github.com/raykuonz/graphify-sf/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/raykuonz/graphify-sf/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/raykuonz/graphify-sf/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/raykuonz/graphify-sf/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/raykuonz/graphify-sf/releases/tag/v0.1.0

# Changelog

All notable changes to graphify-sf are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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

[Unreleased]: https://github.com/raykuo/graphify-sf/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/raykuo/graphify-sf/releases/tag/v0.1.0

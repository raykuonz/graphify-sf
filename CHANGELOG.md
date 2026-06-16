# Changelog

All notable changes to graphify-sf are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.3.9] — 2026-06-16

### Changed
- **The prebuilt CLI binary now ships *inside* npm — `npm install` no longer makes a network request on the
  happy path.** Following the well-established esbuild/@swc/turbo pattern, the binary for each platform is
  published as a scoped subpackage (`@graphify-sf/cli-<plat>-<arch>`) and pulled in via
  `optionalDependencies` with `os`/`cpu` constraints. npm installs only the subpackage matching the host,
  so the binary arrives with the dependency tree itself — even on networks that block GitHub Releases.
  Verified end-to-end in a real consumer `node_modules` layout: postinstall is silent, exits 0, and makes
  zero network calls when the platform subpackage is present.
- `lib/download.js` `ensureBinary()` resolution order is now: (1) `GRAPHIFY_BIN`, (2) the installed platform
  subpackage (new, no network), (3) a previously-downloaded binary in `bin/`, (4) GitHub Releases download.
- `install.js` postinstall short-circuits (no network) when a binary already resolves from the env override
  or a subpackage; the GitHub download remains a non-fatal last-resort fallback (the 0.3.8 `exit(0)`
  behaviour is preserved).

### Added
- `@graphify-sf/cli-{linux-x64,linux-arm64,darwin-x64,darwin-arm64,win32-x64}` scoped subpackages, each
  shipping the renamed prebuilt binary with the correct `os`/`cpu` so npm selects exactly one.
- `npm/scripts/build-subpackages.js` — deterministic, zero-dependency scaffolder that turns the release
  assets into the five subpackage directories (used by the release workflow; runnable locally).
- `release-binaries.yml` now downloads the release binaries, scaffolds the subpackages, publishes them
  (before the main package, which pins their exact versions), then stamps the version into the main
  package + its `optionalDependencies` and publishes it.
- npm regression tests for subpackage resolution, `ensureBinary()` precedence, and no-network postinstall.

### Release prerequisite (one-time)
- The `@graphify-sf` npm scope/org must exist and the `NPM_TOKEN` secret must be authorized to publish to
  it (`--access public`). Create the org on npmjs.com and grant the publish token access before cutting the
  0.3.9 release, otherwise the `Publish platform subpackages` step will 402/403 on first publish.

---

## [0.3.8] — 2026-06-16

### Fixed
- **A blocked or failed binary download during `npm install` no longer aborts the consumer's install.**
  The npm wrapper's `postinstall` hook fetches a prebuilt CLI binary from GitHub Releases. On locked-down
  corporate networks (proxy/firewall blocking GitHub, or a 404), the download would reject and the hook
  called `process.exit(1)`, which fails the entire `npm install` for every package depending on
  graphify-sf. The hook now always exits `0`: a failed pre-fetch is non-fatal, the binary is fetched
  lazily on first run instead, and a clear remediation message is printed (use `pipx install graphify-sf`,
  or set `GRAPHIFY_BIN` to an existing binary). Verified with a regression test that simulates a failed
  download and asserts the postinstall exit code is `0`.
- **Corrected the in-repo npm package version (`0.3.1` → `0.3.8`).** The download URL is derived from the
  package version; the stale `0.3.1` produced a guaranteed `404` against the `v0.3.1` release asset on any
  local/dev install of the wrapper. (Published installs were unaffected because the release workflow
  rewrites the version from the tag, but the drift was a latent footgun.)

### Added
- **`GRAPHIFY_BIN` environment variable** — point graphify-sf at an existing binary to bypass the download
  entirely (highest-priority resolution in `ensureBinary()`). The documented escape hatch for air-gapped or
  proxy-restricted environments.
- npm-side regression test suite (`npm/test/`, Node's built-in `node:test`, zero dependencies) covering the
  non-fatal postinstall behaviour and `GRAPHIFY_BIN` resolution precedence.

---

## [0.3.7] — 2026-06-14

### Fixed
- **macOS: parallel extraction no longer crashes the worker pool and silently truncates the graph.**
  The PyInstaller-frozen binary had no `multiprocessing.freeze_support()` call, so on macOS (and Windows),
  where the multiprocessing start method is **spawn**, each pool worker re-executed the binary with Python's
  internal bootstrap args (`-B --multiprocessing-fork <fd>`). The CLI argument parser intercepted those args
  first, rejected them (`error: unknown command '-B'`), and every worker died — leaving only the lightweight
  sequentially-extracted bundles (LWC/Aura/Document) and producing a severely truncated graph (e.g. 572
  nodes instead of ~9700, with **zero** CustomObject/CustomField/Flow). Linux was unaffected because it uses
  the `fork` start method (no re-exec). `freeze_support()` now runs first in the entry point, so spawn workers
  bootstrap correctly. Verified by building the frozen binary and running it under a forced `spawn` start
  method: full graph restored (9383 nodes, 658 objects, 3239 fields, 166 flows).
- **A failed worker pool no longer produces a silently-incomplete graph that exits 0.** Previously a
  `BrokenProcessPool` was caught per-future and swallowed, so the run continued with only partial results and
  still exited successfully. Any pool-level failure now aborts parallel mode and re-runs the **full**
  extraction sequentially, emitting a loud `WARNING: parallel worker pool failed — falling back to sequential`
  so the produced graph is always complete (just slower) and the degradation is visible.

### Added
- `GRAPHIFY_SF_MP_START` environment variable to override the multiprocessing start method
  (e.g. `GRAPHIFY_SF_MP_START=spawn`/`fork`) — primarily an escape hatch and a way to exercise the spawn
  re-exec path on Linux. Unset uses the platform default.

---

## [0.3.6] — 2026-06-14

### Added
- **`.gitignore` / `.forceignore` are now honored by default** to cut graph noise. Files matched by the
  project's `.gitignore` or `.forceignore` (deprecated metadata, queues, `__tests__`, jsconfig/eslint/ts
  scaffolding, build output, etc.) are skipped during the scan instead of becoming phantom nodes. Patterns
  are parsed with `pathspec` gitignore semantics — negation (`!keep`), anchored (`/foo`), directory
  (`foo/`), and `**` globs all behave the same as git and the `sf` CLI (the previous `.graphifysfignore`
  used `fnmatch`, which could not express these). Ignore files are discovered by walking **upward** from
  the scanned directory, so `graphify-sf force-app` still picks up the `.gitignore`/`.forceignore` at the
  project root. The existing `.graphifysfignore` is still applied, and the hardcoded `_SKIP_DIRS` floor
  (`.git`, `node_modules`, `.sfdx`, …) is unchanged.
- **`--include-ignored` flag** to opt out: scans every file regardless of `.gitignore`/`.forceignore` when
  you suspect a real metadata file was excluded.
- **Honest skip summary** printed after the scan, e.g.
  `skipped 57 files (.forceignore: 57) — use --include-ignored to include them`, so dropped files are
  never silent. (`detect()` now also returns `skipped_count`, `skipped_by_source`, and `respect_ignore`.)

### Fixed
- The post-scan log previously printed the raw `skipped` list object instead of a count
  (`… N skipped` now shows the actual number).
- **Distinct components with the same normalised label are no longer merged.** `deduplicate_by_label`
  collapsed any two nodes whose labels normalised the same — regardless of type — so an `ApexClass` and a
  similarly-named `LWCComponent`, or a `CustomObject` and its `CustomTab`/`Settings`/`PermissionSet`, were
  conflated into one node and their edges silently rewritten onto the wrong survivor. On a real 9k-node org
  this wrongly merged **83 node pairs**. Dedup is now gated on `sf_type`: only same-type nodes merge (the
  intended chunked-duplicate case still works), recovering those nodes and the object→field ownership edges
  that had been dropped (e.g. fields under a managed-package object whose label collided with a permission
  set).
- **Self-referencing lookup fields keep their `contains` ownership edge.** When a lookup/master-detail
  field points back at its own parent object, the object→field `contains` edge and the field→object
  `references` edge occupy the same undirected node-pair and one overwrote the other, leaving the field
  unattached to its object. The build now keeps the higher-priority relation on collision (`contains`
  outranks `references`), so `componentsOnObject`/`bfsImpact` see every field. Together with the dedup fix,
  object→field attachment on the test org went from 99.4% to **100%** (18 orphaned fields → 0). Preserving
  *both* relations on such pairs is the planned 0.4.0 MultiGraph work.

---

## [0.3.5] — 2026-06-13

### Fixed
- **Apex DML edges now work on real-world code.** The Apex DML → object `dml` edge feature added in
  0.3.4 silently produced **zero** edges on real Apex, because DML operands are almost always
  lowercase local variables (`insert c;`) and the edge-building guard only accepted operands whose
  name was already capitalized. Real classes with `insert`/`update`/`delete` statements therefore
  emitted no `dml` edges at all. The extractor now resolves the DML operand variable to its declared
  SObject type by scanning local variable declarations and method parameters (simple `Type var`,
  generic `List<Type>` / `Set<Type>` / `Map<K,Type>`, and parameters), and builds the `dml` edge to
  the resolved object (e.g. `Case c = new Case(); insert c;` → `class → object_case`,
  `operation="create"`, `confidence="INFERRED"`). Operands that cannot be resolved to a type are
  skipped rather than emitting a misleading edge to a variable name (honest INFERRED semantics
  preserved). Apex primitives (`String`, `Integer`, `Id`, etc.) are never treated as DML targets.
  A PascalCase operand that is itself a type name still works via a fallback path, so existing
  behavior is preserved.

  Note: in the built graph, multiple DML operations against the *same* object from one component are
  currently still merged into a single edge (the graph layer keeps one edge per source→target pair).
  Exposing every write operation as its own independently-locatable edge is planned as a follow-up
  graph-model upgrade.

---

## [0.3.4] — 2026-06-13

### Added
- **Apex DML edges now preserve the write operation.** Apex → object `dml` edges now carry
  an `operation` field derived from the DML verb (`insert`→`create`, `update`→`update`,
  `delete`→`delete`, plus the SF-native `upsert` / `merge` / `undelete` preserved as-is rather
  than forced into CRUD). The edge relation stays `dml` (unchanged) and confidence stays
  `INFERRED` — the DML target is a variable name that can't always be statically resolved to an
  object type, and that honesty label is unchanged. Deduplication is now by `(object, operation)`
  so a class that both inserts and updates the same object yields two distinct edges instead of
  one collapsed `dml` edge. This mirrors the flow record-op change in 0.3.3, so both major write
  paths (Flow and Apex) now expose read/write operation semantics to downstream consumers.
  SOQL `queries` edges are unchanged (they already carry read semantics).

---

## [0.3.3] — 2026-06-13

### Added
- **Flow record operations now preserve read/write semantics.** Flow → object edges from
  record operations (`recordLookups` / `recordCreates` / `recordUpdates` / `recordDeletes`)
  now carry an `operation` field (`read` / `create` / `update` / `delete`). The edge relation
  stays `references` (unchanged — that generic relation is reused by many extractors), so all
  existing consumers that filter by relation are unaffected; consumers that need to tell reads
  from writes can read the new field. Deduplication is now by `(object, operation)` instead of
  by object alone, so a flow that both reads and updates the same object yields two distinct
  edges instead of one collapsed reference. This lets downstream answer precise questions like
  "which flows *write* (update/create/delete) object X" rather than only "which flows touch X".

---

## [0.3.2] — 2026-06-12

### Added
- **npm distribution — install without Python.** `graphify-sf` is now installable from npm
  (`npm install graphify-sf` / `pnpm add graphify-sf`). A postinstall step downloads a
  self-contained, per-platform binary (built with PyInstaller) from the matching GitHub Release,
  so Node consumers can use the tool with no Python on the machine. Supported platforms:
  linux x64/arm64, macOS x64/arm64, Windows x64.
- **Programmatic JS API.** `require("graphify-sf").runGraphify(sfdxPath, { outDir })` spawns the
  binary (`<path> --out <outDir> --no-viz`) and resolves `{ code, graphJsonPath }`, so a Node
  daemon can drive the core static-extraction path directly. Also exports `ensureBinary()` and
  `binaryPath()`. The binary is downloaded lazily on first use when a package manager skips
  postinstall scripts (e.g. pnpm's default `ignore-scripts`), and any download failure throws
  a loud, explicit error rather than failing silently.
- **Release automation for binaries + npm.** The same `release: published` event now also builds
  the per-platform binaries (5-leg matrix), uploads them to the Release, and publishes the npm
  wrapper. The version is sourced from the release tag (single source of truth) — both the bundled
  binary and the npm package read it.

### Fixed
- **Frozen-binary version reporting.** The PyInstaller binary now reports its real version instead
  of `dev`, via a version-resolution fallback chain (`importlib.metadata` → bundled `_version.py`
  → `GRAPHIFY_SF_VERSION` env → `dev`). Source/PyPI installs are unaffected.
- **CI dependency scan no longer fails on transient `pip` advisories.** The security-scan job now
  upgrades `pip` in its environment before running `pip-audit`, so a freshly-published advisory
  against the bundled `pip` (which is not a project dependency) no longer reds every PR.

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

[Unreleased]: https://github.com/raykuonz/graphify-sf/compare/v0.3.5...HEAD
[0.3.5]: https://github.com/raykuonz/graphify-sf/compare/v0.3.4...v0.3.5
[0.3.4]: https://github.com/raykuonz/graphify-sf/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/raykuonz/graphify-sf/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/raykuonz/graphify-sf/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/raykuonz/graphify-sf/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/raykuonz/graphify-sf/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/raykuonz/graphify-sf/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/raykuonz/graphify-sf/releases/tag/v0.1.0

# Changelog

All notable changes to graphify-sf are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.4.2] — 2026-10-20

A dependency-health release. It clears every known vulnerability in the locked dependency tree,
removes three dependencies that were never used, replaces the stale `graspologic` Leiden backend,
and fixes two optional-extra paths that were broken for fresh installs: `[claude]` on anthropic 1.x
and `[leiden]` since 0.4.0. CI on `main` had been red since v0.4.1 on the pip-audit job; it is green
again, and Dependabot now maintains `uv.lock`.

### Security
- **The locked dependency tree is free of known vulnerabilities again** (was 80 advisories across 12
  packages, per `pip-audit` over `uv export --all-extras`). 32 of them came from the unused `mcp`
  extra's tree (mcp, starlette, python-multipart, pyjwt, cryptography, pydantic-settings), which is gone.
  27 came from `pypdf`. The rest (pillow, urllib3, anyio, msgpack, pip) are lock-refreshed to patched
  versions.
- **`pypdf` floor raised to `>=6.19`** in `[docs]`/`[all]`. graphify-sf parses PDFs found in the scanned
  project, and 6.11 carried 27 advisories. The npm binaries were never affected: they exclude pypdf,
  python-docx and openpyxl from the bundle.

### Fixed
- **`[claude]` extraction works on anthropic 1.x.** anthropic 1.0 (2026-08-20) removed `temperature`
  from `messages.create()`, so every Claude call raised `TypeError` for anyone who installed
  `graphify-sf[claude]` after that date (the floor is unbounded). Temperature now travels in
  `extra_body`, the SDK's documented replacement, which also works on 0.x. The request on the wire is
  unchanged.
- **`[leiden]` clustering no longer crashes.** graspologic's `leiden()` rejects multigraphs with
  `ValueError`. Since 0.4.0, `cluster()` hands it the `MultiGraph` produced by `to_undirected()`, and only
  `ImportError` was caught. See the backend change under Changed.

### Changed
- **Leiden now runs on `graspologic-native` instead of `graspologic`.** It is the same Rust engine
  graspologic wrapped, with abi3 wheels for every Python ≥3.9, so `[leiden]` now works on Python
  3.13/3.14 too. The extra drops about 25 heavy transitive packages (gensim, numba, umap-learn,
  scikit-learn, statsmodels, POT, `future`, …) and its `numpy<2` pin; it still needs numpy and scipy.
  Parallel edges are now summed into one weighted edge per pair before the engine sees them, because the
  engine silently keeps only the first weight it sees for a pair. Results are seeded (`seed=42`, like
  Louvain) and relabelled in sorted-id order, so **Leiden communities are now reproducible across runs
  and processes.** graspologic's wrapper ran unseeded. Existing graspologic installs keep Leiden, since
  graspologic depends on graspologic-native; verified against graspologic-native 1.2.5, the declared
  floor, and 1.3.1. Louvain results still vary slightly between processes; that behaviour predates this
  release and is unchanged.
- **Three dead or retiring default LLM models replaced.** Each replacement was checked against the
  provider's own docs. To pin a different model, set the backend's model variable:
  `GRAPHIFY_SF_GEMINI_MODEL`, `GRAPHIFY_SF_BEDROCK_MODEL`, or the new `GRAPHIFY_SF_KIMI_MODEL`. The CLI
  has no `--model` flag.
  - **gemini:** `gemini-2.0-flash` (shut down 2026-06-01) → `gemini-3.6-flash`, Google's named replacement.
    Temperature is no longer sent, since Google advises keeping Gemini 3.x at its default and lower values
    can loop. Price $0.10/$0.40 → $0.75/$3.75 per 1M tokens. Google doubles it to $1.50/$7.50 on
    2027-01-01.
  - **kimi:** `kimi-k2-0711-preview` (discontinued 2026-05-25) → `kimi-k3`, Moonshot's replacement.
    K3 always reasons and does not take the K2.x-only `thinking` parameter, so the request hook is now
    model-aware. K2.x models (e.g. `GRAPHIFY_SF_KIMI_MODEL=kimi-k2.6`, the cheaper option at
    $0.95/$4.00) still get `thinking: disabled`. K3+ gets `reasoning_effort="low"`, because its default
    (`max`) is slow and costly for extraction. Other ids get neither setting. Price $0.74/$4.66 →
    $3.00/$15.00.
  - **bedrock:** `anthropic.claude-3-5-sonnet-20241022-v2:0` (Legacy, EOL 2026-11-13) →
    `us.anthropic.claude-sonnet-4-6`, the US geo inference profile. On-demand Sonnet 4.6 has no in-region
    endpoint in us-east-1, the default region. Callers outside the US should set
    `GRAPHIFY_SF_BEDROCK_MODEL` (e.g. `eu.` or `global.anthropic.claude-sonnet-4-6`). The CLI now warns
    once when a `us.` profile is used from a non-US `AWS_REGION`. Cost-estimate price $3.30/$16.50, which
    includes the 10% regional-endpoint premium.
  - **Upcoming:** `openai`'s default `gpt-4.1-mini` is deprecated, and OpenAI shuts it down on 2027-01-14.
    It is unchanged in this release.
- **The `[mcp]` extra is now empty.** `graphify-sf serve` has always implemented MCP's JSON-RPC stdio
  transport itself and never imported the `mcp` package. The extra is kept as an alias so existing
  `pip install graphify-sf[mcp]` commands keep working, and `[all]` no longer installs it.
- **SDK floors raised to the first releases with the APIs graphify-sf calls:** `openai>=1.58`
  (`reasoning_effort`, now always sent for Kimi K3; `max_completion_tokens` needs 1.45) and
  `boto3>=1.34.116` (bedrock-runtime `Converse`). Older versions satisfied the old floors but failed at
  call time. The real-SDK contract tests pass at exactly these floors and at anthropic 0.30.0.
- **The README backend table now lists each default model and its per-1M-token price** from `BACKENDS`.
  It replaces the old per-1k-files cost guesses, which weren't derived consistently.
- **openai 3.x / anthropic 1.x** (now the locked versions) use `httpx2`, which reads the operating
  system's certificate store instead of `certifi`. Behind a TLS-inspecting proxy you may need
  `SSL_CERT_FILE`.

### Removed
- **`datasketch` and `rapidfuzz` core dependencies.** Neither was imported anywhere. A plain
  `pip install graphify-sf` no longer pulls in numpy or scipy; the full pipeline, including `--update`,
  was verified in an environment without them. `[svg]` relied on scipy arriving through datasketch for
  its layout of 201–500-node graphs, so it now declares `scipy` itself.

### CI and maintenance
- Dependabot now uses the `uv` ecosystem, so it updates `uv.lock`. The old `pip` ecosystem ignored the
  lockfile, which is why the vulnerable pins went unfixed. Minor and patch updates are grouped.
- New `test-all-extras` CI job (Python 3.10 and 3.14) installs every extra, so the new real-SDK contract
  tests (`tests/test_llm_sdk_contract.py`), the real-Leiden test and the new SVG export tests run instead
  of being skipped. The job sets `GRAPHIFY_SF_FAIL_ON_SKIP=1`, so any skip there, including a
  module-level one, fails the build. The contract tests drive the actual anthropic, openai and boto3
  clients against a local HTTP server. A breaking SDK release therefore fails CI as soon as Dependabot
  proposes it for `uv.lock`; the existing fakes couldn't catch one.
- Python 3.14 added to the test matrix and classifiers.
- Actions: checkout v7, setup-python v7, setup-node v7 (Node 20, which is EOL, replaced by Node 24), and
  setup-uv pinned to `v10.3.0` (setup-uv no longer publishes moving major tags).
- Python 3.10 reached end of life this month. It is still supported in 0.4.x; dropping it is planned
  for 0.5.0.

### Verification
- 521 tests, up from 503 at 0.4.1. In the minimal (`dev`) environment on Python 3.10–3.14, 514 pass and
  the 7 optional-dependency tests skip by design. All 521 pass with every extra installed on 3.10 and
  3.14, with no skips allowed.
  `ruff check`/`ruff format --check` are clean, and `pip-audit` over the all-extras lock reports nothing.
- Each fix was reproduced before it was made: the anthropic 1.x `TypeError` against the real SDK, the
  `[svg]` scipy `ModuleNotFoundError` in an svg-only environment, and the Leiden fallback on pre-fix code.
  Each regression test fails on the pre-fix code. The end-to-end CLI build, `--update` and the
  `serve` JSON-RPC handshake were run on the fixture projects with and without the extras.

---

## [0.4.1] — 2026-07-14

A correctness- and honesty-focused release: closes several MultiDiGraph parallel-edge-drop gaps left
over from the 0.4.0 migration (including two introduced by this release's own new code, caught and
fixed during a multi-round adversarial review before shipping), hardens the Apex extractor against
comment/string false positives, normalizes LLM backend config drift, and fixes ambiguous doc-mention
resolution. Every fix below shipped with a regression test proven to fail on the pre-fix code.

### Fixed — MultiDiGraph parallel-edge drops (serve.py, merge-graphs, and the new bfs_impact tool)
- **MCP tools and the CLI's `path` command now read every parallel edge, not just the first.**
  `serve.py`'s `get_node`, `get_neighbors`, and `shortest_path`, plus `graphify-sf path`, previously
  called the single-edge `edge_data()` helper on the default MultiDiGraph, so a node pair with two
  relations (e.g. `queries` + `dml` to the same object) silently reported only one of them — the same
  class of bug the 0.4.0 MultiDiGraph migration fixed elsewhere, unfixed in the MCP/CLI layer until now.
  All four now use `edge_datas()` and surface every relation. `get_node`/`get_neighbors` may now return
  one entry per relation instead of one per neighbor (each entry still shaped
  `{id, label, sf_type, relation, confidence}`); `shortest_path`'s per-hop `relation`/`confidence`
  becomes a list when a hop has more than one parallel edge (a scalar for the common single-edge case).
  **If you consume these MCP tools, re-check any caller that assumed exactly one entry per neighbor.**
- **`merge-graphs`/`merge-driver` no longer drop parallel edges, on either axis.** The union previously
  went through a plain `nx.Graph()`, collapsing same-direction parallel edges (e.g. `queries` + `dml` on
  one pair) before the multigraph-aware rebuild ever ran; then, after being rewritten to preserve those,
  it dropped edges that shared a relation but differed only in `operation` (e.g. two `dml` edges, one
  `create` one `update`, on the same pair). The union now hashes the full edge identity (minus the
  per-graph `key`/`source_file` fields that legitimately vary across inputs), so every distinct parallel
  edge survives a 2- or 3-way merge while genuinely-identical duplicates (the base/ours/theirs case)
  still coalesce to one.
- **The new `bfs_impact` MCP tool (see Added) now reports every parallel relation to a neighbor.** Its
  first implementation stored one `{relation, confidence}` pair per neighbor id in its BFS accumulator,
  re-introducing — in code this same release added — the exact parallel-edge collapse fixed above for
  the other MCP tools. `relation`/`confidence` are now lists when a neighbor has more than one parallel
  edge (a scalar for the common single-edge case), mirroring `shortest_path`.

### Fixed — Apex extraction honesty (comments, strings, method scoping, generics)
- **Apex class extraction no longer treats commented-out or string-literal code as real.** `insert`/
  `update`/etc. inside `//`, `/* */`, or a string literal previously produced real edges to a nonexistent
  target; comments and string contents are now scrubbed before `extract_apex_class`'s DML, method-call,
  SOQL, `EventBus.publish`, and Custom Metadata/Setting-access extraction.
- **Known gap (disclosed, not fixed this release):** Apex HTTP-callout detection
  (`extract_apex_class`'s endpoint scan) and `extract_apex_trigger`'s call-scanning still read raw,
  unscrubbed source, so commented-out or string-embedded code in those two paths can still produce a
  phantom edge. Pre-existing, not introduced by the fix above; tracked for a future release.
- **Apex `calls` edges no longer leak across method boundaries.** A method's call-edge scan previously
  ran to end-of-file instead of to its own closing brace, so every method accumulated calls that
  actually belonged to methods below it in the same class.
- **Apex `implements` clauses with a generic argument list no longer split incorrectly.**
  `implements Comparator<Account, String>` previously split on the comma inside the generic brackets and
  emitted a bogus edge treating `String` as an interface.
- **Apex DML operand→type resolution is now scoped per method, not per class.** Two methods reusing the
  same local variable name with different declared types (e.g. `Account a` in one method, `Contact a` in
  another) previously collided via `dict.setdefault`, silently misattributing the second method's DML.

### Fixed — LLM backends, doc mentions, MCP robustness, --verbose accounting
- **LLM backend config drift across the 6 supported backends resolved.** OpenAI previously had no
  `max_tokens` entry and fell back to a hardcoded `8192` (half of every sibling backend's `16384`);
  Gemini silently ignored the documented `GRAPHIFY_SF_MAX_OUTPUT_TOKENS` env override; `temperature` was
  never passed to Claude's SDK call and was hardcoded (ignoring config) for Bedrock. All 6 backends now
  resolve `max_tokens`/`temperature` through the same codepath. Kimi's thinking-disable and Ollama's
  context-sizing quirks moved from inline branches to a data-driven per-backend hook with no behavior
  change (proven by regression test). **The `openai` backend's effective `max_tokens` changes from 8192
  to 16384** — this changes output size/cost for existing `--backend openai` users; not a silent change.
- **Doc/PDF cross-reference mentions no longer resolve to an arbitrary match when ambiguous.** When a
  mention's label matched multiple graph nodes, the resolver previously picked the first one arbitrarily
  (e.g. a `DocumentSection` heading could win over the real `CustomObject` it was named after). It now
  prefers non-document candidates, and falls back to emitting all remaining candidates at a reduced
  `INFERRED` confidence score when the ambiguity is real. A small denylist now filters common English
  words that happen to be PascalCase-shaped (suffixed names like `Account__c` always bypass it), and a
  mention inside a fenced or inline code span now gets a higher confidence score than one in bare prose.
- **MCP tool int arguments (`bfs_impact`'s `max_depth`/`limit` and others) no longer raise on
  non-numeric input.** A caller-supplied non-numeric value previously raised an uncaught `ValueError`;
  a new `_get_int` helper now degrades to the tool's default and clamps out-of-range values.
- **`--verbose` node accounting no longer mislabels retained nodes as stubs on `--update`.** Incremental
  mode merges with the entire prior `graph.json`, so a node carried over unchanged from a file no longer
  on disk was counted as a build-injected stub; the stub term now reports `n/a (incremental merge)` on
  the incremental path, matching the existing `n_pruned_edges` guard.

### Added
- **`bfs_impact` MCP tool** — a depth-bounded, direction-aware (`forward`/`reverse`/`both`) blast-radius
  traversal, EXTRACTED-edges-only by default (`include_inferred` opt-in), with `relation_filter`,
  `limit`/`truncated` reporting, and a `by_type` breakdown. Closes the gap between graphify-sf's own
  1-hop-only `get_neighbors`/`get_node` tools and the multi-hop impact analysis downstream consumers had
  to reimplement on top of raw `graph.json`.
- **`--verbose`/`-v` node-drop accounting** on build/update — prints
  `N extracted → M deduped-by-label (K merged) → +S stub → F final nodes (P dangling edge(s) pruned)` so
  the extract→dedup→build node-count pipeline is no longer opaque.

### Verification
- 503 tests (up from 451 at 0.4.0), `ruff check`/`ruff format --check` clean, zero new runtime
  dependencies. Every fix above was independently reproduced against a pre-fix checkout before and after
  the change, not just asserted by a passing test suite.

---

## [0.4.0]

### ⚠️ BREAKING CONTRACT CHANGE — graph.json is now a MultiDiGraph

**graph.json now declares `"multigraph": true`.** Every entry in `links` carries
a `"key"` integer. A single node-pair **may appear multiple times** in `links`,
each entry with a distinct `key` and its own `relation`. Downstream consumers that
assume "one edge per source→target pair" will silently read only the **first**
relation and drop the rest — a correctness regression, not a crash. **Every
consumer must switch from `find(…)` to `filter(…)` when reading `links`.**

This fulfils the planned 0.4.0 MultiGraph work noted in the 0.3.6 CHANGELOG.

#### Why the change is needed
`build_from_json` previously built an undirected simple `nx.Graph()` where a
node-pair holds ONE edge. Same-direction parallel relations — e.g. an Apex class
that BOTH `queries` AND `dml`-writes the same object — collapsed silently: the
second `add_edge` overwrote the first. On a real org this erases ~149
`{queries,dml}` pairs. The loss was invisible in graph.json (0 multi-relation
pairs ever survived).

#### What changes
- `build_from_json` / `build` / `build_merge_sf` now default to
  `multigraph=True`, constructing a `nx.MultiDiGraph` that stores **all**
  parallel directed edges without collision.
- The old `_RELATION_PRIORITY` collision path (kept for `multigraph=False`) is
  bypassed entirely for the default MultiDiGraph path.
- `node_link_data(G, edges="links")` serialises the MultiDiGraph natively; each
  link gains a `"key"` field. `node_link_graph` reconstructs the MultiDiGraph
  automatically when it sees `"multigraph": true`.
- Consumer query sites (`--explain --filter-relation`, Obsidian export, analysis)
  now iterate `edge_datas(G, u, v)` so all parallel relations are found, not just
  the first.

### Added (Epic A–F coverage breadth)
- Integration & external dependencies (A1–A8): HTTP callouts, Flow callouts,
  RemoteSiteSetting, ExternalDataSource/ExternalObject, PlatformEvent/CDC,
  Custom Metadata/Settings config reads, AuthProvider/CSP/CORS, Workflow outbound
  messages.
- Security & sharing (B1–B5): Org-Wide Defaults, SharingRules/SharingSets,
  PermSetGroup membership, Profile/PermSet userPermissions + tab/app visibility,
  RestrictionRule + Duplicate/MatchingRule.
- Automation completeness (C1–C4): WorkflowFieldUpdate/Task, ProcessBuilder
  distinction, Flow trigger completeness, ValidationRule standard field refs.
- UI layer → backend linkage (D1–D3): LWC schema/label/resource imports,
  Aura/VF controller linkage, FlexiPage Aura embeds + StaticResource/QuickAction/
  CustomTab-App edges.
- Data model completeness (E1–E3): FieldSet/GlobalValueSet, CompactLayout/
  ListView/RecordType inner refs, polymorphic lookups.
- Reporting & packaging (F1–F2): Report/Dashboard/ReportType extraction,
  Package/InstalledPackage nodes + namespace tagging.

### Fixed (cleanups)
- `EventBus` platform type no longer becomes a phantom `ApexClass` node when
  `EventBus.publish(...)` appears in Apex. `eventbus` is now in the keyword
  exclusion set so it is never treated as a user-defined class reference.
- `CustomField --uses--> GlobalValueSet` edge is now emitted exactly once per
  field even when the underlying XML has multiple `<valueSet>` elements.
- `ApexTrigger --subscribes--> PlatformEvent` edge is now emitted (in addition
  to the existing `triggers` edge) whenever a trigger fires on a `__e` object.

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
- Python package version bumped to 0.3.9 to keep PyPI, npm and the release tag in lockstep (no functional
  Python changes in this release; the distribution improvements are all in the npm wrapper).
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

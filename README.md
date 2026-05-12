# graphify-sf

**Turn any Salesforce SFDX project into a queryable knowledge graph — fully offline, no org connection required.**

graphify-sf parses your local SFDX source directory, extracts every metadata entity (Apex classes, triggers, Flows, Custom Objects, Fields, LWC/Aura components, Profiles, Permission Sets, Layouts, Validation Rules, and more), maps the real relationships between them, and produces an interactive knowledge graph with community detection.

Built for developers and architects who need to understand large Salesforce orgs without clicking through Setup.

---

## Features

- **Fully offline** — pure XML/source parsing, no Salesforce CLI, no org connection, no API calls
- **Honest provenance** — every edge is tagged `EXTRACTED` (from explicit XML) or `INFERRED` (from source patterns)
- **Community detection** — Louvain/Leiden clustering surfaces cross-metadata couplings you wouldn't think to ask about
- **Interactive HTML visualization** — force-directed graph with search, community filtering, and node inspector
- **Multiple export formats** — HTML, SVG, Mermaid call-flow, D3 tree, Obsidian vault, GraphML, Cypher/Neo4j, JSON, Markdown wiki
- **Incremental updates** — re-extract only changed files with `--update`; dry-run diff with `check-update`
- **Agentic IDE integration** — install a `/graphify-sf` skill into Claude Code, Cursor, Codex, Kiro, Gemini, and 10+ more IDEs
- **MCP server** — expose graph query tools to Claude Desktop and other MCP clients over stdio
- **File watcher** — auto-rebuild on metadata changes with `watch`
- **Git-native** — post-commit hook for automatic rebuilds; merge driver for conflict-free `graph.json` merges

---

## Quick Start

```bash
# Install
pip install graphify-sf

# Or with uv (recommended)
uv tool install graphify-sf

# Build the knowledge graph from your SFDX project
graphify-sf /path/to/sfdx-project

# Open the interactive visualization
open graphify-sf-out/graph.html
```

On the first run you'll see:

```
[graphify-sf] scanning /path/to/sfdx-project
[graphify-sf] 847 metadata files found, 0 skipped
[graphify-sf] extracting metadata...
[graphify-sf] extracted 1243 nodes, 3891 edges
[graphify-sf] clustering...
[graphify-sf] 7 communities found
[graphify-sf] wrote graphify-sf-out/GRAPH_REPORT.md
[graphify-sf] wrote graphify-sf-out/graph.json
[graphify-sf] wrote graphify-sf-out/graph.html

[graphify-sf] done
  1243 nodes · 3891 edges · 7 communities
```

---

## Output Files

| File | Description |
|------|-------------|
| `graphify-sf-out/graph.html` | Interactive force-directed graph — search, filter by community, inspect nodes |
| `graphify-sf-out/graph.json` | GraphRAG-ready JSON with node/edge provenance, community assignments |
| `graphify-sf-out/GRAPH_REPORT.md` | Plain-language report: god nodes, surprising connections, suggested questions |
| `graphify-sf-out/manifest.json` | File hash manifest for incremental updates |
| `graphify-sf-out/.graphify_sf_labels.json` | Community label sidecar |

---

## Command Reference

### Main Pipeline

```bash
# Build graph from SFDX project (full scan)
graphify-sf <path>

# Custom output directory
graphify-sf <path> --out my-graph-out

# Build directed graph (edges have source→target direction)
graphify-sf <path> --directed

# Skip HTML visualization (faster, report + JSON only)
graphify-sf <path> --no-viz

# Overwrite graph.json even if new graph has fewer nodes
graphify-sf <path> --force

# Parallel extraction with N workers
graphify-sf <path> --max-workers 8

# Add AI semantic layer (finds business-rule duplication, dead metadata, etc.)
graphify-sf <path> --backend claude
graphify-sf <path> --backend gemini
graphify-sf <path> --backend auto     # auto-detect from available API keys

# Control LLM chunk size (tokens per API call, default: 40000)
graphify-sf <path> --backend gemini --token-budget 20000
```

### Incremental Updates

```bash
# Re-extract only changed/new files, merge into existing graph
graphify-sf <path> --update

# Dry-run: show what --update would change without doing it
# Exits 1 if changes exist (useful for CI)
graphify-sf check-update <path>

# Re-run community detection on an existing graph (no re-extraction)
graphify-sf cluster-only <path>
graphify-sf cluster-only --no-viz --graph path/to/graph.json
```

### Exploration

```bash
# BFS traversal — broad context around a question
graphify-sf query "What fires when an Account is updated?"

# DFS — trace a specific dependency chain
graphify-sf query "AccountTrigger dependencies" --dfs

# Cap response at N tokens (default: 2000)
graphify-sf query "..." --budget 4000

# Shortest path between two metadata nodes
graphify-sf path "AccountService" "Account__c"

# Full node details: type, file, community, degree, all connections
graphify-sf explain "AccountTrigger"

# Filter connections by relation type (shows all matches, no cap)
graphify-sf explain "Account" --relation triggers
graphify-sf explain "Account" --relation queries
graphify-sf explain "Account" --relation invokes

# Detailed graph statistics: type distribution, edge relations, density
graphify-sf stats
graphify-sf stats --graph path/to/graph.json
```

All exploration commands accept `--graph <path>` to target a specific `graph.json`.

### Export Formats

```bash
# Regenerate the interactive HTML visualization
graphify-sf export html

# D3 v7 collapsible tree — organized by community, hover tooltips
graphify-sf export tree

# Mermaid call-flow diagram — Apex→Object→Trigger dependency chains
graphify-sf export callflow-html

# Static SVG graph image (dark theme, community colors, degree-sized nodes)
# Requires: pip install graphify-sf[svg]
graphify-sf export svg

# Obsidian vault — one note per node + community overview notes
graphify-sf export obsidian

# GraphML — open in Gephi, yEd, Cytoscape
graphify-sf export graphml

# Neo4j Cypher statements (writes cypher.txt)
graphify-sf export cypher

# Push directly to a running Neo4j instance
# Requires: pip install graphify-sf[neo4j]
graphify-sf export neo4j --push \
  --uri bolt://localhost:7687 \
  --user neo4j \
  --password mypassword

# Agent-crawlable Markdown wiki (one .md per community)
graphify-sf export wiki

# Re-export clean graph.json
graphify-sf export json

# All formats accept --graph and --out:
graphify-sf export html --graph path/to/graph.json --out output-dir/
```

### Merging Graphs

```bash
# Merge two or more graph.json files into one
# Deduplicates nodes by label, re-clusters, regenerates report + HTML
graphify-sf merge-graphs a/graph.json b/graph.json --out merged/graph.json
graphify-sf merge-graphs g1.json g2.json g3.json --out combined.json --no-viz
```

---

## LLM Semantic Extraction

The `--backend` flag adds an AI-powered extraction layer on top of the static XML/source parser. The LLM finds relationships that static parsing **cannot** see:

| What it finds | Example |
|---------------|---------|
| **Business rule duplication** | Same validation in Apex class AND Flow (both enforce a required field) |
| **Semantic equivalence** | Two Profiles granting nearly identical Object/Field access |
| **Implicit data couplings** | Apex writes to Object A; Flow reads from Object A (no XML edge between them) |
| **Dead metadata** | Profile grants access to Apex class that is never called by any Trigger/Flow |
| **Trigger-bypass risk** | Bulk utility using `Database.insert` outside trigger context |

### Supported Backends

| Backend | Flag | API Key env var | Estimated cost (1k files) |
|---------|------|-----------------|--------------------------|
| Claude | `--backend claude` | `ANTHROPIC_API_KEY` | ~$0.50 |
| Gemini | `--backend gemini` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | ~$0.05 |
| Kimi K2 | `--backend kimi` | `MOONSHOT_API_KEY` | ~$0.30 |
| OpenAI | `--backend openai` | `OPENAI_API_KEY` | ~$0.20 |
| AWS Bedrock | `--backend bedrock` | `AWS_PROFILE` / `AWS_REGION` | ~$0.50 |
| Ollama (local) | `--backend ollama` | `OLLAMA_BASE_URL` | free |
| Auto-detect | `--backend auto` | _(first found)_ | varies |

### Install the SDK

```bash
# Claude
pip install graphify-sf[claude]

# Gemini, Kimi, OpenAI, Ollama (all use the openai SDK)
pip install graphify-sf[gemini]   # or [kimi], [openai], [ollama]

# AWS Bedrock
pip install graphify-sf[bedrock]

# Claude + all OpenAI-compat backends
pip install graphify-sf[llm]
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Gemini API key |
| `MOONSHOT_API_KEY` | Kimi K2 API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `AWS_PROFILE` / `AWS_REGION` | AWS credentials for Bedrock |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434/v1`) |
| `OLLAMA_MODEL` | Ollama model name (default: `qwen2.5-coder:7b`) |
| `GRAPHIFY_SF_GEMINI_MODEL` | Override Gemini model |
| `GRAPHIFY_SF_OPENAI_MODEL` | Override OpenAI model |
| `GRAPHIFY_SF_BEDROCK_MODEL` | Override Bedrock model |
| `GRAPHIFY_SF_MAX_OUTPUT_TOKENS` | Override max output tokens per LLM call |
| `GRAPHIFY_SF_API_TIMEOUT` | Override API timeout in seconds (default: 600) |

---

## Agentic IDE Integration

Install a `/graphify-sf` skill that lets any supported AI coding assistant run the full pipeline and explore the graph through natural language.

### Zero-dependency install via npx (no Python required)

Uses the [open agent skills ecosystem](https://github.com/vercel-labs/skills) — works across 55+ AI coding agents.

```bash
# Install globally (all projects)
npx skills add raykuonz/graphify-sf

# Install for this project only
npx skills add raykuonz/graphify-sf --project
```

The skill instructs your agent to run `graphify-sf` via `uvx` or `pipx run` on demand — no permanent Python install needed.

### Install via Python CLI

```bash
graphify-sf install
# Installs to ~/.claude/skills/graphify-sf/SKILL.md
```

### Install for a specific platform

```bash
graphify-sf install --platform cursor    # Cursor → .cursor/skills/graphify-sf/SKILL.md
graphify-sf install --platform codex     # OpenAI Codex
graphify-sf install --platform kiro      # AWS Kiro
graphify-sf install --platform gemini    # Google Gemini CLI
graphify-sf install --platform aider     # aider
graphify-sf install --platform copilot   # GitHub Copilot
graphify-sf install --platform opencode  # OpenCode
```

Supported platforms: `antigravity`, `aider`, `claude`, `codex`, `copilot`, `cursor`, `droid`, `gemini`, `hermes`, `kimi`, `kiro`, `opencode`, `pi`, `trae`, `trae-cn`

### Project-scoped install (this project only)

```bash
graphify-sf install --scope project
```

### Install with symlink — one canonical file, many IDEs (`--link`)

Use `--link` to write a single canonical skill file to `.agents/skills/graphify-sf/SKILL.md` and create a symlink from the platform-specific path to it. This means **upgrading graphify-sf and re-running `install --link` once updates every symlinked IDE at the same time** — no per-platform reinstalls needed.

```bash
# Write canonical to .agents/skills/graphify-sf/SKILL.md,
# symlink from ~/.claude/skills/graphify-sf/SKILL.md
graphify-sf install --link

# Same for another IDE
graphify-sf install --link --platform gemini
graphify-sf install --link --platform kiro --scope project
```

**Symlink strategy:**
- Project scope (`--scope project`): relative symlink — stays valid if the project directory is moved
- Global scope (default): absolute symlink — stays valid regardless of working directory

**Platforms that natively use `.agents/`** (`codex`, `antigravity`): no symlink is created — `.agents/skills/graphify-sf/SKILL.md` is already their install target, so they share the canonical file directly.

**Cursor note:** Cursor discovers skills from both `.cursor/skills/` and `.agents/skills/`. When `--link` is used, the canonical file lands in `.agents/skills/graphify-sf/SKILL.md`, and Cursor picks it up from there automatically — the symlink to `.cursor/skills/` is an optional convenience if you want an explicit entry there too.

### Uninstall

```bash
graphify-sf uninstall
graphify-sf uninstall --platform cursor --scope project
```

### Update / reinstall after upgrading graphify-sf

The `install` command is idempotent — re-running it always overwrites the existing skill file with the latest version bundled in the package:

```bash
# 1. Upgrade the package
pip install --upgrade graphify-sf
# or: uv tool upgrade graphify-sf

# 2. Refresh the installed skill
graphify-sf install
```

For a specific platform or scope, pass the same flags used during the original install:

```bash
graphify-sf install --platform cursor --scope project
```

If you used `--link` when installing, a single re-run updates the canonical file and **all symlinked IDEs pick it up automatically** — no per-platform reinstalls needed:

```bash
graphify-sf install --link          # re-writes .agents/skills/graphify-sf/SKILL.md; all symlinks follow
```

### Always-on: register in AGENTS.md (all agents)

Write mandatory enforcement rules to `AGENTS.md` so **every** AI coding agent (Claude Code, Codex, Cursor, Kiro, Gemini CLI, aider, Copilot, etc.) automatically uses the graph instead of grep:

```bash
# Write ./AGENTS.md enforcement block (always project-scoped)
graphify-sf agents install

# Remove
graphify-sf agents uninstall
```

The written block instructs agents to:
- Read `graphify-sf-out/GRAPH_REPORT.md` before answering metadata questions
- Navigate the wiki instead of reading raw metadata files
- Use `graphify-sf query` instead of grep/find on metadata files
- Run `graphify-sf . --update --no-viz` after modifying metadata files

### Always-on: register in CLAUDE.md (Claude Code only)

```bash
# Global ~/.claude/CLAUDE.md
graphify-sf claude install

# Project-level ./CLAUDE.md
graphify-sf claude install --scope project

# Remove
graphify-sf claude uninstall
```

### Using the skill

Once installed, type `/graphify-sf` in your AI coding assistant. The skill will:

1. Detect your SFDX metadata files
2. Extract, build, cluster, and report
3. Present god nodes, surprising connections, and suggested questions
4. Offer to trace the most interesting question through the graph

---

## Git Integration

### Post-commit hook — auto-rebuild on commit

```bash
# Install: rebuilds graph after any commit that touches metadata files
graphify-sf hook install

# Remove
graphify-sf hook uninstall

# Check status
graphify-sf hook status
```

The hook installs both `post-commit` and `post-checkout` hooks:

- **post-commit** — diffs `HEAD~1..HEAD`, triggers rebuild only when `.cls/.trigger/.flow-meta.xml/*-meta.xml` files changed
- **post-checkout** — triggers rebuild on branch switches (when `graphify-sf-out/` exists)

Both hooks run rebuilds in the **background** (`nohup ... & disown`) so `git commit` and `git checkout` return immediately. Rebuild log: `~/.cache/graphify-sf-rebuild.log`.

Both hooks skip during rebase, merge, and cherry-pick. The `_hooks_dir()` respects `core.hooksPath` (Husky/Lefthook compatibility).

### Merge driver — conflict-free graph.json merges

When two branches both modify `graph.json`, a normal git merge produces a JSON conflict. The graphify-sf merge driver performs a union merge instead (all nodes + all edges from both branches, deduplicated and re-clustered):

```bash
# Install (configures .gitattributes + .git/config)
graphify-sf merge-driver install

# Uninstall
graphify-sf merge-driver uninstall
```

After installation, git calls `graphify-sf merge-driver run %O %A %B` automatically on `graph.json` conflicts.

---

## File Watcher

Auto-rebuild the graph whenever metadata files change:

```bash
# Watch current directory, rebuild on any .cls/.trigger/.flow-meta.xml/... change
graphify-sf watch .

# Custom output directory and debounce (seconds to wait after last change)
graphify-sf watch /path/to/project --out my-out --debounce 5

# Also regenerate graph.html on each rebuild (slower)
graphify-sf watch . --viz

# Build directed graph on rebuild
graphify-sf watch . --directed
```

If `watchdog` is installed (`pip install graphify-sf[watch]`), uses efficient FS events. Otherwise falls back to polling every 5 seconds with a notice.

The watcher runs an initial full build if no `graph.json` exists, then incremental `--update` rebuilds on each detected change.

---

## MCP Server

Expose the graph as a set of tools to any MCP-compatible client (Claude Desktop, Cursor MCP, etc.) over stdio JSON-RPC 2.0:

```bash
graphify-sf serve
graphify-sf serve --graph path/to/graph.json
```

**Available tools:**

| Tool | Description |
|------|-------------|
| `graph_stats` | Node/edge/community counts, community labels, top sf_types |
| `query` | BFS or DFS traversal for a natural-language question |
| `get_node` | Full details for a single node (type, file, degree, all neighbors) |
| `get_neighbors` | Connections of a node (up to N, sorted by degree, optional `relation_filter`) |
| `shortest_path` | Shortest path between two named metadata nodes |
| `god_nodes` | Highest-degree nodes — the most central metadata in the org |
| `list_communities` | All communities with their labels and member counts |
| `get_community` | All members of a specific community (by id or label) |

**Available resources** (via `resources/list` and `resources/read`):

| Resource URI | Description |
|-------------|-------------|
| `graphify-sf://report` | Full GRAPH_REPORT.md as text/markdown |
| `graphify-sf://stats` | Graph statistics JSON |
| `graphify-sf://god-nodes` | Top 20 god nodes JSON |
| `graphify-sf://surprises` | Surprising cross-community connections JSON |
| `graphify-sf://audit` | EXTRACTED/INFERRED/AMBIGUOUS edge breakdown |
| `graphify-sf://questions` | Suggested exploration questions JSON |

### Claude Desktop configuration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "graphify-sf": {
      "command": "graphify-sf",
      "args": ["serve", "--graph", "/path/to/your/project/graphify-sf-out/graph.json"]
    }
  }
}
```

---

## CI/CD Integration

### Check for stale graph before a build

```yaml
# GitHub Actions example
- name: Check if graph needs update
  run: graphify-sf check-update . --out graphify-sf-out
  # Exits 0 = graph is current, exits 1 = changes detected
```

### Rebuild on metadata changes

```yaml
- name: Rebuild knowledge graph
  run: graphify-sf . --update --no-viz --force
```

### Check-update pattern (conditional rebuild)

```bash
graphify-sf check-update . || graphify-sf . --update --no-viz
```

---

## Supported Metadata Types

| sf_type | Source | What it extracts |
|---------|--------|-----------------|
| `ApexClass` | `.cls` | Class name, methods, SOQL queries, DML, callouts, extends/implements |
| `ApexTrigger` | `.trigger` | Trigger name, target object, DML events, handler class references |
| `ApexMethod` | `.cls` | Individual method signatures within a class |
| `Flow` | `.flow-meta.xml` | Flow name, referenced objects, fields, called subflows |
| `CustomObject` | `.object-meta.xml` | Object name, fields, validation rules, record types |
| `CustomField` | `.field-meta.xml` | Field name, type, lookup targets |
| `ValidationRule` | `*-meta.xml` | Rule name, parent object, formula references |
| `RecordType` | `*-meta.xml` | Record type name, parent object |
| `Layout` | `.layout-meta.xml` | Layout name, referenced fields and objects |
| `LWCBundle` | `lwc/*/` | Component name, imported Apex controllers, child components |
| `AuraBundle` | `aura/*/` | Component name, Apex controller references |
| `Profile` | `.profile-meta.xml` | Profile name, object/field/class permissions |
| `PermissionSet` | `.permissionset-meta.xml` | Permission set name, granted permissions |
| `CustomLabel` | `.labels-meta.xml` | Label names |
| `NamedCredential` | `.namedCredential-meta.xml` | Credential name, endpoint |
| `ExternalService` | `.externalService-meta.xml` | Service name, referenced schema |
| `Bot` | `.bot-meta.xml` | Agentforce agent definition — label, bot user |
| `BotVersion` | `.botVersion-meta.xml` | Agent version — links to orchestrator flow, topics, planner |
| `GenAiPlugin` | `.genAiPlugin-meta.xml` | Agentforce Topic — groups actions, contains GenAiFunctions |
| `GenAiFunction` | `.genAiFunction-meta.xml` | Agentforce Action — invokes an Apex class or Flow |
| `GenAiPlannerBundle` | `.genAiPlannerBundle-meta.xml` | Agent planner — maps to sub-agent topics |
| `AiAuthoringBundle` | `.aiAuthoringBundle-meta.xml` | Authoring container linking Bot to BotVersion |
| `PromptTemplate` | `.promptTemplate-meta.xml` | AI prompt template — primary object, flex action references |

### Edge Relations

| relation | Meaning |
|----------|---------|
| `triggers` | Apex trigger fires on DML events for this object |
| `queries` | Apex performs SOQL query on this sObject |
| `dml` | Apex performs insert/update/delete/upsert on this object |
| `calls` | Apex class/method calls another class/method |
| `references` | Flow, Layout, or Profile references this metadata |
| `contains` | Parent contains child (Object→Field, Class→Method) |
| `extends` | Apex class extends a superclass |
| `implements` | Apex class implements an interface |
| `invokes` | Flow calls a subflow, or Agentforce action calls an Apex class / Flow |

---

## Configuration

All configuration via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `GRAPHIFY_SF_OUT` | `graphify-sf-out` | Default output directory |
| `GRAPHIFY_SF_VIZ_NODE_LIMIT` | `5000` | Max nodes before HTML viz switches to aggregated community view |
| `GRAPHIFY_SF_FORCE` | `` | Set to `1`/`true` to always overwrite `graph.json` |
| `GRAPHIFY_SF_REBUILD_MEMORY_LIMIT_MB` | `` | Cap memory usage for background watch rebuilds (MB) |
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Override Claude Code config directory — only set if your Claude Code config lives at a non-standard path (company-managed dotfiles, CI, or multiple installations) |

### `.graphifysfignore`

Place a `.graphifysfignore` file at your project root to exclude files/directories from scanning (same syntax as `.gitignore` glob patterns):

```
# Exclude test data
force-app/test/**
# Exclude archived components
force-app/archived/**
*.bak
```

---

## Optional Extras

```bash
# Better community detection (Leiden algorithm, Python < 3.13 only)
pip install graphify-sf[leiden]

# Neo4j direct push support
pip install graphify-sf[neo4j]

# SVG/PNG graph image export
pip install graphify-sf[svg]

# Watchdog for efficient file-system events in watch mode
pip install graphify-sf[watch]

# MCP SDK (reserved for future native MCP SDK adoption)
pip install graphify-sf[mcp]

# LLM semantic extraction — Claude
pip install graphify-sf[claude]

# LLM semantic extraction — Gemini / Kimi / OpenAI / Ollama (all use openai SDK)
pip install graphify-sf[gemini]

# LLM semantic extraction — AWS Bedrock
pip install graphify-sf[bedrock]

# LLM semantic extraction — Claude + all OpenAI-compat backends
pip install graphify-sf[llm]

# Everything
pip install graphify-sf[all]
```

---

## Requirements

- Python 3.10+
- No Salesforce CLI, no org connection, no API keys
- Core dependencies: `networkx`, `datasketch`, `rapidfuzz`

---

## Architecture

```
graphify_sf/
├── detect.py       File scanner — classifies .cls/.trigger/.flow-meta.xml/... files
├── extract/        Per-type extractors — Apex, Flow, Object, LWC, Aura, Profile, Agentforce, ...
├── build.py        Graph construction — node/edge deduplication, merge strategies
├── cluster.py      Community detection — Louvain (default) or Leiden (optional)
├── analyze.py      Graph analysis — god nodes, surprising connections, question generation
├── report.py       GRAPH_REPORT.md generation
├── export.py       All export formats — HTML, SVG, Obsidian, GraphML, Cypher, wiki, ...
├── llm.py          LLM semantic extraction — 6 backends, SF-specific prompt, adaptive retry
├── watch.py        File-system watcher — fcntl rebuild lock, resource limits, callflow regen
├── serve.py        MCP stdio server — 8 tools, 6 resources, blank-stdin filter
├── cache.py        Per-file extraction cache — SHA-256 keyed, atomic writes
├── validate.py     Extraction schema validation — catches bad extractors before graph assembly
├── security.py     Input sanitization — sanitize_label, validate_graph_path
└── __main__.py     CLI entry point — all command dispatch
```

---

## License

MIT

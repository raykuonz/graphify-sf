---
name: graphify-sf
description: "Salesforce SFDX metadata knowledge graph — explore Apex, Flow, Object, LWC, and all metadata relationships interactively. Use when asked about a Salesforce project structure, metadata dependencies, impact analysis, or cross-component relationships — especially if graphify-sf-out/ exists, treat the question as a /graphify-sf query."
trigger: /graphify-sf
---

# /graphify-sf

Turn any Salesforce SFDX project into a navigable knowledge graph with community detection, an honest audit trail (EXTRACTED/INFERRED), and three outputs: interactive HTML, GraphRAG-ready JSON, and a plain-language GRAPH_REPORT.md. Works fully offline — no org connection required.

## Usage

```
/graphify-sf                                          # full pipeline on current directory
/graphify-sf <path>                                   # full pipeline on SFDX project path
/graphify-sf <path> --update                          # incremental — re-extract only changed files
/graphify-sf <path> --directed                        # build directed graph (source→target)
/graphify-sf <path> --no-viz                          # skip graph.html, just report + JSON
/graphify-sf <path> --out <dir>                       # custom output directory (default: graphify-sf-out)
/graphify-sf <path> --force                           # overwrite graph.json even if new graph is smaller
/graphify-sf <path> --max-workers N                   # parallel extraction worker count
/graphify-sf <path> --backend claude                  # add AI semantic layer (business rules, dead metadata)
/graphify-sf <path> --backend gemini                  # Gemini backend (cheapest, ~$0.05/1k files)
/graphify-sf <path> --backend auto                    # auto-detect backend from available API keys
/graphify-sf <path> --backend claude --token-budget 20000  # smaller chunks for large orgs
/graphify-sf cluster-only <path>                      # rerun clustering on existing graph
/graphify-sf cluster-only --no-viz                    # rerun clustering, skip HTML
/graphify-sf check-update <path>                      # dry-run diff — what would --update change?
/graphify-sf merge-graphs <g1.json> <g2.json>         # merge multiple graph.json files
/graphify-sf query "<question>"                       # BFS traversal — broad context
/graphify-sf query "<question>" --dfs                 # DFS — trace a specific dependency path
/graphify-sf query "<question>" --budget 3000         # cap answer at N tokens
/graphify-sf path "AccountService" "Account__c"       # shortest path between two nodes
/graphify-sf explain "AccountTrigger"                 # node details and all connections
/graphify-sf explain "Account" --relation triggers    # only show trigger connections (no cap)
/graphify-sf stats                                    # detailed type/relation/density breakdown
/graphify-sf export html                              # regenerate graph.html from existing graph.json
/graphify-sf export tree                              # D3 collapsible tree view by community
/graphify-sf export callflow-html                     # Mermaid call-flow diagram (Apex→Object→Trigger)
/graphify-sf export svg                               # static SVG graph image (needs [svg] extra)
/graphify-sf export obsidian                          # write Obsidian vault (one note per community)
/graphify-sf export graphml                           # export graph.graphml (Gephi, yEd)
/graphify-sf export cypher                            # generate cypher.txt for Neo4j
/graphify-sf export neo4j --push --uri bolt://localhost:7687 --password <pw>  # push to Neo4j
/graphify-sf export wiki                              # agent-crawlable markdown wiki
/graphify-sf export json                              # re-export clean graph.json
/graphify-sf agents install                           # write AGENTS.md enforcement rules (all agents)
/graphify-sf agents uninstall                         # remove graphify-sf section from AGENTS.md
/graphify-sf merge-driver install                     # register git merge driver for graph.json
/graphify-sf watch <path>                             # auto-rebuild on metadata changes
/graphify-sf serve                                    # MCP stdio server for agent graph access
```

## What graphify-sf is for

Drop any Salesforce SFDX project directory into graphify-sf and get a queryable knowledge graph of your metadata. Apex classes and triggers, Flows, Custom Objects and Fields, LWC/Aura components, Profiles, Permission Sets, Layouts, Validation Rules — all connected by their real relationships (triggers, references, queries, DML, calls, contains).

No org connection. No SFDX CLI needed. Pure XML/source parsing with community detection that surfaces cross-metadata couplings you wouldn't think to ask about.

Answers questions like:
- Which Apex classes query the Account object?
- What fires when an Opportunity is created?
- Which LWC components reference the same Apex controllers?
- What does changing this Validation Rule affect?
- Where is this Permission Set used?

## What You Must Do When Invoked

If the user invoked `/graphify-sf --help` or `/graphify-sf -h`, print the contents of the `## Usage` section above verbatim and stop.

If no path was given, use `.` (current directory). Do not ask the user for a path.

### Fast path — graph already exists

**Before running the pipeline, check if a graph is already built:**

```bash
ls graphify-sf-out/graph.json 2>/dev/null && echo "EXISTS" || echo "MISSING"
```

If `graphify-sf-out/graph.json` exists:
- **Skip Steps 1, 2, and 3 entirely.**
- Go directly to exploration using the CLI commands below (`query`, `explain`, `path`, `stats`).
- Do **not** re-run the pipeline unless the user explicitly asks for a rebuild (`--update`, `--force`, or `/graphify-sf <path>`).

**CRITICAL — how to run CLI commands in the fast-path:**

```bash
# Resolve the command (re-run Step 1's full resolution if .graphify_sf_cmd is missing)
if [ ! -f graphify-sf-out/.graphify_sf_cmd ]; then
    GRAPHIFY_SF_CMD=""
    command -v uvx      >/dev/null 2>&1 && uvx graphify-sf --version >/dev/null 2>&1 && GRAPHIFY_SF_CMD="uvx graphify-sf"
    [ -z "$GRAPHIFY_SF_CMD" ] && command -v uv >/dev/null 2>&1 && uv tool run graphify-sf --version >/dev/null 2>&1 && GRAPHIFY_SF_CMD="uv tool run graphify-sf"
    [ -z "$GRAPHIFY_SF_CMD" ] && command -v pipx >/dev/null 2>&1 && pipx run graphify-sf --version >/dev/null 2>&1 && GRAPHIFY_SF_CMD="pipx run graphify-sf"
    [ -z "$GRAPHIFY_SF_CMD" ] && command -v graphify-sf >/dev/null 2>&1 && GRAPHIFY_SF_CMD="graphify-sf"
    [ -z "$GRAPHIFY_SF_CMD" ] && GRAPHIFY_SF_CMD="python3 -m graphify_sf"
    mkdir -p graphify-sf-out && echo "$GRAPHIFY_SF_CMD" > graphify-sf-out/.graphify_sf_cmd
fi
# Now use it — ALWAYS use this exact pattern, never anything else:
$(cat graphify-sf-out/.graphify_sf_cmd) query "QUESTION" --graph graphify-sf-out/graph.json
$(cat graphify-sf-out/.graphify_sf_cmd) explain "NODE" --graph graphify-sf-out/graph.json
```

**NEVER do any of these:**
- ❌ Write Python heredocs to detect the interpreter (`PY=$(python3 - <<'PY' ...`)
- ❌ Read `.graphify_sf_python` — that file is from an old version and has been deleted
- ❌ Use `"$PY" -m graphify_sf` — use `$(cat graphify-sf-out/.graphify_sf_cmd)` instead
- ❌ Parse `graph.json` directly with Python — the CLI commands handle the graph format correctly

If the graph is missing, follow all steps in order.

Follow these steps in order. Do not skip steps.

### Step 1 — Resolve the graphify-sf command

Prefer ephemeral runners (`uvx`, `pipx run`) so no permanent install is needed on the developer's machine. Fall back to an existing install, then to pip as a last resort.

```bash
GRAPHIFY_SF_CMD=""

# 1. uvx — uv's zero-install tool runner (installs to uv cache, never touches system Python)
if [ -z "$GRAPHIFY_SF_CMD" ] && command -v uvx >/dev/null 2>&1; then
    uvx graphify-sf --version >/dev/null 2>&1 && GRAPHIFY_SF_CMD="uvx graphify-sf"
fi

# 2. uv tool run — same as uvx but explicit (older uv versions)
if [ -z "$GRAPHIFY_SF_CMD" ] && command -v uv >/dev/null 2>&1; then
    uv tool run graphify-sf --version >/dev/null 2>&1 && GRAPHIFY_SF_CMD="uv tool run graphify-sf"
fi

# 3. pipx run — pipx ephemeral runner (installs to pipx cache, no system pollution)
if [ -z "$GRAPHIFY_SF_CMD" ] && command -v pipx >/dev/null 2>&1; then
    pipx run graphify-sf --version >/dev/null 2>&1 && GRAPHIFY_SF_CMD="pipx run graphify-sf"
fi

# 4. Already-installed CLI binary
if [ -z "$GRAPHIFY_SF_CMD" ] && command -v graphify-sf >/dev/null 2>&1; then
    GRAPHIFY_SF_CMD="graphify-sf"
fi

# 5. Already installed as a Python module
if [ -z "$GRAPHIFY_SF_CMD" ] && python3 -c "import graphify_sf" 2>/dev/null; then
    GRAPHIFY_SF_CMD="python3 -m graphify_sf"
fi

# 6. Last resort — install permanently
if [ -z "$GRAPHIFY_SF_CMD" ]; then
    if command -v uv >/dev/null 2>&1; then
        uv pip install graphify-sf -q 2>/dev/null
    else
        python3 -m pip install graphify-sf -q 2>/dev/null \
            || python3 -m pip install graphify-sf -q --break-system-packages 2>&1 | tail -3
    fi
    GRAPHIFY_SF_CMD="python3 -m graphify_sf"
fi

mkdir -p graphify-sf-out
echo "$GRAPHIFY_SF_CMD" > graphify-sf-out/.graphify_sf_cmd
```

If the command resolves, print nothing and move to Step 2.

**In every subsequent bash block, use `$(cat graphify-sf-out/.graphify_sf_cmd)` in place of `graphify-sf`.**

### Step 2 — Detect SFDX metadata files

Count files using shell commands — no Python or graphify-sf install needed at this point.

```bash
INPUT="INPUT_PATH"
APEX=$(find "$INPUT" \( -name "*.cls" -o -name "*.trigger" \) 2>/dev/null | wc -l | tr -d ' ')
FLOWS=$(find "$INPUT" -name "*.flow-meta.xml" 2>/dev/null | wc -l | tr -d ' ')
OBJECTS=$(find "$INPUT" \( -name "*.object-meta.xml" -o -name "*.field-meta.xml" \) 2>/dev/null | wc -l | tr -d ' ')
LAYOUTS=$(find "$INPUT" -name "*.layout-meta.xml" 2>/dev/null | wc -l | tr -d ' ')
PROFILES=$(find "$INPUT" \( -name "*.profile-meta.xml" -o -name "*.permissionset-meta.xml" \) 2>/dev/null | wc -l | tr -d ' ')
LWC=$(find "$INPUT" -path "*/lwc/*" -name "*.js" -not -name "*.test.js" 2>/dev/null | grep -v __tests__ | wc -l | tr -d ' ')
AURA=$(find "$INPUT" -path "*/aura/*" -name "*.cmp" 2>/dev/null | wc -l | tr -d ' ')
TOTAL=$((APEX + FLOWS + OBJECTS + LAYOUTS + PROFILES + LWC + AURA))
echo "SFDX Project: $INPUT"
[ "$APEX" -gt 0 ]     && echo "  apex:     $APEX files (.cls .trigger)"
[ "$FLOWS" -gt 0 ]    && echo "  flows:    $FLOWS files (.flow-meta.xml)"
[ "$OBJECTS" -gt 0 ]  && echo "  objects:  $OBJECTS files"
[ "$LAYOUTS" -gt 0 ]  && echo "  layouts:  $LAYOUTS files"
[ "$PROFILES" -gt 0 ] && echo "  profiles: $PROFILES files"
[ "$LWC" -gt 0 ]      && echo "  lwc:      $LWC components"
[ "$AURA" -gt 0 ]     && echo "  aura:     $AURA components"
echo "  total:    $TOTAL metadata items"
```

Replace `INPUT_PATH` with the actual path. Present the output as a clean summary.

- If `TOTAL` is 0: stop with "No Salesforce metadata files found in [path]. Is this an SFDX project with a `force-app/` directory?"
- Otherwise: proceed to Step 3.

### Step 3 — Extract, build, cluster, and report

```bash
$(cat graphify-sf-out/.graphify_sf_cmd) INPUT_PATH --out graphify-sf-out
```

This runs the full pipeline in one shot: extract all metadata → build graph → cluster → generate GRAPH_REPORT.md + graph.json + graph.html.

Replace `INPUT_PATH` with the actual path.

If `--update` was given, pass `--update` to the command. If `--directed` was given, pass `--directed`. If `--no-viz` was given, pass `--no-viz`. If `--backend <name>` was given, pass `--backend <name>`. If `--token-budget N` was given, pass `--token-budget N`.

The command prints progress lines. When it finishes, you will see:

```
[graphify-sf] done
  N nodes · N edges · N communities
  Report: graphify-sf-out/GRAPH_REPORT.md
  Graph:  graphify-sf-out/graph.json
  HTML:   graphify-sf-out/graph.html
```

If the command exits with a non-zero code, show the last 20 lines of output and stop.

### Step 4 — Read the report and present findings

Read `graphify-sf-out/GRAPH_REPORT.md`. Then paste these three sections directly into the chat:

- **God Nodes** (highest-degree metadata — most central to the org)
- **Surprising Connections** (cross-community edges)
- **Suggested Questions**

Do NOT paste the full report — just those three sections.

Then immediately offer to explore. Pick the single most interesting suggested question from the report — the one that crosses the most metadata type boundaries — and ask:

> "The most interesting question this graph can answer: **[question]**. Want me to trace it?"

If the user says yes, run `/graphify-sf query "[question]"` on the graph and walk them through the answer using the graph structure: which nodes connect, which community boundaries get crossed, what the path reveals. Keep going as long as they want to explore. Each answer should end with a natural follow-up ("this connects to X — want to go deeper?") so the session feels like navigation, not a one-shot report.

The graph is the map. Your job after the pipeline is to be the guide.

---

## Command guard for subcommands

Before running any subcommand (`--update`, `cluster-only`, `query`, `path`, `explain`, `export`), check that `.graphify_sf_cmd` exists. If it's missing (e.g. user deleted `graphify-sf-out/`), re-resolve using the same priority order as Step 1:

```bash
if [ ! -f graphify-sf-out/.graphify_sf_cmd ]; then
    GRAPHIFY_SF_CMD=""
    command -v uvx >/dev/null 2>&1 && uvx graphify-sf --version >/dev/null 2>&1 \
        && GRAPHIFY_SF_CMD="uvx graphify-sf"
    [ -z "$GRAPHIFY_SF_CMD" ] && command -v uv >/dev/null 2>&1 \
        && uv tool run graphify-sf --version >/dev/null 2>&1 \
        && GRAPHIFY_SF_CMD="uv tool run graphify-sf"
    [ -z "$GRAPHIFY_SF_CMD" ] && command -v pipx >/dev/null 2>&1 \
        && pipx run graphify-sf --version >/dev/null 2>&1 \
        && GRAPHIFY_SF_CMD="pipx run graphify-sf"
    [ -z "$GRAPHIFY_SF_CMD" ] && command -v graphify-sf >/dev/null 2>&1 \
        && GRAPHIFY_SF_CMD="graphify-sf"
    [ -z "$GRAPHIFY_SF_CMD" ] && GRAPHIFY_SF_CMD="python3 -m graphify_sf"
    mkdir -p graphify-sf-out
    echo "$GRAPHIFY_SF_CMD" > graphify-sf-out/.graphify_sf_cmd
fi
```

---

## For --update (incremental re-extraction)

Use when you've added or modified metadata since the last run. Only re-extracts changed files — saves time on large projects.

```bash
$(cat graphify-sf-out/.graphify_sf_cmd) INPUT_PATH --out graphify-sf-out --update
```

The command merges new nodes and edges into the existing `graph.json`, updates `GRAPH_REPORT.md`, and regenerates the HTML.

---

## For cluster-only

Skip extraction and re-run only community detection on the existing graph. Useful after manually editing `graph.json` or tuning cluster parameters.

```bash
$(cat graphify-sf-out/.graphify_sf_cmd) cluster-only INPUT_PATH --out graphify-sf-out
```

Then run Step 4 as normal (read report and present findings).

---

## For /graphify-sf query

Two traversal modes — choose based on the question:

| Mode | Flag | Best for |
|------|------|----------|
| BFS (default) | _(none)_ | "What is X connected to?" — broad context, nearest neighbors first |
| DFS | `--dfs` | "How does X reach Y?" — trace a specific dependency chain |

```bash
$(cat graphify-sf-out/.graphify_sf_cmd) query "QUESTION" --graph graphify-sf-out/graph.json
# or: --dfs --budget 3000
```

Replace `QUESTION` with the user's actual question. Answer using **only** what the graph output contains. Quote `source_location` when citing a specific fact. If the graph lacks enough information, say so — do not hallucinate edges.

---

## For /graphify-sf path

Find the shortest path between two named Salesforce metadata nodes.

```bash
$(cat graphify-sf-out/.graphify_sf_cmd) path "SOURCE_NODE" "TARGET_NODE" --graph graphify-sf-out/graph.json
```

Replace `SOURCE_NODE` and `TARGET_NODE` with actual metadata names (e.g. `"AccountTrigger"`, `"Account__c"`). Then explain the path in plain language — what each hop means (trigger → object, field → lookup, class → query, etc.) and why it's significant.

---

## For /graphify-sf explain

Give a complete picture of a single metadata node — its type, file location, community, degree, and all connections.

```bash
# All connections (top 20 by degree)
$(cat graphify-sf-out/.graphify_sf_cmd) explain "NODE_NAME" --graph graphify-sf-out/graph.json

# Only connections with a specific relation (no cap — shows every match)
$(cat graphify-sf-out/.graphify_sf_cmd) explain "NODE_NAME" --relation triggers --graph graphify-sf-out/graph.json
$(cat graphify-sf-out/.graphify_sf_cmd) explain "NODE_NAME" --relation invokes --graph graphify-sf-out/graph.json
$(cat graphify-sf-out/.graphify_sf_cmd) explain "NODE_NAME" --relation queries --graph graphify-sf-out/graph.json
```

Replace `NODE_NAME` with the metadata name the user asked about. Use `--relation` when the question is specifically about one kind of dependency — for example, "what triggers on Account?" → `--relation triggers`. Then write a 3–5 sentence explanation: what this node is, what it connects to, and why those connections are significant in the org's metadata dependency graph.

**Common relation values:** `triggers`, `invokes`, `calls`, `references`, `contains`, `queries`, `dml`, `extends`, `implements`

---

## For export subcommands

All export commands operate on an existing `graph.json` — no re-extraction needed.

```bash
# Regenerate interactive HTML
$(cat graphify-sf-out/.graphify_sf_cmd) export html --graph graphify-sf-out/graph.json --out graphify-sf-out

# Write Obsidian vault (one note per community + one per node)
$(cat graphify-sf-out/.graphify_sf_cmd) export obsidian --graph graphify-sf-out/graph.json --out graphify-sf-out

# Export graph.graphml for Gephi / yEd
$(cat graphify-sf-out/.graphify_sf_cmd) export graphml --graph graphify-sf-out/graph.json --out graphify-sf-out

# Generate Cypher statements for Neo4j
$(cat graphify-sf-out/.graphify_sf_cmd) export cypher --graph graphify-sf-out/graph.json --out graphify-sf-out
```

---

## Salesforce metadata types decoded

When presenting graph findings, translate node types into plain language:

| sf_type | What it is |
|---------|------------|
| `ApexClass` | Apex class — business logic, triggers handlers, utilities |
| `ApexTrigger` | Apex trigger — fires on DML events for a specific object |
| `ApexMethod` | Method within an Apex class |
| `Flow` | Flow or Process Builder — declarative automation |
| `CustomObject` | Custom or standard Salesforce object (sObject) |
| `CustomField` | Field on an object (including Lookup/MasterDetail relationships) |
| `ValidationRule` | Prevents invalid data from being saved |
| `RecordType` | Variant of an object with different picklist values and layouts |
| `Layout` | Page layout — controls field order and visibility |
| `LWCBundle` | Lightning Web Component — modern UI component |
| `AuraBundle` | Aura/Lightning Component — older UI component |
| `Profile` | User profile — object/field/class permissions |
| `PermissionSet` | Additive permissions that extend profiles |
| `CustomLabel` | Translatable text constant |
| `CustomMetadata` | Configuration metadata record |
| `NamedCredential` | External service endpoint definition |
| `ExternalService` | OpenAPI-based external service integration |
| `Bot` | Agentforce agent definition |
| `BotVersion` | Agent version — links to orchestrator flow, topics, planner |
| `GenAiPlugin` | Agentforce Topic — groups actions |
| `GenAiFunction` | Agentforce Action — invokes Apex or Flow |
| `GenAiPlannerBundle` | Agent planner — maps to sub-agent topics |
| `AiAuthoringBundle` | Authoring container linking Bot to BotVersion |
| `PromptTemplate` | AI prompt template — primary object, flex action references |

Edge relations and what they mean:

| relation | Meaning |
|----------|---------|
| `triggers` | Trigger fires on DML events for this object |
| `queries` | Apex queries this sObject via SOQL |
| `dml` | Apex performs insert/update/delete on this object |
| `calls` | Apex method calls another class/method |
| `references` | Flow/Layout/Profile/Agentforce references this metadata |
| `contains` | Parent contains child (Object→Field, Class→Method, Topic→Action) |
| `extends` | Apex class extends a superclass |
| `implements` | Apex class implements an interface |
| `invokes` | Flow calls a subflow, or Agentforce action calls Apex/Flow |

---

## Honesty Rules

- Never invent an edge. If unsure, mark it INFERRED.
- Always show token cost (0 for graphify-sf — extraction is local, no LLM needed).
- Never hide cohesion scores — show the raw number.
- Never run HTML viz on a graph with more than 5,000 nodes without warning the user.
- If a metadata node has `confidence: INFERRED`, tell the user — that relationship was inferred from source patterns, not from an explicit XML tag.
- **Never write Python (heredocs, inline scripts, or `-c` one-liners) to detect the interpreter, read `.graphify_sf_python`, or invoke graphify-sf.** The only correct invocation pattern is `$(cat graphify-sf-out/.graphify_sf_cmd) <subcommand>`. If `.graphify_sf_cmd` is missing, run the resolver block in the fast-path section — never improvise.

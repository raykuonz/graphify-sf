# graphify-sf (npm)

Install and run [graphify-sf](https://github.com/raykuonz/graphify-sf) — the Salesforce SFDX
knowledge-graph tool — from npm, without needing Python.

On install, a pre-built binary matching your OS/arch is downloaded from the GitHub Release.

## Install

```bash
npm install graphify-sf
# or
pnpm add graphify-sf
```

> **pnpm note:** pnpm sets `ignore-scripts=true` by default, so the `postinstall` step may not
> run automatically. The binary is downloaded lazily on first use instead, so everything still
> works — you may just see a one-time download message the first time you invoke the CLI.

## CLI usage

```bash
npx graphify-sf ./force-app --out my-graph-out --no-viz
```

The output directory will contain `graph.json` with the full knowledge graph.

## Programmatic usage (Node.js / sf-cockpit)

```js
const { runGraphify } = require("graphify-sf");

const { graphJsonPath } = await runGraphify("./force-app", { outDir: "my-graph-out" });
console.log("Graph written to:", graphJsonPath);
```

`runGraphify` returns a Promise that resolves with `{ code, graphJsonPath }` on success and
rejects on non-zero exit.

Additional exports: `ensureBinary()` (downloads if missing, returns path), `binaryPath()`
(returns expected path without triggering a download).

## What's bundled

This package wraps the **core static-extraction path** of graphify-sf: Apex, Flow, Object, LWC,
Aura, Profile/PermSet, and Agentforce metadata — everything that can be parsed without an org
connection. Community detection and the knowledge-graph JSON export are included.

**Not bundled:** LLM-assisted extraction (`--backend`), SVG export, Neo4j export, MCP server, and
file-watcher mode. Those extras require a full Python install:

```bash
pip install "graphify-sf[all]"
# or
pipx install "graphify-sf[all]"
```

## Supported platforms

| Platform  | x64 | arm64 |
|-----------|-----|-------|
| linux     | ✓   | ✓     |
| macOS     | ✓   | ✓     |
| Windows   | ✓   | —     |

For unsupported platforms, install via PyPI: `pipx install graphify-sf`.

## License

MIT — see [LICENSE](https://github.com/raykuonz/graphify-sf/blob/main/LICENSE).

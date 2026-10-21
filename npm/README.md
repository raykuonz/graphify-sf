# graphify-sf (npm)

Install and run [graphify-sf](https://github.com/raykuonz/graphify-sf) — the Salesforce SFDX
knowledge-graph tool — from npm, without needing Python.

The pre-built binary for your OS/arch arrives with the install, inside a platform package
(`@graphify-sf/cli-<os>-<arch>`, an optional dependency); no download is needed. If that package
is missing (`--omit=optional`, or a registry mirror without the `@graphify-sf` scope), the binary
is downloaded from the GitHub Release instead. That download is checked against the sha256 shipped
in this package (`checksums.json`) and is refused if it doesn't match. Packages are published
from CI with npm provenance.

**Supported platforms:** macOS (x64, arm64), Windows x64, and Linux x64/arm64 with **glibc 2.28 or
newer**: RHEL/AlmaLinux/Rocky 8+, Debian 11+ (including `node:*-bookworm` images), Ubuntu 20.04+,
Amazon Linux 2023. musl-based distros (Alpine) aren't supported by the binary; use
`pipx install graphify-sf` there.

## Install

```bash
npm install graphify-sf
# or
pnpm add graphify-sf
```

> **pnpm note:** pnpm sets `ignore-scripts=true` by default, so the `postinstall` step may not
> run automatically. That only matters on the fallback path above: the binary is then downloaded
> (and verified) lazily on first use, so you may see a one-time download message.

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

Additional exports: `ensureBinary()` (resolves the binary, downloading and verifying it if
needed, and returns its path), `binaryPath()` (returns the fallback download path without
triggering a download).

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

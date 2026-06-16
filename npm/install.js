"use strict";

// postinstall hook.
//
// As of 0.3.9 the prebuilt binary normally arrives WITH `npm install`, shipped
// inside a platform-specific scoped subpackage (@graphify-sf/cli-<plat>-<arch>)
// declared in optionalDependencies. npm installs only the subpackage matching
// the host os/cpu, so on a supported platform the binary is already present and
// this hook makes ZERO network requests.
//
// Resolution order (see lib/download.js ensureBinary):
//   1. GRAPHIFY_BIN env override
//   2. the installed platform subpackage  <-- 0.3.9 happy path, no network
//   3. a previously-downloaded binary in bin/
//   4. download from GitHub Releases       <-- fallback only
//
// A failed download in step 4 MUST NOT abort the consumer's `npm install`
// (graphify-sf is an optional second engine for its consumers). So this hook
// always exits 0: if no binary resolves and the fallback download fails, we
// print actionable remediation and still exit 0; the binary is fetched lazily
// on first run instead.

const { envBinary, subpackageBinary, download } = require("./lib/download");

async function main() {
  // If a binary already resolves (env override or the platform subpackage),
  // there is nothing to do — and crucially, no network request.
  if (envBinary() || subpackageBinary()) {
    process.exit(0);
  }

  // No prebuilt binary available for this platform (unsupported platform,
  // --no-optional, or a registry that doesn't carry the scoped subpackages).
  // Try the GitHub Releases fallback, but never fail the install.
  try {
    await download();
    process.exit(0);
  } catch (err) {
    process.stderr.write(
      `\ngraphify-sf: no prebuilt binary for this platform and the fallback download failed.\n` +
        `  Reason: ${err.message}\n` +
        `\n` +
        `  This is non-fatal — installation will continue. The binary will be\n` +
        `  fetched automatically the first time you run graphify-sf, provided\n` +
        `  network access is available then.\n` +
        `\n` +
        `  If your network blocks GitHub Releases, use one of these instead:\n` +
        `    • Install the Python package directly:  pipx install graphify-sf\n` +
        `    • Point at an existing binary:           export GRAPHIFY_BIN=/path/to/graphify-sf\n` +
        `\n`
    );
    process.exit(0);
  }
}

main();

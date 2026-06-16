"use strict";

// postinstall hook.
//
// The graphify-sf npm package is a thin wrapper that fetches a prebuilt binary
// from the project's GitHub Releases. In locked-down corporate networks the
// download can be blocked by a proxy or firewall. A failed download here MUST
// NOT abort `npm install` for the whole dependency tree — graphify-sf is an
// optional second engine for its consumers, so a missing binary should degrade
// gracefully (the binary is fetched lazily on first run, and there are offline
// remediation paths).
//
// Therefore: never exit non-zero from postinstall. Print a clear, actionable
// warning and exit 0. The actual binary resolution happens later via
// download.ensureBinary() at first invocation.

const { download } = require("./lib/download");

download()
  .then(() => {
    process.exit(0);
  })
  .catch((err) => {
    process.stderr.write(
      `\ngraphify-sf: could not pre-fetch the CLI binary during install.\n` +
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
    // Non-fatal: do not break the consumer's `npm install`.
    process.exit(0);
  });

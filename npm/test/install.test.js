"use strict";

// Regression tests for the npm postinstall behaviour.
//
// The critical invariant (the bug behind 0.3.8): a FAILED binary download
// during `npm install` must NOT abort the consumer's install. The postinstall
// hook must always exit 0, even when GitHub Releases is unreachable (blocked by
// a corporate proxy/firewall, 404, DNS failure, etc.).
//
// These tests run the real install.js in a child process with the download
// forced to fail, and assert the process exits 0.

const { test } = require("node:test");
const assert = require("node:assert");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");

const INSTALL_JS = path.join(__dirname, "..", "install.js");

// Helper: run install.js in a child node process with ./lib/download replaced
// by a stub that always rejects, simulating a blocked / failed download.
// Returns the child process result ({ status, stdout, stderr }).
function runInstallWithFailingDownload() {
  // A loader that intercepts require("./lib/download") (resolved to an absolute
  // path from install.js) and substitutes a failing download().
  const downloadAbs = path.join(__dirname, "..", "lib", "download.js");
  const loader = `
    const Module = require("node:module");
    const origLoad = Module._load;
    Module._load = function (request, parent, isMain) {
      const real = origLoad.apply(this, arguments);
      const resolved = (() => {
        try { return Module._resolveFilename(request, parent, isMain); }
        catch { return request; }
      })();
      if (resolved === ${JSON.stringify(downloadAbs)}) {
        // Preserve the real module (envBinary/subpackageBinary) and only force
        // the network download() to fail.
        return Object.assign({}, real, {
          download: () =>
            Promise.reject(
              new Error("simulated: download failed with HTTP 404 (network blocked)")
            ),
        });
      }
      return real;
    };
    require(${JSON.stringify(INSTALL_JS)});
  `;

  const tmp = path.join(
    fs.mkdtempSync(path.join(os.tmpdir(), "gsf-install-test-")),
    "run.js"
  );
  fs.writeFileSync(tmp, loader);

  return spawnSync(process.execPath, [tmp], { encoding: "utf8" });
}

test("postinstall exits 0 when the binary download fails", () => {
  const res = runInstallWithFailingDownload();
  assert.strictEqual(
    res.status,
    0,
    `expected exit code 0 on failed download, got ${res.status}.\n` +
      `stdout: ${res.stdout}\nstderr: ${res.stderr}`
  );
});

test("postinstall prints actionable remediation when download fails", () => {
  const res = runInstallWithFailingDownload();
  const out = `${res.stdout}\n${res.stderr}`;
  assert.match(out, /pipx install graphify-sf/, "should mention pipx remediation");
  assert.match(out, /GRAPHIFY_BIN/, "should mention GRAPHIFY_BIN escape hatch");
  assert.match(out, /non-fatal/i, "should communicate that the failure is non-fatal");
});

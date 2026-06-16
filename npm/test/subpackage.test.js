"use strict";

// Tests for the 0.3.9 platform-subpackage binary resolution.
//
// The 0.3.9 happy path ships the binary inside @graphify-sf/cli-<plat>-<arch>
// via optionalDependencies, so `npm install` delivers the binary with no
// network request. These tests build a temp node_modules fixture containing a
// fake scoped subpackage and assert resolution works (and that no network is
// touched). They run a child node process whose require() resolves the fixture.

const { test } = require("node:test");
const assert = require("node:assert");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");

const DOWNLOAD_JS = path.join(__dirname, "..", "lib", "download.js");
const INSTALL_JS = path.join(__dirname, "..", "install.js");

// Build a temp dir with node_modules/@graphify-sf/cli-<plat>-<arch>/graphify-sf
// matching the CURRENT host platform, so subpackageBinary() resolves it.
function makeSubpackageFixture() {
  const plat = process.platform;
  const arch = process.arch;
  const binName = plat === "win32" ? "graphify-sf.exe" : "graphify-sf";
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "gsf-subpkg-"));
  const pkgDir = path.join(root, "node_modules", "@graphify-sf", `cli-${plat}-${arch}`);
  fs.mkdirSync(pkgDir, { recursive: true });
  fs.writeFileSync(
    path.join(pkgDir, "package.json"),
    JSON.stringify({
      name: `@graphify-sf/cli-${plat}-${arch}`,
      version: "0.3.9",
      os: [plat],
      cpu: [arch],
      files: [binName],
    }) + "\n"
  );
  const binPath = path.join(pkgDir, binName);
  fs.writeFileSync(binPath, "#!/bin/sh\necho fake-binary\n");
  if (plat !== "win32") fs.chmodSync(binPath, 0o755);
  return { root, binPath };
}

// Run a snippet in a child node process whose module resolution is rooted at
// `cwd` (so require.resolve finds the fixture's node_modules).
function runInFixture(cwd, snippet) {
  const tmp = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "gsf-run-")), "run.js");
  fs.writeFileSync(tmp, snippet);
  return spawnSync(process.execPath, [tmp], { cwd, encoding: "utf8" });
}

test("subpackageBinary resolves the binary from an installed subpackage", () => {
  const { root, binPath } = makeSubpackageFixture();
  const snippet = `
    const { subpackageBinary } = require(${JSON.stringify(DOWNLOAD_JS)});
    const r = subpackageBinary();
    process.stdout.write(JSON.stringify({ r }));
  `;
  const res = runInFixture(root, snippet);
  assert.strictEqual(res.status, 0, res.stderr);
  const { r } = JSON.parse(res.stdout);
  assert.strictEqual(r, binPath, `expected resolved path ${binPath}, got ${r}`);
});

test("subpackageBinary returns null when no subpackage is installed", () => {
  const emptyRoot = fs.mkdtempSync(path.join(os.tmpdir(), "gsf-empty-"));
  const snippet = `
    const { subpackageBinary } = require(${JSON.stringify(DOWNLOAD_JS)});
    process.stdout.write(JSON.stringify({ r: subpackageBinary() }));
  `;
  const res = runInFixture(emptyRoot, snippet);
  assert.strictEqual(res.status, 0, res.stderr);
  assert.strictEqual(JSON.parse(res.stdout).r, null);
});

test("ensureBinary prefers the subpackage over the network (no download call)", async () => {
  const { root, binPath } = makeSubpackageFixture();
  // Stub download() to throw if invoked; ensureBinary must not reach it.
  const snippet = `
    const dl = require(${JSON.stringify(DOWNLOAD_JS)});
    dl.download = () => { throw new Error("network must not be touched"); };
    dl.ensureBinary().then((p) => {
      process.stdout.write(JSON.stringify({ p }));
    }).catch((e) => {
      process.stderr.write(e.message);
      process.exit(1);
    });
  `;
  const res = runInFixture(root, snippet);
  assert.strictEqual(res.status, 0, res.stderr);
  assert.strictEqual(JSON.parse(res.stdout).p, binPath);
});

test("postinstall makes no network request when the subpackage is present", () => {
  const { root } = makeSubpackageFixture();
  // Load install.js with download() replaced by a throwing stub; if the hook
  // tries to download, the child would print the throw. We assert exit 0 and
  // that the failure-remediation banner is NOT printed (i.e. download not hit).
  const snippet = `
    const Module = require("node:module");
    const origLoad = Module._load;
    Module._load = function (request, parent, isMain) {
      const real = origLoad.apply(this, arguments);
      if (request.endsWith("lib/download") || request.endsWith("lib/download.js")) {
        return Object.assign({}, real, {
          download: () => Promise.reject(new Error("network must not be touched")),
        });
      }
      return real;
    };
    require(${JSON.stringify(INSTALL_JS)});
  `;
  const res = runInFixture(root, snippet);
  assert.strictEqual(res.status, 0, `expected exit 0, got ${res.status}\n${res.stderr}`);
  assert.doesNotMatch(
    `${res.stdout}\n${res.stderr}`,
    /fallback download failed/,
    "postinstall should not attempt a download when the subpackage is present"
  );
});

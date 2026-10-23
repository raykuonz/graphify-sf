"use strict";

// Error messages thrown by lib/download.js already start with "graphify-sf: ".
// The launcher and the postinstall hook print them under their own prefix, which
// used to produce "graphify-sf: graphify-sf: sha256 mismatch ...".

const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const { describeError } = require("../lib/download");

test("describeError strips exactly one leading graphify-sf: prefix", () => {
  assert.strictEqual(describeError(new Error("graphify-sf: sha256 mismatch")), "sha256 mismatch");
  assert.strictEqual(
    describeError(new Error("graphify-sf: graphify-sf: odd")),
    "graphify-sf: odd"
  );
});

test("describeError leaves other messages alone", () => {
  assert.strictEqual(describeError(new Error("ENOTFOUND github.com")), "ENOTFOUND github.com");
  assert.strictEqual(describeError("plain string"), "plain string");
  assert.strictEqual(describeError(new Error("see graphify-sf: docs")), "see graphify-sf: docs");
});

test("the launcher prints a single prefix", () => {
  const npmDir = path.resolve(__dirname, "..");
  const script = `
    const dl = require(${JSON.stringify(path.join(npmDir, "lib", "download.js"))});
    dl.ensureBinary = () => Promise.reject(new Error("graphify-sf: sha256 mismatch for asset"));
    require(${JSON.stringify(path.join(npmDir, "bin", "graphify-sf.js"))});
  `;
  const result = spawnSync(process.execPath, ["-e", script], { encoding: "utf8" });

  assert.strictEqual(result.status, 1);
  assert.strictEqual(result.stderr, "graphify-sf: sha256 mismatch for asset\n");
});

"use strict";

// Unit tests for binary resolution precedence in lib/download.js.
//
// ensureBinary() resolution order (highest priority first):
//   1. GRAPHIFY_BIN env var pointing at an existing file
//   2. an already-downloaded binary in the package bin/ dir
//   3. lazy download (network)
//
// These tests cover (1) — the offline escape hatch — without touching the
// network. We do not exercise (3) here to keep the suite hermetic.

const { test } = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");

const { ensureBinary, envBinary } = require("../lib/download");

test("envBinary returns the path when GRAPHIFY_BIN points at an existing file", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gsf-bin-test-"));
  const fake = path.join(dir, "graphify-sf");
  fs.writeFileSync(fake, "#!/bin/sh\necho fake\n");
  const prev = process.env.GRAPHIFY_BIN;
  process.env.GRAPHIFY_BIN = fake;
  try {
    assert.strictEqual(envBinary(), fake);
  } finally {
    if (prev === undefined) delete process.env.GRAPHIFY_BIN;
    else process.env.GRAPHIFY_BIN = prev;
  }
});

test("envBinary returns null when GRAPHIFY_BIN points at a missing file", () => {
  const prev = process.env.GRAPHIFY_BIN;
  process.env.GRAPHIFY_BIN = path.join(os.tmpdir(), "does-not-exist-gsf-xyz");
  try {
    assert.strictEqual(envBinary(), null);
  } finally {
    if (prev === undefined) delete process.env.GRAPHIFY_BIN;
    else process.env.GRAPHIFY_BIN = prev;
  }
});

test("ensureBinary resolves GRAPHIFY_BIN without touching the network", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gsf-bin-test-"));
  const fake = path.join(dir, "graphify-sf");
  fs.writeFileSync(fake, "#!/bin/sh\necho fake\n");
  const prev = process.env.GRAPHIFY_BIN;
  process.env.GRAPHIFY_BIN = fake;
  try {
    const resolved = await ensureBinary();
    assert.strictEqual(resolved, fake);
  } finally {
    if (prev === undefined) delete process.env.GRAPHIFY_BIN;
    else process.env.GRAPHIFY_BIN = prev;
  }
});

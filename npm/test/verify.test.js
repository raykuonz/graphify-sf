"use strict";

// Integrity checks for the GitHub Releases fallback download (lib/download.js).
//
// The fallback runs only when no @graphify-sf/cli-* subpackage resolved
// (--omit=optional, or a registry mirror without the scope). Release assets can
// be replaced under an existing tag, so a downloaded binary must match the
// sha256 recorded in checksums.json (shipped inside the integrity-pinned npm
// tarball) before it is renamed into place or executed. A local HTTP server
// stands in for GitHub.

const { test, after } = require("node:test");
const assert = require("node:assert");
const http = require("node:http");
const https = require("node:https");
const crypto = require("node:crypto");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");

const { assetName, binaryPath, download, ensureBinary, verifiedCachedBinary } = require("../lib/download");

// Hermetic by construction: if a regression ever ignores the injected fetch or
// dest, the test fails here instead of downloading the real release binary
// into npm/bin (which the pre-fix code did).
https.get = () => {
  throw new Error("network disabled in tests");
};
const binExistedBefore = fs.existsSync(binaryPath());
after(() => {
  if (!binExistedBefore) assert.ok(!fs.existsSync(binaryPath()), "tests must not write into npm/bin");
});

const GOOD = Buffer.from("#!/bin/sh\necho genuine-binary\n");
const BAD = Buffer.from("#!/bin/sh\necho tampered-binary\n");
const sha256 = (buf) => crypto.createHash("sha256").update(buf).digest("hex");

function tmpDir() {
  return fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "gsf-verify-")));
}

function writeChecksums(dir, table) {
  const p = path.join(dir, "checksums.json");
  fs.writeFileSync(p, JSON.stringify(table));
  return p;
}

// Serve `body` (or run a custom handler) for every request. download() builds
// the real GitHub URL; the injected fetch routes it to the local server by path.
async function serve(bodyOrHandler) {
  const requests = [];
  const server = http.createServer((req, res) => {
    requests.push(req.url);
    if (typeof bodyOrHandler === "function") {
      bodyOrHandler(req, res);
      return;
    }
    res.writeHead(200, { "Content-Type": "application/octet-stream" });
    res.end(bodyOrHandler);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const fetch = (url) =>
    new Promise((resolve, reject) => {
      http.get(base + new URL(url).pathname, resolve).on("error", reject);
    });
  return { fetch, requests, close: () => new Promise((resolve) => server.close(resolve)) };
}

function withoutGraphifyBin(fn) {
  return async () => {
    const prev = process.env.GRAPHIFY_BIN;
    delete process.env.GRAPHIFY_BIN;
    try {
      await fn();
    } finally {
      if (prev !== undefined) process.env.GRAPHIFY_BIN = prev;
    }
  };
}

test("download installs an asset whose sha256 matches checksums.json", async () => {
  const dir = tmpDir();
  const dest = path.join(dir, "graphify-sf-bin");
  const checksumsPath = writeChecksums(dir, { [assetName()]: sha256(GOOD) });
  const srv = await serve(GOOD);
  try {
    await download({ dest, checksumsPath, fetch: srv.fetch });
  } finally {
    await srv.close();
  }
  assert.deepStrictEqual(fs.readFileSync(dest), GOOD);
  assert.deepStrictEqual(srv.requests, [`/raykuonz/graphify-sf/releases/download/v${require("../package.json").version}/${assetName()}`]);
  if (process.platform !== "win32") assert.ok(fs.statSync(dest).mode & 0o100, "installed binary is executable");
});

test("download rejects a tampered asset and leaves nothing behind", async () => {
  const dir = tmpDir();
  const dest = path.join(dir, "graphify-sf-bin");
  const checksumsPath = writeChecksums(dir, { [assetName()]: sha256(GOOD) });
  const srv = await serve(BAD);
  try {
    await assert.rejects(download({ dest, checksumsPath, fetch: srv.fetch }), /sha256 mismatch/);
  } finally {
    await srv.close();
  }
  assert.ok(!fs.existsSync(dest), "tampered binary must not be installed");
  assert.deepStrictEqual(fs.readdirSync(dir), ["checksums.json"], "no .tmp left behind");
});

test("download refuses without fetching when checksums.json has no entry for the asset", async () => {
  const dir = tmpDir();
  const dest = path.join(dir, "graphify-sf-bin");
  const checksumsPath = writeChecksums(dir, { "graphify-sf-other-platform": sha256(GOOD) });
  const srv = await serve(GOOD);
  try {
    await assert.rejects(download({ dest, checksumsPath, fetch: srv.fetch }), /no published sha256/);
  } finally {
    await srv.close();
  }
  assert.strictEqual(srv.requests.length, 0, "must fail before any network request");
  assert.ok(!fs.existsSync(dest));
});

test("download refuses when checksums.json is absent", async () => {
  const dir = tmpDir();
  const dest = path.join(dir, "graphify-sf-bin");
  const srv = await serve(GOOD);
  try {
    await assert.rejects(
      download({ dest, checksumsPath: path.join(dir, "missing.json"), fetch: srv.fetch }),
      /no published sha256/
    );
  } finally {
    await srv.close();
  }
  assert.strictEqual(srv.requests.length, 0);
});

test("verifiedCachedBinary accepts only a cached binary whose hash matches", () => {
  const dir = tmpDir();
  const dest = path.join(dir, "graphify-sf-bin");
  const checksumsPath = writeChecksums(dir, { [assetName()]: sha256(GOOD) });

  assert.strictEqual(verifiedCachedBinary(dest, checksumsPath), false, "missing file");
  fs.writeFileSync(dest, GOOD);
  assert.strictEqual(verifiedCachedBinary(dest, checksumsPath), true);
  fs.writeFileSync(dest, BAD);
  assert.strictEqual(verifiedCachedBinary(dest, checksumsPath), false, "tampered file");
  fs.writeFileSync(dest, GOOD);
  assert.strictEqual(verifiedCachedBinary(dest, path.join(dir, "missing.json")), false, "no checksums");
});

test(
  "ensureBinary replaces a tampered cached binary with a verified download",
  withoutGraphifyBin(async () => {
    const dir = tmpDir();
    const dest = path.join(dir, "graphify-sf-bin");
    const checksumsPath = writeChecksums(dir, { [assetName()]: sha256(GOOD) });
    fs.writeFileSync(dest, BAD);
    const srv = await serve(GOOD);
    let resolved;
    try {
      resolved = await ensureBinary({ dest, checksumsPath, fetch: srv.fetch });
    } finally {
      await srv.close();
    }
    assert.strictEqual(resolved, dest);
    assert.deepStrictEqual(fs.readFileSync(dest), GOOD);
  })
);

test(
  "ensureBinary refuses to return a binary when the only download is tampered",
  withoutGraphifyBin(async () => {
    const dir = tmpDir();
    const dest = path.join(dir, "graphify-sf-bin");
    const checksumsPath = writeChecksums(dir, { [assetName()]: sha256(GOOD) });
    fs.writeFileSync(dest, BAD);
    const srv = await serve(BAD);
    try {
      await assert.rejects(ensureBinary({ dest, checksumsPath, fetch: srv.fetch }), /sha256 mismatch/);
    } finally {
      await srv.close();
    }
    assert.ok(!fs.existsSync(dest), "the tampered cached binary is removed, not executed");
  })
);

test("download rejects a truncated response and leaves nothing behind", async () => {
  const dir = tmpDir();
  const dest = path.join(dir, "graphify-sf-bin");
  const checksumsPath = writeChecksums(dir, { [assetName()]: sha256(GOOD) });
  const srv = await serve((req, res) => {
    // Promise more bytes than are sent, then drop the connection.
    res.writeHead(200, { "Content-Length": String(GOOD.length * 4) });
    res.write(GOOD.subarray(0, 8));
    setImmediate(() => res.socket.destroy());
  });
  try {
    await assert.rejects(download({ dest, checksumsPath, fetch: srv.fetch }));
  } finally {
    await srv.close();
  }
  assert.ok(!fs.existsSync(dest));
  assert.deepStrictEqual(fs.readdirSync(dir), ["checksums.json"], "no temp file left behind");
});

test("download rejects an uppercase or malformed checksums entry", async () => {
  for (const content of [
    JSON.stringify({ [assetName()]: sha256(GOOD).toUpperCase() }),
    JSON.stringify({ [assetName()]: sha256(GOOD).slice(1) }),
    "{ not json",
    JSON.stringify([sha256(GOOD)]),
  ]) {
    const dir = tmpDir();
    const checksumsPath = path.join(dir, "checksums.json");
    fs.writeFileSync(checksumsPath, content);
    await assert.rejects(
      download({ dest: path.join(dir, "b"), checksumsPath, fetch: () => assert.fail("must not fetch") }),
      /no published sha256/,
      `checksums content: ${content}`
    );
  }
});

test("concurrent downloads to one dest never install a tampered binary", async () => {
  const dir = tmpDir();
  const dest = path.join(dir, "graphify-sf-bin");
  const checksumsPath = writeChecksums(dir, { [assetName()]: sha256(GOOD) });
  const good = await serve(GOOD);
  const bad = await serve(BAD);
  let results;
  try {
    results = await Promise.allSettled([
      download({ dest, checksumsPath, fetch: good.fetch }),
      download({ dest, checksumsPath, fetch: bad.fetch }),
      download({ dest, checksumsPath, fetch: good.fetch }),
      download({ dest, checksumsPath, fetch: bad.fetch }),
    ]);
  } finally {
    await good.close();
    await bad.close();
  }
  assert.deepStrictEqual(
    results.map((r) => r.status),
    ["fulfilled", "rejected", "fulfilled", "rejected"]
  );
  assert.deepStrictEqual(fs.readFileSync(dest), GOOD);
  assert.deepStrictEqual(fs.readdirSync(dir).sort(), ["checksums.json", "graphify-sf-bin"], "no temp files left");
});

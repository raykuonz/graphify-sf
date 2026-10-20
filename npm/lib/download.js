"use strict";

const crypto = require("crypto");
const https = require("https");
const fs = require("fs");
const path = require("path");

const PKG = require("../package.json");
const VERSION = PKG.version;

const SUPPORTED = {
  linux: ["x64", "arm64"],
  darwin: ["x64", "arm64"],
  win32: ["x64"],
};

function assetName() {
  const plat = process.platform;
  const arch = process.arch;

  const supported = SUPPORTED[plat];
  if (!supported) {
    throw new Error(
      `graphify-sf: unsupported platform "${plat}". ` +
        `Supported: ${Object.keys(SUPPORTED).join(", ")}. ` +
        `Remediation: install via pip/pipx instead: pipx install graphify-sf`
    );
  }
  if (!supported.includes(arch)) {
    throw new Error(
      `graphify-sf: unsupported arch "${arch}" on ${plat}. ` +
        `Supported archs for ${plat}: ${supported.join(", ")}. ` +
        `Remediation: install via pip/pipx instead: pipx install graphify-sf`
    );
  }

  const ext = plat === "win32" ? ".exe" : "";
  return `graphify-sf-${plat}-${arch}${ext}`;
}

function binDir() {
  return path.join(__dirname, "..", "bin");
}

function binaryPath() {
  const ext = process.platform === "win32" ? ".exe" : "";
  return path.join(binDir(), `graphify-sf-bin${ext}`);
}

function downloadUrl(asset) {
  return `https://github.com/raykuonz/graphify-sf/releases/download/v${VERSION}/${asset}`;
}

function checksumsPath() {
  return path.join(__dirname, "..", "checksums.json");
}

// sha256 the release workflow recorded for `asset`. checksums.json is written
// at publish time and ships inside the npm tarball, which lockfiles pin by
// integrity; GitHub release assets can be replaced under an existing tag, so a
// downloaded binary is trusted only if it matches. Throws when there is no
// usable entry (e.g. a source checkout), so callers fail closed.
function expectedSha256(asset, file) {
  let table = null;
  try {
    table = JSON.parse(fs.readFileSync(file || checksumsPath(), "utf8"));
  } catch {
    /* missing or unreadable: handled below */
  }
  const digest = table && table[asset];
  if (typeof digest !== "string" || !/^[0-9a-f]{64}$/.test(digest)) {
    throw new Error(
      `graphify-sf: no published sha256 for ${asset} (checksums.json missing or incomplete); ` +
        `refusing to download an unverifiable binary. ` +
        `Remediation: install via pip/pipx instead: pipx install graphify-sf, ` +
        `or point GRAPHIFY_BIN at an existing binary`
    );
  }
  return digest;
}

function sha256File(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

// True only if `dest` exists and matches the published sha256 for this platform.
function verifiedCachedBinary(dest, file) {
  if (!fs.existsSync(dest)) return false;
  try {
    return sha256File(dest) === expectedSha256(assetName(), file);
  } catch {
    return false;
  }
}

function fetchFollow(url, redirects) {
  if (redirects === undefined) redirects = 5;
  return new Promise((resolve, reject) => {
    https
      .get(url, { headers: { "User-Agent": "graphify-sf-npm-installer" } }, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          if (redirects === 0) {
            reject(new Error(`graphify-sf: too many redirects downloading ${url}`));
            return;
          }
          resolve(fetchFollow(res.headers.location, redirects - 1));
          return;
        }
        if (res.statusCode !== 200) {
          reject(
            new Error(
              `graphify-sf: download failed with HTTP ${res.statusCode} from ${url}. ` +
                `Remediation: install via pip/pipx instead: pipx install graphify-sf`
            )
          );
          return;
        }
        resolve(res);
      })
      .on("error", reject);
  });
}

// Download this platform's binary from GitHub Releases, verifying its sha256
// against checksums.json before it is renamed into place. `opts` (dest,
// checksumsPath, fetch) exists for tests; production callers pass nothing.
async function download(opts) {
  const o = opts || {};
  const asset = assetName();
  const expected = expectedSha256(asset, o.checksumsPath); // fails before any network request
  const url = downloadUrl(asset);
  const dest = o.dest || binaryPath();
  const fetch = o.fetch || fetchFollow;

  fs.mkdirSync(path.dirname(dest), { recursive: true });

  process.stdout.write(`graphify-sf: downloading ${asset} from ${url}\n`);

  const res = await fetch(url);

  await new Promise((resolve, reject) => {
    const tmp = dest + ".tmp";
    const hash = crypto.createHash("sha256");
    const out = fs.createWriteStream(tmp);
    const fail = (e) => {
      fs.rmSync(tmp, { force: true });
      reject(e);
    };
    res.on("data", (chunk) => hash.update(chunk));
    res.pipe(out);
    out.on("finish", () => {
      out.close(() => {
        const actual = hash.digest("hex");
        if (actual !== expected) {
          fail(
            new Error(
              `graphify-sf: sha256 mismatch for ${asset} from ${url} ` +
                `(expected ${expected}, got ${actual}); refusing to install it. ` +
                `Remediation: install via pip/pipx instead: pipx install graphify-sf`
            )
          );
          return;
        }
        try {
          fs.renameSync(tmp, dest);
          resolve();
        } catch (e) {
          fail(e);
        }
      });
    });
    out.on("error", fail);
    res.on("error", fail);
  });

  if (process.platform !== "win32") {
    fs.chmodSync(dest, 0o755);
  }

  process.stdout.write(`graphify-sf: installed to ${dest}\n`);
}

// Resolve a user-supplied binary path from the GRAPHIFY_BIN environment
// variable. This is the highest-priority resolution and is the documented
// escape hatch for locked-down networks where the GitHub download is blocked.
// Returns the path if it points at an existing file, otherwise null.
function envBinary() {
  const p = process.env.GRAPHIFY_BIN;
  if (p && fs.existsSync(p)) {
    return p;
  }
  return null;
}

// Name of the platform-specific scoped subpackage that ships the prebuilt
// binary for the current platform/arch, e.g. "@graphify-sf/cli-linux-x64".
// Returns null on unsupported platforms.
function subpackageName() {
  const plat = process.platform;
  const arch = process.arch;
  const supported = SUPPORTED[plat];
  if (!supported || !supported.includes(arch)) {
    return null;
  }
  return `@graphify-sf/cli-${plat}-${arch}`;
}

// Resolve the binary from an installed platform subpackage (the 0.3.9 happy
// path — the binary arrives with `npm install` via optionalDependencies, no
// network). Returns the absolute path, or null if the subpackage is not
// installed (unsupported platform, --no-optional, or a registry mirror that
// does not carry the scoped subpackages).
function subpackageBinary() {
  const name = subpackageName();
  if (!name) return null;
  const binName = process.platform === "win32" ? "graphify-sf.exe" : "graphify-sf";

  // Build a robust set of resolution roots. In a normal install the subpackage
  // is a peer in the consumer's node_modules and resolves from this module's
  // own location; but with non-hoisted / nested layouts (or when invoked from a
  // different cwd, e.g. tests) it may live elsewhere. Searching from this
  // module, the package root, and the current working directory covers npm,
  // pnpm and yarn layouts.
  const searchPaths = [__dirname, path.join(__dirname, ".."), process.cwd()];

  let resolved = null;
  try {
    resolved = require.resolve(`${name}/${binName}`, { paths: searchPaths });
  } catch {
    // Subpackage not installed — fall through to other resolution strategies.
    return null;
  }

  if (resolved && fs.existsSync(resolved)) {
    // Defensive: npm tarballs preserve mode, but ensure executable on Unix.
    if (process.platform !== "win32") {
      try {
        fs.accessSync(resolved, fs.constants.X_OK);
      } catch {
        try {
          fs.chmodSync(resolved, 0o755);
        } catch {
          /* best-effort; resolution still returned below */
        }
      }
    }
    return resolved;
  }
  return null;
}

async function ensureBinary(opts) {
  const o = opts || {};

  // 1. Explicit override always wins.
  const fromEnv = envBinary();
  if (fromEnv) {
    return fromEnv;
  }

  // 2. Prebuilt binary shipped in the platform subpackage (0.3.9 happy path,
  //    no network).
  const fromSubpkg = subpackageBinary();
  if (fromSubpkg) {
    return fromSubpkg;
  }

  // 3. A binary an earlier run downloaded into bin/, but only while it still
  //    matches the published sha256; anything else is discarded.
  const dest = o.dest || binaryPath();
  if (verifiedCachedBinary(dest, o.checksumsPath)) {
    return dest;
  }
  fs.rmSync(dest, { force: true });

  // 4. Last resort: lazily download (and verify) from GitHub Releases.
  await download(o);
  return dest;
}

module.exports = {
  assetName,
  binaryPath,
  binDir,
  download,
  ensureBinary,
  envBinary,
  expectedSha256,
  subpackageName,
  subpackageBinary,
  verifiedCachedBinary,
};

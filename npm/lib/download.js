"use strict";

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

async function download() {
  const asset = assetName();
  const url = downloadUrl(asset);
  const dest = binaryPath();

  fs.mkdirSync(binDir(), { recursive: true });

  process.stdout.write(`graphify-sf: downloading ${asset} from ${url}\n`);

  const res = await fetchFollow(url);

  await new Promise((resolve, reject) => {
    const tmp = dest + ".tmp";
    const out = fs.createWriteStream(tmp);
    res.pipe(out);
    out.on("finish", () => {
      out.close(() => {
        try {
          fs.renameSync(tmp, dest);
          resolve();
        } catch (e) {
          reject(e);
        }
      });
    });
    out.on("error", (e) => {
      fs.unlink(tmp, () => {});
      reject(e);
    });
    res.on("error", (e) => {
      fs.unlink(tmp, () => {});
      reject(e);
    });
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

async function ensureBinary() {
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

  // 3. Already-downloaded binary in the package's bin/ dir (legacy cache).
  const dest = binaryPath();
  if (fs.existsSync(dest)) {
    return dest;
  }

  // 4. Last resort: lazily download from GitHub Releases on first use.
  await download();
  return dest;
}

module.exports = {
  assetName,
  binaryPath,
  binDir,
  download,
  ensureBinary,
  envBinary,
  subpackageName,
  subpackageBinary,
};

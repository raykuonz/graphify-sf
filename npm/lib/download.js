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

async function ensureBinary() {
  const dest = binaryPath();
  if (!fs.existsSync(dest)) {
    await download();
  }
  return dest;
}

module.exports = { assetName, binaryPath, binDir, download, ensureBinary };

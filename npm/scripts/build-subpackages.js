"use strict";

// Scaffold the platform-specific scoped subpackages that ship the prebuilt
// graphify-sf binary (the 0.3.9 "binary in npm" distribution channel).
//
// For each supported platform/arch it creates:
//   npm/platforms/<plat>-<arch>/
//     package.json   (name @graphify-sf/cli-<plat>-<arch>, os/cpu, files)
//     graphify-sf     (or graphify-sf.exe on win32) -- the renamed binary, 0755
//
// Usage:
//   node npm/scripts/build-subpackages.js --version 0.3.9 --bin-dir <dir>
//
// <dir> must contain the release assets named exactly as release-binaries.yml
// produces them: graphify-sf-<plat>-<arch>  (and graphify-sf-win32-x64.exe).
// Targets whose asset is missing are skipped with a warning (so the script can
// run in a partial matrix without crashing), unless --strict is passed.
//
// This script is deterministic and has zero dependencies. It is invoked by the
// release workflow and can be run locally to validate packing.

const fs = require("fs");
const path = require("path");

const TARGETS = [
  { plat: "linux", arch: "x64", asset: "graphify-sf-linux-x64", bin: "graphify-sf" },
  { plat: "linux", arch: "arm64", asset: "graphify-sf-linux-arm64", bin: "graphify-sf" },
  { plat: "darwin", arch: "x64", asset: "graphify-sf-darwin-x64", bin: "graphify-sf" },
  { plat: "darwin", arch: "arm64", asset: "graphify-sf-darwin-arm64", bin: "graphify-sf" },
  { plat: "win32", arch: "x64", asset: "graphify-sf-win32-x64.exe", bin: "graphify-sf.exe" },
];

function parseArgs(argv) {
  const out = { version: null, binDir: null, outDir: null, strict: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--version") out.version = argv[++i];
    else if (a === "--bin-dir") out.binDir = argv[++i];
    else if (a === "--out-dir") out.outDir = argv[++i];
    else if (a === "--strict") out.strict = true;
  }
  return out;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.version) {
    process.stderr.write("build-subpackages: --version is required\n");
    process.exit(2);
  }
  const binDir = args.binDir || ".";
  const outDir = args.outDir || path.join(__dirname, "..", "platforms");
  const repoUrl = "git+https://github.com/raykuonz/graphify-sf.git";

  const built = [];
  for (const t of TARGETS) {
    const src = path.join(binDir, t.asset);
    if (!fs.existsSync(src)) {
      const msg = `build-subpackages: missing asset ${src} for ${t.plat}-${t.arch}\n`;
      if (args.strict) {
        process.stderr.write(msg);
        process.exit(1);
      }
      process.stderr.write(`WARN: ${msg}`);
      continue;
    }

    const pkgName = `@graphify-sf/cli-${t.plat}-${t.arch}`;
    const dir = path.join(outDir, `${t.plat}-${t.arch}`);
    fs.mkdirSync(dir, { recursive: true });

    const pkg = {
      name: pkgName,
      version: args.version,
      description: `graphify-sf prebuilt CLI binary for ${t.plat}-${t.arch}`,
      os: [t.plat],
      cpu: [t.arch],
      files: [t.bin],
      license: "MIT",
      repository: { type: "git", url: repoUrl },
      homepage: "https://github.com/raykuonz/graphify-sf#readme",
    };
    fs.writeFileSync(path.join(dir, "package.json"), JSON.stringify(pkg, null, 2) + "\n");

    const dest = path.join(dir, t.bin);
    fs.copyFileSync(src, dest);
    if (t.plat !== "win32") {
      fs.chmodSync(dest, 0o755);
    }

    built.push({ name: pkgName, dir });
    process.stdout.write(`built ${pkgName} -> ${dir}\n`);
  }

  // Emit the list of built package dirs for the workflow to publish, in
  // dependency order (subpackages before the main package).
  process.stdout.write(`\nBUILT_DIRS=${built.map((b) => b.dir).join(":")}\n`);
}

main();

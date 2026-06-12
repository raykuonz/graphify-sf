"use strict";

const { spawn } = require("child_process");
const path = require("path");
const { ensureBinary, binaryPath } = require("./lib/download");

/**
 * Run graphify-sf programmatically.
 *
 * @param {string} sfdxPath - Path to the SFDX project root.
 * @param {object} [options]
 * @param {string} [options.outDir] - Output directory (default: "graphify-sf-out").
 * @param {string[]} [options.extraArgs] - Additional CLI args forwarded verbatim.
 * @param {"inherit"|"pipe"|"ignore"} [options.stdio] - stdio mode for the child process (default: "inherit").
 * @returns {Promise<{code: number, graphJsonPath: string}>}
 */
async function runGraphify(sfdxPath, options) {
  if (!sfdxPath) throw new Error("graphify-sf: sfdxPath is required");

  const opts = options || {};
  const outDir = opts.outDir || "graphify-sf-out";
  const extraArgs = opts.extraArgs || [];
  const stdioMode = opts.stdio || "inherit";

  const bin = await ensureBinary();
  const args = [sfdxPath, "--out", outDir, "--no-viz", ...extraArgs];
  const graphJsonPath = path.join(outDir, "graph.json");

  return new Promise((resolve, reject) => {
    const child = spawn(bin, args, { stdio: stdioMode });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve({ code, graphJsonPath });
      } else {
        reject(
          new Error(
            `graphify-sf exited with code ${code}. ` +
              `Command: ${bin} ${args.join(" ")}`
          )
        );
      }
    });
  });
}

module.exports = { runGraphify, ensureBinary, binaryPath };

#!/usr/bin/env node
"use strict";

const { spawn } = require("child_process");
const { ensureBinary } = require("../lib/download");

ensureBinary()
  .then((bin) => {
    const child = spawn(bin, process.argv.slice(2), { stdio: "inherit" });
    child.on("error", (err) => {
      process.stderr.write(`graphify-sf: failed to start binary: ${err.message}\n`);
      process.exit(1);
    });
    child.on("close", (code) => {
      process.exit(code == null ? 1 : code);
    });
  })
  .catch((err) => {
    process.stderr.write(`graphify-sf: ${err.message}\n`);
    process.exit(1);
  });

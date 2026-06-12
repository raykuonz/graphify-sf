"use strict";

const { download } = require("./lib/download");

download().catch((err) => {
  process.stderr.write(`graphify-sf postinstall failed: ${err.message}\n`);
  process.exit(1);
});

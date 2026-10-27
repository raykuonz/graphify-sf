#!/usr/bin/env bash
# Write a hash-locked requirements file for the binary build, from uv.lock.
#
#   export-binary-requirements.sh [OUT]     (default: reqs-binary.txt, repo root)
#
# keeps every platform's wheel hashes and environment markers, so the one file
# installs on macOS, Windows and manylinux alike under `pip install --require-hashes`.
# Needs uv on the host; the manylinux container never installs uv, it receives this file
# through the checkout copy. The project itself is excluded (installed separately by
# install-binary-deps.sh); its runtime dependencies and the `binary` group are in. The docs extra is left out on purpose:
# pyinstaller-build.sh excludes pypdf/docx/openpyxl from the bundle, so installing them would
# only add (lxml's) native wheels to the supply chain.
set -euo pipefail

out="${1:-reqs-binary.txt}"
uv export --frozen --group binary --no-emit-project \
  --format requirements-txt --output-file "$out"
echo "wrote $out ($(grep -c '^[A-Za-z0-9]' "$out") requirements)"

#!/usr/bin/env bash
# Install the binary-build dependencies from the hash-locked file, then the project.
#
#   install-binary-deps.sh <python> [REQS]  (REQS default: reqs-binary.txt, from
#                                            export-binary-requirements.sh)
#
# Every third-party package is verified against a hash (--require-hashes). The project is
# installed with --no-build-isolation so the build backend is the hash-pinned setuptools
# from the same file, not whatever pip would fetch into an isolated environment.
# pip itself is the interpreter's bundled version (not upgraded).
set -euo pipefail

PY="${1:?usage: install-binary-deps.sh <python> [requirements-file]}"
reqs="${2:-reqs-binary.txt}"

"$PY" -m pip install --require-hashes --no-deps -r "$reqs"
"$PY" -m pip install --no-deps --no-build-isolation .

#!/usr/bin/env bash
# Run a built Linux binary on the distros it must support, natively on the host
# arch: the glibc 2.28 floor (AlmaLinux 8), RHEL 9 family (2.34), Ubuntu 22.04
# (2.35) and Debian 12 / bookworm (2.36, sf-cockpit's node:22-bookworm-slim).
# Each run prints --version and builds a real graph from a fixture project.
#
# Usage (from the repo root): smoke-linux-binary.sh dist/graphify-sf
set -euo pipefail

bin="$(cd "$(dirname "${1:?usage: smoke-linux-binary.sh <binary>}")" && pwd)/$(basename "$1")"
fixture="$PWD/tests/fixtures/simple_project"

for image in almalinux:8 almalinux:9 ubuntu:22.04 debian:bookworm-slim; do
  echo "=== ${image}"
  docker run --rm \
    -v "${bin}:/usr/local/bin/graphify-sf:ro" \
    -v "${fixture}:/proj:ro" \
    "${image}" \
    sh -ec '
      ldd --version 2>&1 | head -1
      graphify-sf --version
      graphify-sf /proj --out /tmp/out --no-viz > /dev/null
      test -s /tmp/out/graph.json
      echo "graph.json OK"
    '
done

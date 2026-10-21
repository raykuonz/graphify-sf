#!/usr/bin/env bash
# Run a built Linux binary on every distro family the README lists as supported,
# natively on the host arch: AlmaLinux 8 (glibc 2.28, the floor), Debian 11
# (2.31), Ubuntu 20.04 (2.31), AlmaLinux 9 / RHEL 9 (2.34), Amazon Linux 2023
# (2.34), Ubuntu 22.04 (2.35) and Debian 12 (2.36, sf-cockpit's
# node:22-bookworm-slim).
# Each run prints --version and builds a real graph from a fixture project.
#
# Usage (from the repo root): smoke-linux-binary.sh dist/graphify-sf
set -euo pipefail

bin="$(cd "$(dirname "${1:?usage: smoke-linux-binary.sh <binary>}")" && pwd)/$(basename "$1")"
fixture="$PWD/tests/fixtures/simple_project"

for image in almalinux:8 debian:bullseye-slim ubuntu:20.04 almalinux:9 amazonlinux:2023 ubuntu:22.04 debian:bookworm-slim; do
  echo "=== ${image}"
  docker run --rm \
    -v "${bin}:/usr/local/bin/graphify-sf:ro" \
    -v "${fixture}:/proj:ro" \
    "${image}" \
    sh -ec '
      ldd --version 2>&1 | sed -n 1p
      graphify-sf --version
      graphify-sf /proj --out /tmp/out --no-viz > /dev/null
      test -s /tmp/out/graph.json
      echo "graph.json OK"
    '
done

# FIPS hosts (FedRAMP/GovCloud RHEL, Ubuntu Pro FIPS): RHEL's OpenSSL switches
# to FIPS mode when the kernel says so; OPENSSL_FORCE_FIPS_MODE forces the same
# path (the build log shows whether the bundled libcrypto honours it). Hashing
# (sha256 in the cache/manifest) must keep working.
echo "=== almalinux:9 with OPENSSL_FORCE_FIPS_MODE=1"
docker run --rm \
  -e OPENSSL_FORCE_FIPS_MODE=1 \
  -v "${bin}:/usr/local/bin/graphify-sf:ro" \
  -v "${fixture}:/proj:ro" \
  almalinux:9 \
  sh -ec '
    graphify-sf --version
    graphify-sf /proj --out /tmp/out --no-viz > /dev/null
    test -s /tmp/out/graph.json
    echo "graph.json OK (FIPS mode)"
  '

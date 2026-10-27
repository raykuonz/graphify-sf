#!/usr/bin/env bash
# Build the Linux binary inside manylinux_2_28 (AlmaLinux 8, glibc 2.28), so it
# runs on any glibc >= 2.28 distro: RHEL 8/9, Debian 11/12, Ubuntu 20.04+,
# Amazon Linux 2023. PyInstaller bundles libpython, libcrypto, etc. from the
# build machine; building directly on the runner (Ubuntu 24.04, glibc 2.39)
# shipped libraries that required GLIBC_2.38 (sf-cockpit #38).
#
# The build itself is manylinux-build-inner.sh; it ends with a glibc gate that
# fails if anything bundled needs a newer glibc than 2.28. The checkout is
# mounted read-only; only the binary comes back out, into dist/.
#
# The base image is pinned by digest in .github/docker/manylinux-<arch>/Dockerfile (Dependabot
# keeps it current); this script runs exactly the reference on that file's FROM line.
# Build dependencies come from reqs-binary.txt (hash-locked, written on the host by
# export-binary-requirements.sh, which needs uv); it travels into the container with the
# checkout, and uv is never installed inside the container.
#
# Usage (from the repo root, on an x86_64 or aarch64 host with docker):
#   export-binary-requirements.sh && build-linux-binary.sh        -> dist/graphify-sf
set -euo pipefail

case "$(uname -m)" in
  x86_64) arch="x86_64" ;;
  aarch64 | arm64) arch="aarch64" ;;
  *) echo "unsupported host arch: $(uname -m)" >&2; exit 1 ;;
esac

dockerfile=".github/docker/manylinux-${arch}/Dockerfile"
image="$(awk '$1 == "FROM" { print $2; exit }' "$dockerfile")"
case "$image" in
  *@sha256:????????????????????????????????????????????????????????????????) ;;
  *) echo "$dockerfile: FROM must be pinned by digest, got: ${image:-<none>}" >&2; exit 1 ;;
esac
[ -f reqs-binary.txt ] || { echo "reqs-binary.txt missing: run .github/scripts/export-binary-requirements.sh first" >&2; exit 1; }

docker pull -q "$image" > /dev/null
echo "build image: $image"

mkdir -p dist
docker run --rm --init \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -v "$PWD:/src:ro" \
  -v "$PWD/dist:/out" \
  "$image" \
  bash /src/.github/scripts/manylinux-build-inner.sh

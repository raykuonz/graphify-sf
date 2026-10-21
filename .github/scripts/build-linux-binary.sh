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
# Usage (from the repo root, on an x86_64 or aarch64 host with docker):
#   build-linux-binary.sh        -> dist/graphify-sf
set -euo pipefail

case "$(uname -m)" in
  x86_64) image="quay.io/pypa/manylinux_2_28_x86_64" ;;
  aarch64 | arm64) image="quay.io/pypa/manylinux_2_28_aarch64" ;;
  *) echo "unsupported host arch: $(uname -m)" >&2; exit 1 ;;
esac

docker pull -q "$image"
echo "build image: $(docker image inspect --format '{{index .RepoDigests 0}}' "$image")"

mkdir -p dist
docker run --rm --init \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -v "$PWD:/src:ro" \
  -v "$PWD/dist:/out" \
  "$image" \
  bash /src/.github/scripts/manylinux-build-inner.sh

#!/usr/bin/env bash
# Build the Linux binary inside manylinux_2_28 (AlmaLinux 8, glibc 2.28), so it
# runs on any glibc >= 2.28 distro: RHEL 8/9, Debian 11/12, Ubuntu 20.04+,
# Amazon Linux 2023. PyInstaller bundles libpython, libcrypto, etc. from the
# build machine; building directly on the runner (Ubuntu 24.04, glibc 2.39)
# shipped libraries that required GLIBC_2.38 (sf-cockpit #38).
#
# Python is AlmaLinux 8's python3.12 package: security-maintained and built
# with a shared libpython, which PyInstaller needs. The glibc gate fails the
# build if anything bundled needs a newer glibc than the image provides.
#
# Usage (from the repo root, on an x86_64 or aarch64 host with docker):
#   build-linux-binary.sh        -> dist/graphify-sf
set -euo pipefail

case "$(uname -m)" in
  x86_64) image="quay.io/pypa/manylinux_2_28_x86_64" ;;
  aarch64 | arm64) image="quay.io/pypa/manylinux_2_28_aarch64" ;;
  *) echo "unsupported host arch: $(uname -m)" >&2; exit 1 ;;
esac

docker run --rm \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -v "$PWD:/src" -w /src \
  "$image" \
  bash -euo pipefail -c '
    trap "chown -R \"\$HOST_UID:\$HOST_GID\" /src" EXIT
    ldd --version 2>&1 | sed -n 1p   # sed reads all input: no SIGPIPE under pipefail
    dnf install -y -q python3.12 python3.12-devel python3.12-pip >/dev/null
    # Absolute path: a bare python3.12 resolves to manylinux'"'"'s own static
    # /opt/python build, which PyInstaller rejects (no shared libpython).
    py=/usr/bin/python3.12
    "$py" -c "import sys, sysconfig; sys.exit(0 if sysconfig.get_config_var(\"Py_ENABLE_SHARED\") else \"python lacks a shared libpython\")"
    "$py" --version
    "$py" -m venv /tmp/venv
    /tmp/venv/bin/python -m pip install -q --upgrade pip
    /tmp/venv/bin/python -m pip install -q ".[docs]" pyinstaller pyelftools
    bash .github/scripts/pyinstaller-build.sh /tmp/venv/bin/python
    /tmp/venv/bin/python .github/scripts/check-glibc.py dist/graphify-sf --max 2.28
  '

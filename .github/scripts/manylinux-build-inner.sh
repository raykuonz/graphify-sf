#!/usr/bin/env bash
# Runs INSIDE quay.io/pypa/manylinux_2_28_* (AlmaLinux 8, glibc 2.28); started by
# build-linux-binary.sh. The checkout is mounted read-only at /src and copied
# to /build, and only the finished binary is copied out to /out, so nothing the
# build installs can modify the host workspace.
set -euo pipefail

ldd --version 2>&1 | sed -n 1p # sed reads all input: no SIGPIPE under pipefail

# AlmaLinux's python3.12 is security-maintained and has a shared libpython,
# which PyInstaller needs. A full upgrade means every library PyInstaller
# bundles (openssl, expat, zlib, libffi, xz, bzip2, ncurses/readline, ...)
# ships at its latest EL8 errata rather than the image snapshot.
# AlmaLinux mirrors occasionally answer with an empty repomd.xml; retry instead of failing the build.
retry() {
  local n
  for n in 1 2 3; do
    "$@" && return 0
    echo "retry $n/3 after failure: $*" >&2
    sleep $((n * 15))
  done
  return 1
}
retry dnf upgrade -y -q > /dev/null
retry dnf install -y -q python3.12 python3.12-devel python3.12-pip > /dev/null
rpm -q python3.12 openssl-libs expat zlib libffi xz-libs bzip2-libs readline || true # report only

# Absolute path: a bare python3.12 resolves to manylinux's own static
# /opt/python build, which PyInstaller rejects (no shared libpython).
py=/usr/bin/python3.12
"$py" -c 'import sys, sysconfig; sys.exit(0 if sysconfig.get_config_var("Py_ENABLE_SHARED") else "python lacks a shared libpython")'
"$py" -c 'import ssl, pyexpat, sys; print(sys.version.split()[0], "|", ssl.OPENSSL_VERSION, "|", pyexpat.EXPAT_VERSION)'
# Positive control for the FIPS smoke run: does this libcrypto actually enter
# FIPS mode when forced? (Informational; the smoke test checks it still works.)
OPENSSL_FORCE_FIPS_MODE=1 "$py" -c 'import _hashlib; print("FIPS mode when forced:", bool(_hashlib.get_fips_mode()))' ||
  echo "FIPS mode when forced: check failed (informational)"

cp -a /src /build
cd /build
"$py" -m venv /tmp/venv
# Hash-locked install (reqs-binary.txt was exported on the host and came in with the checkout).
bash .github/scripts/install-binary-deps.sh /tmp/venv/bin/python
bash .github/scripts/pyinstaller-build.sh /tmp/venv/bin/python
/tmp/venv/bin/python .github/scripts/check-glibc.py dist/graphify-sf --max 2.28

cp dist/graphify-sf /out/graphify-sf
chown "${HOST_UID}:${HOST_GID}" /out/graphify-sf

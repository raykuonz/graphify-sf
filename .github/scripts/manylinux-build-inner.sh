#!/usr/bin/env bash
# Runs INSIDE quay.io/pypa/manylinux_2_28_* (AlmaLinux 8, glibc 2.28); started by
# build-linux-binary.sh. The checkout is mounted read-only at /src and copied
# to /build, and only the finished binary is copied out to /out, so nothing the
# build installs can modify the host workspace.
set -euo pipefail

ldd --version 2>&1 | sed -n 1p # sed reads all input: no SIGPIPE under pipefail

# AlmaLinux's python3.12 is security-maintained and has a shared libpython,
# which PyInstaller needs. Upgrade the libraries PyInstaller bundles so the
# latest errata ship, not the image snapshot.
dnf install -y -q python3.12 python3.12-devel python3.12-pip > /dev/null
dnf upgrade -y -q openssl-libs expat > /dev/null
rpm -q python3.12 openssl-libs expat

# Absolute path: a bare python3.12 resolves to manylinux's own static
# /opt/python build, which PyInstaller rejects (no shared libpython).
py=/usr/bin/python3.12
"$py" -c 'import sys, sysconfig; sys.exit(0 if sysconfig.get_config_var("Py_ENABLE_SHARED") else "python lacks a shared libpython")'
"$py" -c 'import ssl, pyexpat, sys; print(sys.version.split()[0], "|", ssl.OPENSSL_VERSION, "|", pyexpat.EXPAT_VERSION)'

cp -a /src /build
cd /build
"$py" -m venv /tmp/venv
/tmp/venv/bin/python -m pip install -q --upgrade pip
/tmp/venv/bin/python -m pip install -q ".[docs]" pyinstaller pyelftools
bash .github/scripts/pyinstaller-build.sh /tmp/venv/bin/python
/tmp/venv/bin/python .github/scripts/check-glibc.py dist/graphify-sf --max 2.28

cp dist/graphify-sf /out/graphify-sf
chown "${HOST_UID}:${HOST_GID}" /out/graphify-sf

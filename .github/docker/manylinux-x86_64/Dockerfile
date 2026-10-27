# Base image for the Linux release binary (see .github/scripts/build-linux-binary.sh, which
# reads the FROM line below and runs exactly that reference). The digest pins the image;
# Dependabot's docker ecosystem opens PRs that move it, and CI rebuilds the binary on them.
# Packages installed inside the container by manylinux-build-inner.sh (dnf upgrade) are
# deliberately NOT pinned: they bring the bundled libraries to the latest EL8 security errata.
FROM quay.io/pypa/manylinux_2_28_x86_64:latest@sha256:e0adf18521ad35192df733a6c62d35df7801957d24e0470238aacecfab2188a3

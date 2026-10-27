# Base image for the Linux release binary (see .github/scripts/build-linux-binary.sh, which
# reads the FROM line below and runs exactly that reference). The digest pins the image;
# Dependabot's docker ecosystem opens PRs that move it, and CI rebuilds the binary on them.
# Packages installed inside the container by manylinux-build-inner.sh (dnf upgrade) are
# deliberately NOT pinned: they bring the bundled libraries to the latest EL8 security errata.
FROM quay.io/pypa/manylinux_2_28_aarch64:latest@sha256:a3e02308c822fb6ce0d12248b0c941817ba5e1a1bc9e7bb5929f29c50eaa40a9

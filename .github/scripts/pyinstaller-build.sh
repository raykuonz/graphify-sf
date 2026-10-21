#!/usr/bin/env bash
# Build the one-file graphify-sf binary with PyInstaller (output: dist/graphify-sf
# or dist/graphify-sf.exe). Shared by every release leg and by CI so the bundle
# contents are defined in one place. Optional extras are installed for module
# discovery but kept out of the bundle.
#
# Usage (from the repo root): pyinstaller-build.sh <python-with-pyinstaller>
set -euo pipefail

PY="${1:?usage: pyinstaller-build.sh <python>}"

"$PY" -m PyInstaller \
  --noconfirm \
  --onefile \
  --name graphify-sf \
  --collect-submodules graphify_sf \
  --hidden-import graphify_sf.__main__ \
  --exclude-module matplotlib \
  --exclude-module neo4j \
  --exclude-module anthropic \
  --exclude-module openai \
  --exclude-module boto3 \
  --exclude-module mcp \
  --exclude-module watchdog \
  --exclude-module graspologic \
  --exclude-module graspologic_native \
  --exclude-module pypdf \
  --exclude-module docx \
  --exclude-module openpyxl \
  -c \
  graphify_sf/__main__.py

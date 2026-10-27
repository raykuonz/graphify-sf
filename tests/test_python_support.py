"""Supported-Python metadata stays consistent (3.11+)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_MINOR = 11


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_requires_python_floor():
    assert _pyproject()["project"]["requires-python"] == f">=3.{MIN_MINOR}"


def test_classifiers_list_only_supported_pythons():
    versions = [
        c.rsplit("::", 1)[1].strip()
        for c in _pyproject()["project"]["classifiers"]
        if c.startswith("Programming Language :: Python :: 3.")
    ]
    assert versions, "no Python version classifiers found"
    assert all(int(v.split(".")[1]) >= MIN_MINOR for v in versions), versions


def test_ruff_targets_the_floor():
    assert _pyproject()["tool"]["ruff"]["target-version"] == f"py3{MIN_MINOR}"


def test_lockfile_has_no_pre_floor_resolution_fork():
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert f'requires-python = ">=3.{MIN_MINOR}"' in lock
    assert not re.search(rf"python_full_version\s*<\s*'3\.({MIN_MINOR - 1}|[0-9])'", lock)


def test_ci_matrices_and_docs_match_the_floor():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert '"3.10"' not in ci
    for doc in ("README.md", "CONTRIBUTING.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        assert "Python 3.10" not in text, doc
    template = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(encoding="utf-8")
    assert '"3.10"' not in template and '"3.14"' in template

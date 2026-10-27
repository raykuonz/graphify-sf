"""Every place a release version is written agrees, so a tag can't ship half-bumped.

Release-binaries stamps the npm packages from the tag and publish.yml builds the wheel from
pyproject.toml, so a missed bump would publish mismatched PyPI and npm versions.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def test_npm_package_and_platform_pins_match_pyproject():
    version = _pyproject_version()
    pkg = json.loads((ROOT / "npm" / "package.json").read_text(encoding="utf-8"))
    assert pkg["version"] == version
    pins = pkg["optionalDependencies"]
    assert sorted(pins) == sorted(
        f"@graphify-sf/cli-{t}" for t in ("linux-x64", "linux-arm64", "darwin-x64", "darwin-arm64", "win32-x64")
    )
    assert set(pins.values()) == {version}


def test_lockfile_records_the_project_version():
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    m = re.search(r'\[\[package\]\]\nname = "graphify-sf"\nversion = "([^"]+)"', lock)
    assert m, "graphify-sf entry not found in uv.lock"
    assert m.group(1) == _pyproject_version()


def test_changelog_has_a_section_and_link_for_the_current_version():
    version = _pyproject_version()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## \[{re.escape(version)}\] — \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M)
    assert re.search(rf"^\[{re.escape(version)}\]: https://github.com/raykuonz/graphify-sf/compare/", changelog, re.M)


def test_release_workflows_refuse_a_tag_that_differs_from_pyproject():
    publish = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert "Check the tag matches pyproject.toml" in publish
    assert "TAG: ${{ github.event.release.tag_name }}" in publish
    assert publish.index("Check the tag matches pyproject.toml") < publish.index("uv build")
    binaries = (ROOT / ".github" / "workflows" / "release-binaries.yml").read_text(encoding="utf-8")
    assert "tag version $TAG_VERSION != pyproject.toml version" in binaries
    assert binaries.index("tag version $TAG_VERSION") < binaries.index("Export hash-locked binary requirements")

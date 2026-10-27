"""Structure of release-binaries.yml: who may write to the release, who may mint OIDC tokens.

The build legs run third-party PyPI code, so they are read-only and hand their binaries over as
workflow artifacts; one job with no third-party code writes the release; the npm job has the
OIDC token but no release write access. These static checks keep that from regressing, because
the release path cannot be exercised on a pull request (use `dry_run=true` for the job graph).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github" / "workflows" / "release-binaries.yml").read_text(encoding="utf-8")
ASSETS = [
    "graphify-sf-linux-x64",
    "graphify-sf-linux-arm64",
    "graphify-sf-darwin-x64",
    "graphify-sf-darwin-arm64",
    "graphify-sf-win32-x64.exe",
]


def _jobs() -> dict[str, str]:
    body = WORKFLOW.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z][\w-]*):\n", body, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def _permissions(job: str) -> dict[str, str]:
    m = re.search(r"^    permissions:\n((?:      [\w-]+: \w+.*\n)+)", job, re.M)
    assert m, "job has no explicit permissions"
    return dict(re.findall(r"^      ([\w-]+): (\w+)", m.group(1), re.M))


def _steps(job: str) -> list[str]:
    return re.split(r"^      - ", job, flags=re.M)[1:]


def test_job_graph():
    jobs = _jobs()
    assert list(jobs) == ["resolve", "build-binaries", "attach-assets", "publish-npm"]
    assert re.search(r"^    needs: resolve$", jobs["build-binaries"], re.M)
    assert re.search(r"^    needs: \[resolve, build-binaries\]$", jobs["attach-assets"], re.M)
    assert re.search(r"^    needs: \[resolve, attach-assets\]$", jobs["publish-npm"], re.M)
    assert "always()" not in WORKFLOW, "a failed build leg must stop the release"


def test_permissions_are_least_privilege():
    jobs = _jobs()
    assert _permissions(jobs["resolve"]) == {"contents": "read"}
    assert _permissions(jobs["build-binaries"]) == {"contents": "read"}  # runs third-party build code
    assert _permissions(jobs["attach-assets"]) == {"contents": "write"}  # the only release writer; no OIDC
    npm = _permissions(jobs["publish-npm"])
    assert npm["id-token"] == "write" and npm["contents"] == "read"  # OIDC for npm, no release writes
    assert "\npermissions:\n  contents: read\n" in WORKFLOW  # workflow default is read-only


def test_attach_assets_runs_no_third_party_package_code():
    job = "\n".join(ln for ln in _jobs()["attach-assets"].splitlines() if not ln.lstrip().startswith("#"))
    for forbidden in ("actions/checkout", "setup-python", "setup-node", "setup-uv", "pip ", "npm ", "uv "):
        assert forbidden not in job, f"attach-assets must not use {forbidden!r}"
    uses = re.findall(r"uses:\s*(\S+)", job)
    assert uses and all(u.startswith("actions/") for u in uses), uses  # first-party, SHA-pinned (test_release_pins)


def test_artifact_names_are_the_release_asset_names():
    matrix = re.findall(r"asset-name: (\S+)", _jobs()["build-binaries"])
    assert sorted(matrix) == sorted(ASSETS)
    build = _jobs()["build-binaries"]
    upload = next(s for s in _steps(build) if "actions/upload-artifact" in s)
    assert "name: ${{ matrix.asset-name }}" in upload
    assert "path: ${{ matrix.asset-name }}" in upload
    assert "if-no-files-found: error" in upload
    attach = _jobs()["attach-assets"]
    assert "EXPECTED: " + " ".join(ASSETS) in attach, "attach-assets must allowlist exactly the five assets"
    scaffold = (ROOT / "npm" / "scripts" / "build-subpackages.js").read_text(encoding="utf-8")
    assert sorted(re.findall(r'asset: "([^"]+)"', scaffold)) == sorted(ASSETS)


def test_dry_run_writes_nothing():
    inputs = WORKFLOW.split("workflow_dispatch:", 1)[1].split("\npermissions:", 1)[0]
    assert re.search(r"dry_run:\n(?:\s+\w+:.*\n)*?\s+default: false", inputs)
    attach = _jobs()["attach-assets"]
    for step in _steps(attach):
        if "gh release upload" in step or "gh release download" in step:
            assert "needs.resolve.outputs.dry_run != 'true'" in step, step.splitlines()[0]
    npm = _jobs()["publish-npm"]
    assert "NPM_DRY: ${{ needs.resolve.outputs.dry_run == 'true' && '--dry-run' || '' }}" in npm
    publishes = re.findall(r"^\s*npm publish .*$", npm, re.M)
    assert len(publishes) == 2
    assert all("${NPM_DRY}" in line for line in publishes), publishes


def test_checksums_come_from_the_published_bytes():
    attach = _jobs()["attach-assets"]
    assert "gh release download" in attach and "--dir published" in attach
    assert re.search(r"dir=published\n\s+\[ \"\$DRY_RUN\" = \"true\" \] && dir=built", attach)
    npm = _jobs()["publish-npm"]
    assert "name: checksums" in npm and "path: npm" in npm  # lands as npm/checksums.json
    assert "gh release upload" not in npm, "publish-npm has no release write access"


def test_tag_is_validated_once_and_never_taken_from_elsewhere():
    jobs = _jobs()
    assert "refusing non-semver tag" in jobs["resolve"]
    for name in ("build-binaries", "attach-assets", "publish-npm"):
        assert "github.event.inputs.tag" not in jobs[name]
        assert "github.event.release.tag_name" not in jobs[name]
    assert "needs.resolve.outputs.ref" in jobs["build-binaries"]
    assert "needs.resolve.outputs.ref" in jobs["publish-npm"]


def test_dry_run_version_is_not_a_prerelease():
    """npm refuses to publish a prerelease without --tag, even with --dry-run (found by the first dry run)."""
    resolve = _jobs()["resolve"]
    m = re.search(r'echo "version=(\S+)" >> "\$GITHUB_OUTPUT"\n\s+echo "ref=\$GITHUB_SHA"', resolve)
    assert m, "dry-run branch of the resolve step not found"
    assert re.fullmatch(r"\d+\.\d+\.\d+", m.group(1)), m.group(1)


def test_manylinux_package_installs_retry_mirror_failures():
    inner = (ROOT / ".github" / "scripts" / "manylinux-build-inner.sh").read_text(encoding="utf-8")
    assert "retry dnf upgrade" in inner and "retry dnf install" in inner

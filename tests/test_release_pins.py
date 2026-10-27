"""The release pipeline's inputs stay pinned (supply-chain hardening).

Static checks over .github/: every GitHub Action is pinned to a commit SHA, tool versions
are exact, the manylinux base images are pinned by digest and are what the build script
actually runs, the binary-build dependencies are hash-locked, and Dependabot watches what it
can (actions, the Dockerfiles, uv.lock; the uv/npm/Node versions in workflows are bumped by hand).
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GITHUB = ROOT / ".github"
WORKFLOWS = sorted([*(GITHUB / "workflows").glob("*.yml"), *(GITHUB / "workflows").glob("*.yaml")])
ACTION_FILES = sorted((GITHUB / "actions").glob("**/action.y*ml")) if (GITHUB / "actions").exists() else []
DOCKERFILES = sorted((GITHUB / "docker").glob("*/Dockerfile"))
SHA = r"[0-9a-f]{40}"
DIGEST_REF = re.compile(r"^[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}$")


def _uses_lines():
    for wf in [*WORKFLOWS, *ACTION_FILES]:
        for lineno, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            m = re.match(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$", line)
            if m:
                yield str(wf.relative_to(GITHUB)), lineno, m.group(1), m.group(2)


def test_workflows_found():
    assert {"ci.yml", "publish.yml", "release-binaries.yml"} <= {w.name for w in WORKFLOWS}


@pytest.mark.parametrize(("wf", "lineno", "ref", "rest"), list(_uses_lines()))
def test_every_action_is_pinned_to_a_commit_sha(wf, lineno, ref, rest):
    where = f"{wf}:{lineno}"
    assert not ref.startswith("./"), f"{where}: local actions are not expected here"
    assert not ref.startswith("docker://"), f"{where}: docker actions must be pinned by digest elsewhere"
    assert re.fullmatch(rf"[\w.-]+/[\w./-]+@{SHA}", ref), f"{where}: {ref} is not pinned to a 40-hex commit"
    assert re.match(r"^\s+#\s*v\d+(\.\d+)*\s*$", rest), f"{where}: needs a trailing '# vX.Y.Z' comment for Dependabot"


def _setup_uv_steps():
    """(workflow, step text) for every setup-uv step: the lines up to the next '- name:'/'- uses:' entry."""
    for wf in WORKFLOWS:
        lines = wf.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if "astral-sh/setup-uv@" not in line:
                continue
            j = i + 1
            while j < len(lines) and not re.match(r"\s*-\s+(name|uses):", lines[j]):
                j += 1
            yield wf.name, "\n".join(lines[i:j])


def test_setup_uv_versions_are_exact_and_release_steps_do_not_cache():
    steps = list(_setup_uv_steps())
    assert len(steps) >= 5, "setup-uv steps not found"
    seen = set()
    for name, step in steps:
        m = re.search(r"^\s+version:\s*\"?(\d+\.\d+\.\d+)\"?\s*$", step, re.M)
        assert m, f"{name}: setup-uv step without an exact version:\n{step}"
        seen.add(m.group(1))
        if name in ("release-binaries.yml", "publish.yml"):
            assert re.search(r"^\s+enable-cache:\s*false\b", step, re.M), f"{name}: release jobs must not cache"
    assert len(seen) == 1, f"uv versions differ between steps: {seen}"


def test_pypi_oidc_permission_is_only_on_the_publish_job():
    text = (GITHUB / "workflows" / "publish.yml").read_text(encoding="utf-8")
    top = text.split("jobs:", 1)[0]
    assert "id-token" not in top, "id-token must not be granted at workflow level"
    build, publish = text.split("  publish:", 1)
    assert "id-token" not in build, "the build job runs build-backend code and must not mint OIDC tokens"
    assert "id-token: write" in publish


def test_npm_is_installed_at_an_exact_trusted_publishing_version():
    text = (GITHUB / "workflows" / "release-binaries.yml").read_text(encoding="utf-8")
    versions = re.findall(r"npm install -g npm@(\S+)", text)
    assert versions, "release-binaries.yml no longer installs npm explicitly"
    for v in versions:
        m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", v)
        assert m, f"npm version {v!r} is not exact"
        assert tuple(map(int, m.groups())) >= (11, 5, 1)  # first npm with Trusted Publishing


def test_manylinux_dockerfiles_pin_a_digest():
    assert {p.parent.name for p in DOCKERFILES} == {"manylinux-x86_64", "manylinux-aarch64"}
    for df in DOCKERFILES:
        froms = [ln for ln in df.read_text(encoding="utf-8").splitlines() if ln.startswith("FROM ")]
        assert len(froms) == 1, df
        ref = froms[0].split()[1]
        assert DIGEST_REF.match(ref), f"{df}: {ref} must be repo:tag@sha256:<64 hex>"
        assert df.parent.name.removeprefix("manylinux-") in ref, f"{df}: image arch does not match directory"


def test_dependabot_watches_every_pinned_artifact():
    dependabot = (GITHUB / "dependabot.yml").read_text(encoding="utf-8")
    docker_dirs = set(re.findall(r'package-ecosystem:\s*"docker"\s*\n\s*directory:\s*"([^"]+)"', dependabot))
    assert docker_dirs == {f"/.github/docker/{p.parent.name}" for p in DOCKERFILES}
    assert 'package-ecosystem: "github-actions"' in dependabot
    assert 'package-ecosystem: "uv"' in dependabot


def test_build_script_runs_exactly_the_pinned_image(tmp_path):
    """build-linux-binary.sh must docker pull/run the FROM reference of the host arch's Dockerfile."""
    bash = shutil.which("bash")
    assert bash, "bash is required"
    work = tmp_path / "repo"
    shutil.copytree(GITHUB / "docker", work / ".github" / "docker")
    (work / "reqs-binary.txt").write_text("", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    stub = bin_dir / "docker"
    stub.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n', encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    subprocess.run(
        [bash, str(GITHUB / "scripts" / "build-linux-binary.sh")], cwd=work, env=env, check=True, capture_output=True
    )

    arch = "aarch64" if platform.machine().lower() in ("aarch64", "arm64") else "x86_64"
    expected = (GITHUB / "docker" / f"manylinux-{arch}" / "Dockerfile").read_text(encoding="utf-8")
    ref = next(ln.split()[1] for ln in expected.splitlines() if ln.startswith("FROM "))
    calls = log.read_text(encoding="utf-8").splitlines()
    assert any(c.startswith("pull") and ref in c for c in calls), calls
    assert any(c.startswith("run") and f" {ref} " in f" {c} " for c in calls), calls
    assert all("@sha256:" in c for c in calls if c.startswith(("pull", "run")))


def test_build_script_refuses_an_unpinned_image(tmp_path):
    bash = shutil.which("bash")
    assert bash
    work = tmp_path / "repo"
    for arch in ("x86_64", "aarch64"):
        d = work / ".github" / "docker" / f"manylinux-{arch}"
        d.mkdir(parents=True)
        (d / "Dockerfile").write_text(f"FROM quay.io/pypa/manylinux_2_28_{arch}:latest\n", encoding="utf-8")
    (work / "reqs-binary.txt").write_text("", encoding="utf-8")
    proc = subprocess.run(
        [bash, str(GITHUB / "scripts" / "build-linux-binary.sh")], cwd=work, capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "pinned by digest" in proc.stderr


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is needed to export the lock")
def test_binary_requirements_export_is_fully_hash_locked(tmp_path):
    out = tmp_path / "reqs.txt"
    subprocess.run(
        ["bash", str(GITHUB / "scripts" / "export-binary-requirements.sh"), str(out)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    text = out.read_text(encoding="utf-8")
    blocks: list[str] = []
    joined = False
    for line in text.splitlines():
        if joined:
            blocks[-1] += "\n" + line
        elif re.match(r"[A-Za-z0-9]", line):
            blocks.append(line)
        else:
            continue
        joined = line.rstrip().endswith("\\")
    assert blocks
    for block in blocks:
        assert "--hash=sha256:" in block, f"requirement without a hash: {block.splitlines()[0]}"
    names = {re.match(r"[A-Za-z0-9_.-]+", b).group(0).lower() for b in blocks}
    # Build tooling, the pinned build backend, and the docs extra are all in the file.
    assert {"pyinstaller", "setuptools", "pyelftools", "networkx"} <= names
    # The docs extra is excluded from the bundle (pyinstaller-build.sh), so it is not installed either.
    assert not names & {"pypdf", "python-docx", "openpyxl", "lxml"}
    # One file serves every platform: platform-only packages carry markers instead of being dropped.
    assert any(b.startswith("pefile") and "sys_platform == 'win32'" in b for b in blocks)
    assert any(b.startswith("macholib") and "sys_platform == 'darwin'" in b for b in blocks)
    assert any(b.startswith("pyelftools") and "sys_platform == 'linux'" in b for b in blocks)
    # The project itself is installed separately, from the checkout.
    assert "graphify-sf" not in names


def test_install_script_uses_hashes_and_the_pinned_build_backend():
    text = (GITHUB / "scripts" / "install-binary-deps.sh").read_text(encoding="utf-8")
    assert "--require-hashes" in text
    assert "--no-build-isolation" in text and "--no-deps" in text
    inner = (GITHUB / "scripts" / "manylinux-build-inner.sh").read_text(encoding="utf-8")
    assert "install-binary-deps.sh" in inner
    assert "--upgrade pip" not in inner
    assert "--only-binary=:all:" in text
    for wf in ("ci.yml", "release-binaries.yml"):
        wf_text = (GITHUB / "workflows" / wf).read_text(encoding="utf-8")
        assert "export-binary-requirements.sh" in wf_text, wf
        assert "install-binary-deps.sh" in wf_text, wf
        assert 'pip install ".[docs]"' not in wf_text, f"{wf}: unpinned binary install is back"

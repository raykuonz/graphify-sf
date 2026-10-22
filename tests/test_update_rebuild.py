"""0.4.5 fixes: ``--update`` is an idempotent rebuild with safety checks, ``built_at_commit``
is the analysed project's, and the watcher sees every metadata type."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from graphify_sf.__main__ import _run_pipeline

FIXTURES = Path(__file__).parent / "fixtures"


def _run(project: Path, out_dir: Path, *, update: bool, force: bool = False, **kw) -> dict:
    _run_pipeline(project, out_dir, update=update, directed=False, no_viz=True, max_workers=1, force=force, **kw)
    return json.loads((out_dir / "graph.json").read_text(encoding="utf-8"))


def _link_keys(data: dict) -> list[tuple]:
    return sorted((e["source"], e["target"], e.get("relation", "")) for e in data["links"])


def test_update_is_idempotent(tmp_path):
    project = tmp_path / "proj"
    shutil.copytree(FIXTURES / "epicA_callout", project)
    out = tmp_path / "out"

    fresh = _run(project, out, update=False)
    first = _run(project, out, update=True)
    second = _run(project, out, update=True)

    assert len(fresh["links"]) > 0
    assert _link_keys(first) == _link_keys(fresh)
    assert _link_keys(second) == _link_keys(fresh)
    assert sorted(n["id"] for n in second["nodes"]) == sorted(n["id"] for n in fresh["nodes"])


def test_update_drops_deleted_files_without_force(tmp_path):
    base = tmp_path / "proj" / "force-app" / "main" / "default" / "classes"
    base.mkdir(parents=True)
    (base / "First.cls").write_text("public class First { }", encoding="utf-8")
    (base / "Second.cls").write_text("public class Second { }", encoding="utf-8")
    out = tmp_path / "out"

    before = _run(tmp_path / "proj", out, update=False)
    assert {"First", "Second"} <= {n["label"] for n in before["nodes"]}

    (base / "Second.cls").unlink()
    after = _run(tmp_path / "proj", out, update=True)  # no --force: shrinking is legitimate here

    labels = {n["label"] for n in after["nodes"]}
    assert "First" in labels
    assert "Second" not in labels


def test_plain_run_still_refuses_to_shrink_without_force(tmp_path):
    base = tmp_path / "proj" / "force-app" / "main" / "default" / "classes"
    base.mkdir(parents=True)
    (base / "First.cls").write_text("public class First { }", encoding="utf-8")
    (base / "Second.cls").write_text("public class Second { }", encoding="utf-8")
    out = tmp_path / "out"
    _run(tmp_path / "proj", out, update=False)

    (base / "Second.cls").unlink()
    kept = _run(tmp_path / "proj", out, update=False)

    assert "Second" in {n["label"] for n in kept["nodes"]}


def _git(repo: Path, *args: str) -> str:
    # Drop GIT_DIR & co. so a test run from inside a git hook can't touch the outer repo.
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README").write_text("x", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return _git(repo, "rev-parse", "HEAD")


def test_git_head_is_the_projects_not_the_cwds(tmp_path, monkeypatch):
    from graphify_sf.export import _git_head

    other = tmp_path / "cwd_repo"
    _init_repo(other)
    project = tmp_path / "project_repo"
    project_head = _init_repo(project)
    monkeypatch.chdir(other)

    assert _git_head(project) == project_head
    assert _git_head(project / "README") == project_head  # a file resolves via its directory


def test_git_head_none_outside_a_repo_even_when_cwd_is_one(tmp_path, monkeypatch):
    from graphify_sf.export import _git_head

    other = tmp_path / "cwd_repo"
    _init_repo(other)
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(other)

    assert _git_head(plain) is None


def test_graph_json_records_the_analysed_projects_commit(tmp_path, monkeypatch):
    other = tmp_path / "cwd_repo"
    _init_repo(other)
    project = tmp_path / "proj"
    shutil.copytree(FIXTURES / "simple_project", project)
    project_head = _init_repo_in_place(project)
    monkeypatch.chdir(other)

    data = _run(project, tmp_path / "out", update=False)

    assert data["built_at_commit"] == project_head


def _init_repo_in_place(repo: Path) -> str:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return _git(repo, "rev-parse", "HEAD")


def test_graph_json_has_no_commit_for_a_non_git_project(tmp_path, monkeypatch):
    other = tmp_path / "cwd_repo"
    _init_repo(other)
    project = tmp_path / "proj"
    shutil.copytree(FIXTURES / "simple_project", project)
    monkeypatch.chdir(other)

    data = _run(project, tmp_path / "out", update=False)

    assert "built_at_commit" not in data


def test_cluster_only_keeps_the_original_build_commit(tmp_path, monkeypatch):
    from graphify_sf.__main__ import _cmd_cluster_only

    project = tmp_path / "proj"
    shutil.copytree(FIXTURES / "simple_project", project)
    built = _init_repo_in_place(project)
    out = tmp_path / "out"
    _run(project, out, update=False)
    (project / "README").write_text("later", encoding="utf-8")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "later")
    assert _git(project, "rev-parse", "HEAD") != built

    _cmd_cluster_only(project, out, no_viz=True)

    assert json.loads((out / "graph.json").read_text(encoding="utf-8"))["built_at_commit"] == built


def test_watcher_matches_endpoint_metadata_and_bundle_files():
    from graphify_sf.watch import _is_sf_file

    for name in (
        "lwc/myCmp/myCmp.js",
        "lwc/myCmp/myCmp.html",
        "aura/myCmp/myCmp.cmp",
        "aura/myCmp/myCmpController.js",
        "Acme.namedCredential-meta.xml",
        "Api.externalService-meta.xml",
        "Site.remoteSite-meta.xml",
        "Ds.externalDataSource-meta.xml",
        "Csp.cspTrustedSite-meta.xml",
    ):
        assert _is_sf_file(f"/p/{name}"), name
    assert not _is_sf_file("/p/notes.txt")


def test_git_head_ignores_an_inherited_git_dir(tmp_path, monkeypatch):
    from graphify_sf.export import _git_head

    other = tmp_path / "cwd_repo"
    _init_repo(other)
    project = tmp_path / "project_repo"
    project_head = _init_repo(project)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))

    assert _git_head(project) == project_head


def test_export_json_keeps_the_build_commit(tmp_path, monkeypatch):
    from graphify_sf.__main__ import main

    project = tmp_path / "proj"
    shutil.copytree(FIXTURES / "simple_project", project)
    built = _init_repo_in_place(project)
    out = tmp_path / "out"
    _run(project, out, update=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv", ["graphify-sf", "export", "json", "--graph", str(out / "graph.json"), "--out", str(out)]
    )

    main()

    assert json.loads((out / "graph.json").read_text(encoding="utf-8"))["built_at_commit"] == built


def _two_class_project(root: Path) -> Path:
    base = root / "force-app" / "main" / "default" / "classes"
    base.mkdir(parents=True)
    (base / "First.cls").write_text("public class First { }", encoding="utf-8")
    (base / "Second.cls").write_text("public class Second { }", encoding="utf-8")
    return base


def test_update_on_a_subdirectory_rebuilds_just_that_path(tmp_path):
    # Documented: --update covers the path it is given, like any other run with --force.
    base = _two_class_project(tmp_path / "proj")
    flows = tmp_path / "proj" / "force-app" / "main" / "default" / "flows"
    shutil.copytree(FIXTURES / "simple_project" / "force-app" / "main" / "default" / "flows", flows)
    out = tmp_path / "out"
    _run(tmp_path / "proj", out, update=False)

    after = _run(base, out, update=True)

    assert {n.get("sf_type") for n in after["nodes"]} == {"ApexClass"}


def test_update_rebuilds_without_a_file_that_now_fails_to_parse(tmp_path):
    # A half-edited file drops out until it parses again; refusing here would leave the
    # hook and watcher graphs stale.
    _two_class_project(tmp_path / "proj")
    flows = tmp_path / "proj" / "force-app" / "main" / "default" / "flows"
    shutil.copytree(FIXTURES / "simple_project" / "force-app" / "main" / "default" / "flows", flows)
    out = tmp_path / "out"
    before = _run(tmp_path / "proj", out, update=False)
    flow = sorted(flows.glob("*.flow-meta.xml"))[0]
    flow.write_text(flow.read_text(encoding="utf-8")[:40], encoding="utf-8")  # truncated mid-edit

    after = _run(tmp_path / "proj", out, update=True)

    assert len(after["nodes"]) < len(before["nodes"])


def test_update_accepts_a_node_that_dedup_attributes_to_another_file(tmp_path):
    # Profile tabVisibilities emit the same CustomTab node as the tab file; dedup keeps one
    # copy, so the tab file seems to produce nothing. That must not block --update.
    project = tmp_path / "proj"
    shutil.copytree(FIXTURES / "epicD_config", project)
    profiles = project / "force-app" / "main" / "default" / "profiles"
    profiles.mkdir(parents=True)
    out = tmp_path / "out"
    _run(project, out, update=False)
    (profiles / "Admin.profile-meta.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Profile xmlns="http://soap.sforce.com/2006/04/metadata">\n'
        "  <tabVisibilities><tab>AccountTab</tab><visibility>DefaultOn</visibility></tabVisibilities>\n"
        "</Profile>\n",
        encoding="utf-8",
    )

    after = _run(project, out, update=True)

    assert any(n.get("sf_type") == "Profile" for n in after["nodes"])


def test_update_refuses_to_drop_llm_facts_without_backend(tmp_path):
    _two_class_project(tmp_path / "proj")
    out = tmp_path / "out"
    data = _run(tmp_path / "proj", out, update=False)
    first = next(n for n in data["nodes"] if n["label"] == "First")
    data["nodes"].append(
        {
            "id": "llm_concept",
            "label": "Billing",
            "sf_type": "Concept",
            "source_file": first["source_file"],
            "extractor": "llm",
        }
    )
    (out / "graph.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(SystemExit):
        _run(tmp_path / "proj", out, update=True)
    assert "llm_concept" in {n["id"] for n in json.loads((out / "graph.json").read_text(encoding="utf-8"))["nodes"]}

    _run(tmp_path / "proj", out, update=True, force=True)  # --force drops them
    assert "llm_concept" not in {n["id"] for n in json.loads((out / "graph.json").read_text(encoding="utf-8"))["nodes"]}


def test_update_refuses_when_the_backend_produced_nothing(tmp_path, monkeypatch):
    _two_class_project(tmp_path / "proj")
    out = tmp_path / "out"
    data = _run(tmp_path / "proj", out, update=False)
    data["nodes"].append({"id": "llm_concept", "label": "Billing", "sf_type": "Concept", "extractor": "llm"})
    (out / "graph.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("graphify_sf.llm.detect_backend", lambda: None)  # --backend auto, no key

    with pytest.raises(SystemExit):
        _run(tmp_path / "proj", out, update=True, backend="auto")


def test_update_treats_relative_source_files_from_older_llm_runs_as_llm_facts(tmp_path):
    _two_class_project(tmp_path / "proj")
    out = tmp_path / "out"
    data = _run(tmp_path / "proj", out, update=False)
    data["nodes"].append(
        {"id": "old_llm", "label": "Billing", "sf_type": "Concept", "source_file": "classes/First.cls"}
    )
    (out / "graph.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(SystemExit):
        _run(tmp_path / "proj", out, update=True)


def test_update_detects_legacy_llm_edges_even_when_their_nodes_were_folded(tmp_path):
    _two_class_project(tmp_path / "proj")
    out = tmp_path / "out"
    data = _run(tmp_path / "proj", out, update=False)
    a, b = (n["id"] for n in data["nodes"][:2])
    data["links"].append(
        {"source": a, "target": b, "relation": "semantically_related", "source_file": "classes/First.cls"}
    )
    (out / "graph.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(SystemExit):
        _run(tmp_path / "proj", out, update=True)


def test_update_accepts_a_graph_built_on_another_os(tmp_path):
    # Static nodes of a Windows-built graph carry "C:/..." paths: absolute, not LLM output.
    _two_class_project(tmp_path / "proj")
    out = tmp_path / "out"
    data = _run(tmp_path / "proj", out, update=False)
    data["nodes"].append(
        {"id": "win_only", "label": "Old", "sf_type": "ApexClass", "source_file": "C:/proj/classes/Old.cls"}
    )
    data["nodes"].append(
        {"id": "posix_only", "label": "Old2", "sf_type": "ApexClass", "source_file": "/elsewhere/Old2.cls"}
    )
    (out / "graph.json").write_text(json.dumps(data), encoding="utf-8")

    after = _run(tmp_path / "proj", out, update=True)

    assert "win_only" not in {n["id"] for n in after["nodes"]}


def test_llm_extraction_tags_its_output_and_reports_a_merge(tmp_path, monkeypatch):
    from graphify_sf.__main__ import _run_llm_extraction

    _two_class_project(tmp_path / "proj")
    from graphify_sf.detect import detect

    detection = detect(tmp_path / "proj")
    extraction = {"nodes": [], "edges": []}
    monkeypatch.setattr(
        "graphify_sf.llm.extract_corpus_parallel",
        lambda *a, **k: {
            "nodes": [{"id": "c", "label": "Billing", "sf_type": "Concept"}],
            "edges": [{"source": "c", "target": "c2", "relation": "references", "confidence": "INFERRED"}],
        },
    )

    merged = _run_llm_extraction(tmp_path / "proj", detection, extraction, "claude", 40_000, {"input": 0, "output": 0})

    assert merged is True
    assert all(x["extractor"] == "llm" for x in extraction["nodes"] + extraction["edges"])


def test_update_allows_nodes_a_reextracted_file_no_longer_produces(tmp_path):
    base = tmp_path / "proj" / "force-app" / "main" / "default" / "classes"
    base.mkdir(parents=True)
    (base / "First.cls").write_text("public class First { public void a() {} public void b() {} }", encoding="utf-8")
    out = tmp_path / "out"
    before = _run(tmp_path / "proj", out, update=False)
    (base / "First.cls").write_text("public class First { public void a() {} }", encoding="utf-8")

    after = _run(tmp_path / "proj", out, update=True)

    assert len(after["nodes"]) < len(before["nodes"])


@pytest.mark.parametrize(
    ("event_type", "src", "dest", "is_dir", "expected"),
    [
        ("modified", "/p/force-app/main/default/classes/A.cls", "", False, True),
        ("modified", "/p/force-app/main/default/lwc/myCmp/myCmp.js", "", False, True),
        ("modified", "/p/force-app/main/default/aura/myCmp/myCmpController.js", "", False, True),
        ("moved", "/p/force-app/main/default/classes/A.cls", "/p/tmp/A.cls.bak", False, True),
        ("deleted", "/p/force-app/main/default/objects/Account__c", "", True, True),
        ("moved", "/p/force-app/main/default/lwc/myCmp", "/tmp/myCmp", True, True),
        ("modified", "/p/force-app/main/default/objects", "", True, False),
        ("opened", "/p/force-app/main/default/classes/A.cls", "", False, False),
        ("closed_no_write", "/p/force-app/main/default/classes/A.cls", "", False, False),
        ("modified", "/p/graphify-sf-out/graph.json", "", False, False),
        ("modified", "/p/docs/notes.md", "", False, False),
        ("deleted", "C:/p/force-app/main/default/lwc/myCmp", "", False, True),  # Windows folder delete
        ("modified", "/p/.sf/config.json", "", False, False),
        ("deleted", "/p/.sf/orgs", "", True, False),
    ],
)
def test_watcher_event_filter(event_type, src, dest, is_dir, expected):
    from graphify_sf.watch import _event_triggers_rebuild

    assert _event_triggers_rebuild(event_type, src, dest, is_dir, Path("/p")) is expected


def test_watcher_still_fires_for_a_project_under_a_skip_named_directory():
    from graphify_sf.watch import _event_triggers_rebuild

    root = Path("/repo/.claude/worktrees/feature")
    cls = str(root / "force-app/main/default/classes/A.cls")

    assert _event_triggers_rebuild("modified", cls, "", False, root) is True
    assert _event_triggers_rebuild("modified", str(root / "dist/A.cls"), "", False, root) is False


def test_watcher_fires_when_a_file_is_moved_into_a_skipped_directory():
    from graphify_sf.watch import _event_triggers_rebuild

    root = Path("/p")
    src = "/p/force-app/main/default/classes/A.cls"

    assert _event_triggers_rebuild("moved", src, "/p/dist/A.cls", False, root) is True

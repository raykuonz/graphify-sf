"""Tests for detect module."""

from __future__ import annotations

from pathlib import Path


def test_detect_returns_total_files(simple_detect_result):
    """Test that detect() returns correct total_files count."""
    assert "total_files" in simple_detect_result
    assert simple_detect_result["total_files"] > 0, "Should detect at least one file"


def test_detect_finds_apex_classes(simple_detect_result):
    """Test that Apex classes are detected."""
    apex_files = simple_detect_result["files"]["apex"]
    assert len(apex_files) >= 2, "Should find at least 2 Apex classes"
    # Check that AccountService and AccountTriggerHandler are found
    class_names = [Path(f).stem for f in apex_files]
    assert "AccountService" in class_names
    assert "AccountTriggerHandler" in class_names


def test_detect_finds_triggers(simple_detect_result):
    """Test that triggers are detected."""
    trigger_files = simple_detect_result["files"]["trigger"]
    assert len(trigger_files) >= 1, "Should find at least 1 trigger"
    trigger_names = [Path(f).stem for f in trigger_files]
    assert "AccountTrigger" in trigger_names


def test_detect_finds_flows(simple_detect_result):
    """Test that flows are detected."""
    flow_files = simple_detect_result["files"]["flow"]
    assert len(flow_files) >= 1, "Should find at least 1 flow"


def test_detect_finds_objects(simple_detect_result):
    """Test that custom objects are detected."""
    object_files = simple_detect_result["files"]["object"]
    assert len(object_files) >= 1, "Should find at least 1 custom object"


def test_detect_finds_fields(simple_detect_result):
    """Test that custom fields are detected."""
    field_files = simple_detect_result["files"]["field"]
    assert len(field_files) >= 1, "Should find at least 1 custom field"


def test_detect_finds_lwc_bundles(simple_detect_result):
    """Test that LWC bundles are detected."""
    lwc_bundles = simple_detect_result["bundle_dirs"]["lwc"]
    assert len(lwc_bundles) >= 1, "Should find at least 1 LWC bundle"
    bundle_names = [Path(b).name for b in lwc_bundles]
    assert "accountCard" in bundle_names


def test_detect_compound_suffix_flow(simple_project_path):
    """Test compound suffix matching for .flow-meta.xml files."""
    from graphify_sf.detect import detect

    result = detect(simple_project_path)
    flow_files = result["files"]["flow"]
    assert any("UpdateAccountStatus" in f for f in flow_files)


def test_detect_compound_suffix_field(simple_project_path):
    """Test compound suffix matching for .field-meta.xml files."""
    from graphify_sf.detect import detect

    result = detect(simple_project_path)
    field_files = result["files"]["field"]
    assert any("Status__c" in f for f in field_files)


def test_detect_skips_common_dirs(tmp_path):
    """Test that common directories are skipped."""
    # Create a project with a node_modules directory
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "node_modules").mkdir()
    (project / "node_modules" / "test.cls").write_text("public class Test {}")

    from graphify_sf.detect import detect

    result = detect(project)

    # node_modules should be skipped, so no files detected
    assert result["total_files"] == 0


def test_detect_incremental_exists(simple_project_path, tmp_path):
    """Test that detect_incremental() exists and works."""
    from graphify_sf.detect import detect_incremental, save_manifest

    manifest_path = tmp_path / "manifest.json"

    # First run - all files should be new
    result = detect_incremental(simple_project_path, str(manifest_path))
    assert "new_files" in result
    assert "unchanged_files" in result

    # Save manifest
    save_manifest(result["files"], str(manifest_path))

    # Second run - all files should be unchanged
    result2 = detect_incremental(simple_project_path, str(manifest_path))
    new_count = sum(len(v) for v in result2["new_files"].values())
    unchanged_count = sum(len(v) for v in result2["unchanged_files"].values())

    assert unchanged_count > 0, "Should have unchanged files on second run"
    assert new_count == 0, "Should have no new files on second run"


def test_save_and_load_manifest(simple_detect_result, tmp_path):
    """Test that save_manifest() and load_manifest() work."""
    from graphify_sf.detect import load_manifest, save_manifest

    manifest_path = tmp_path / "manifest.json"
    save_manifest(simple_detect_result["files"], str(manifest_path))

    assert manifest_path.exists(), "Manifest file should be created"

    loaded = load_manifest(str(manifest_path))
    assert isinstance(loaded, dict), "Should load a dict"
    assert len(loaded) > 0, "Manifest should contain entries"


def test_load_manifest_missing_file(tmp_path):
    """Test that load_manifest() returns empty dict for missing file."""
    from graphify_sf.detect import load_manifest

    manifest_path = tmp_path / "nonexistent.json"
    result = load_manifest(str(manifest_path))

    assert result == {}, "Should return empty dict for missing file"


def test_detect_warning_none_for_small_project(simple_detect_result):
    """Test that warning is None for small projects."""
    assert simple_detect_result["warning"] is None


def test_detect_skipped_list(simple_detect_result):
    """Test that skipped list is present."""
    assert "skipped" in simple_detect_result
    assert isinstance(simple_detect_result["skipped"], list)


# ---------------------------------------------------------------------------
# .gitignore / .forceignore support (default-on, --include-ignored opt-out)
# ---------------------------------------------------------------------------


def _make_sfdx_tree(root: Path) -> None:
    """Create a tiny SFDX tree: one kept class + one queue + a flow."""
    classes = root / "force-app" / "main" / "default" / "classes"
    classes.mkdir(parents=True)
    (classes / "Keep.cls").write_text("public class Keep {}")
    (classes / "Keep.cls-meta.xml").write_text(
        '<?xml version="1.0"?><ApexClass xmlns="http://soap.sforce.com/2006/04/metadata"><apiVersion>59.0</apiVersion></ApexClass>'
    )
    queues = root / "force-app" / "main" / "default" / "queues"
    queues.mkdir(parents=True)
    (queues / "Sales.queue-meta.xml").write_text(
        '<?xml version="1.0"?><Queue xmlns="http://soap.sforce.com/2006/04/metadata"><name>Sales</name></Queue>'
    )
    flows = root / "force-app" / "main" / "default" / "flows"
    flows.mkdir(parents=True)
    (flows / "Deprecated.flow-meta.xml").write_text(
        '<?xml version="1.0"?><Flow xmlns="http://soap.sforce.com/2006/04/metadata"><label>Deprecated</label></Flow>'
    )


def test_forceignore_skips_files_by_default(tmp_path):
    """.forceignore patterns skip matching files by default, with per-source count."""
    from graphify_sf.detect import detect

    _make_sfdx_tree(tmp_path)
    (tmp_path / ".forceignore").write_text("**/queues/**\n**/Deprecated.flow-meta.xml\n")

    res = detect(tmp_path)
    all_files = [f for lst in res["files"].values() for f in lst]
    assert not any("queues" in f for f in all_files), "queue file should be skipped"
    assert not any("Deprecated" in f for f in all_files), "deprecated flow should be skipped"
    assert any("Keep.cls" in f for f in all_files), "kept class must remain"
    assert res["skipped_count"] >= 2
    assert res["skipped_by_source"][".forceignore"] >= 2
    assert res["respect_ignore"] is True


def test_gitignore_skips_files_by_default(tmp_path):
    """.gitignore patterns skip matching files by default."""
    from graphify_sf.detect import detect

    _make_sfdx_tree(tmp_path)
    (tmp_path / ".gitignore").write_text("**/Deprecated.flow-meta.xml\n")

    res = detect(tmp_path)
    all_files = [f for lst in res["files"].values() for f in lst]
    assert not any("Deprecated" in f for f in all_files)
    assert res["skipped_by_source"][".gitignore"] >= 1


def test_include_ignored_scans_everything(tmp_path):
    """respect_ignore=False (--include-ignored) ignores .gitignore/.forceignore."""
    from graphify_sf.detect import detect

    _make_sfdx_tree(tmp_path)
    (tmp_path / ".forceignore").write_text("**/queues/**\n**/Deprecated.flow-meta.xml\n")

    res = detect(tmp_path, respect_ignore=False)
    all_files = [f for lst in res["files"].values() for f in lst]
    assert any("Deprecated" in f for f in all_files), "ignored flow must be included"
    assert res["skipped_count"] == 0
    assert res["respect_ignore"] is False


def test_ignore_files_discovered_upward_from_subdir(tmp_path):
    """Scanning a subdir still finds .forceignore at the project root (git-style upward walk)."""
    from graphify_sf.detect import detect

    _make_sfdx_tree(tmp_path)
    # ignore file at repo root; scan the force-app subdir
    (tmp_path / ".forceignore").write_text("**/Deprecated.flow-meta.xml\n")

    res = detect(tmp_path / "force-app")
    all_files = [f for lst in res["files"].values() for f in lst]
    assert not any("Deprecated" in f for f in all_files), "root .forceignore must apply when scanning subdir"
    assert res["skipped_by_source"][".forceignore"] >= 1


def test_gitignore_negation_semantics(tmp_path):
    """gitignore negation (!keep) is honored — fnmatch could not do this."""
    from graphify_sf.detect import detect

    _make_sfdx_tree(tmp_path)
    # ignore all flows, then un-ignore the one we keep
    (tmp_path / ".gitignore").write_text("**/*.flow-meta.xml\n!**/Deprecated.flow-meta.xml\n")

    res = detect(tmp_path)
    all_files = [f for lst in res["files"].values() for f in lst]
    assert any("Deprecated" in f for f in all_files), "negated pattern must re-include the flow"

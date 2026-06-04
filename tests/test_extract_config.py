"""Tests for config metadata extractors, focusing on extract_flexipage."""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_flexipage(tmp_path: Path, name: str, xml: str) -> Path:
    fp_dir = tmp_path / "force-app" / "main" / "default" / "flexipages"
    fp_dir.mkdir(parents=True)
    p = fp_dir / f"{name}.flexipage-meta.xml"
    p.write_text(xml)
    return p


_NS = "http://soap.sforce.com/2006/04/metadata"


# ---------------------------------------------------------------------------
# sobjectType → record_page_for edge
# ---------------------------------------------------------------------------


def test_flexipage_record_page_for_edge_emitted(tmp_path):
    """sobjectType in FlexiPage XML produces a record_page_for EXTRACTED edge to the object."""
    from graphify_sf.extract._ids import make_sf_id
    from graphify_sf.extract.config import extract_flexipage

    xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<FlexiPage xmlns="{_NS}">
    <flexiPageType>RecordPage</flexiPageType>
    <sobjectType>Account</sobjectType>
</FlexiPage>
"""
    path = _write_flexipage(tmp_path, "Account_Record_Page", xml)
    result = extract_flexipage(path)

    record_page_edges = [e for e in result["edges"] if e["relation"] == "record_page_for"]
    assert len(record_page_edges) == 1
    edge = record_page_edges[0]
    assert edge["target"] == make_sf_id("object", "Account")
    assert edge["confidence"] == "EXTRACTED"


def test_flexipage_no_sobject_type_no_record_page_edge(tmp_path):
    """FlexiPage without sobjectType emits no record_page_for edge."""
    from graphify_sf.extract.config import extract_flexipage

    xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<FlexiPage xmlns="{_NS}">
    <flexiPageType>AppPage</flexiPageType>
</FlexiPage>
"""
    path = _write_flexipage(tmp_path, "My_App_Page", xml)
    result = extract_flexipage(path)

    assert not any(e["relation"] == "record_page_for" for e in result["edges"])


def test_flexipage_record_page_for_custom_object(tmp_path):
    """sobjectType referencing a custom object uses the correct object_id."""
    from graphify_sf.extract._ids import object_id
    from graphify_sf.extract.config import extract_flexipage

    xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<FlexiPage xmlns="{_NS}">
    <flexiPageType>RecordPage</flexiPageType>
    <sobjectType>Opportunity__c</sobjectType>
</FlexiPage>
"""
    path = _write_flexipage(tmp_path, "Opportunity_Record_Page", xml)
    result = extract_flexipage(path)

    record_page_edges = [e for e in result["edges"] if e["relation"] == "record_page_for"]
    assert len(record_page_edges) == 1
    assert record_page_edges[0]["target"] == object_id("Opportunity__c")


# ---------------------------------------------------------------------------
# Standard-component noise filtering
# ---------------------------------------------------------------------------


def test_flexipage_standard_components_produce_no_edges(tmp_path):
    """Standard Salesforce namespace components (force:, lightning:, etc.) are silently dropped."""
    from graphify_sf.extract.config import extract_flexipage

    xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<FlexiPage xmlns="{_NS}">
    <flexiPageType>RecordPage</flexiPageType>
    <sobjectType>Account</sobjectType>
    <regions>
        <itemInstances>
            <componentInstance>
                <componentName>force:recordDetail</componentName>
            </componentInstance>
            <componentInstance>
                <componentName>lightning:relatedList</componentName>
            </componentInstance>
            <componentInstance>
                <componentName>forceCommunity:header</componentName>
            </componentInstance>
        </itemInstances>
    </regions>
</FlexiPage>
"""
    path = _write_flexipage(tmp_path, "Account_Record_Page2", xml)
    result = extract_flexipage(path)

    contains_edges = [e for e in result["edges"] if e["relation"] == "contains"]
    assert len(contains_edges) == 0, f"Expected no contains edges for standard components, got {contains_edges}"


def test_flexipage_custom_lwc_c_colon_prefix_emits_edge(tmp_path):
    """Custom LWC with c: prefix emits a contains edge to the normalized LWC id."""
    from graphify_sf.extract._ids import lwc_id
    from graphify_sf.extract.config import extract_flexipage

    xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<FlexiPage xmlns="{_NS}">
    <flexiPageType>RecordPage</flexiPageType>
    <regions>
        <itemInstances>
            <componentInstance>
                <componentName>c:accountCard</componentName>
            </componentInstance>
        </itemInstances>
    </regions>
</FlexiPage>
"""
    path = _write_flexipage(tmp_path, "AccountCard_Page", xml)
    result = extract_flexipage(path)

    contains_edges = [e for e in result["edges"] if e["relation"] == "contains"]
    assert len(contains_edges) == 1
    assert contains_edges[0]["target"] == lwc_id("accountCard")
    assert contains_edges[0]["confidence"] == "INFERRED"


def test_flexipage_custom_lwc_c_double_underscore_prefix_emits_edge(tmp_path):
    """Custom LWC with c__ prefix emits a contains edge to the normalized LWC id."""
    from graphify_sf.extract._ids import lwc_id
    from graphify_sf.extract.config import extract_flexipage

    xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<FlexiPage xmlns="{_NS}">
    <flexiPageType>RecordPage</flexiPageType>
    <regions>
        <itemInstances>
            <componentInstance>
                <componentName>c__accountSummary</componentName>
            </componentInstance>
        </itemInstances>
    </regions>
</FlexiPage>
"""
    path = _write_flexipage(tmp_path, "AccountSummary_Page", xml)
    result = extract_flexipage(path)

    contains_edges = [e for e in result["edges"] if e["relation"] == "contains"]
    assert len(contains_edges) == 1
    assert contains_edges[0]["target"] == lwc_id("accountSummary")


def test_flexipage_mixed_components_only_custom_emits_edge(tmp_path):
    """Mixed standard and custom components: only custom produces a contains edge."""
    from graphify_sf.extract.config import extract_flexipage

    xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<FlexiPage xmlns="{_NS}">
    <flexiPageType>RecordPage</flexiPageType>
    <sobjectType>Contact</sobjectType>
    <regions>
        <itemInstances>
            <componentInstance>
                <componentName>force:recordDetail</componentName>
            </componentInstance>
            <componentInstance>
                <componentName>c:contactTimeline</componentName>
            </componentInstance>
            <componentInstance>
                <componentName>lightning:card</componentName>
            </componentInstance>
        </itemInstances>
    </regions>
</FlexiPage>
"""
    path = _write_flexipage(tmp_path, "Contact_Record_Page", xml)
    result = extract_flexipage(path)

    contains_edges = [e for e in result["edges"] if e["relation"] == "contains"]
    assert len(contains_edges) == 1, f"Expected exactly 1 contains edge, got {contains_edges}"
    assert "contacttimeline" in contains_edges[0]["target"].lower()

    record_page_edges = [e for e in result["edges"] if e["relation"] == "record_page_for"]
    assert len(record_page_edges) == 1


# ---------------------------------------------------------------------------
# Node structure
# ---------------------------------------------------------------------------


def test_flexipage_node_structure(tmp_path):
    """FlexiPage node has correct id, label, sf_type, and file_type."""
    from graphify_sf.extract._ids import make_sf_id
    from graphify_sf.extract.config import extract_flexipage

    xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<FlexiPage xmlns="{_NS}">
    <flexiPageType>AppPage</flexiPageType>
</FlexiPage>
"""
    path = _write_flexipage(tmp_path, "MyApp_Page", xml)
    result = extract_flexipage(path)

    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["id"] == make_sf_id("flexipage", "MyApp_Page")
    assert node["label"] == "MyApp_Page"
    assert node["sf_type"] == "FlexiPage"
    assert node["file_type"] == "config"
    assert node["source_file"] == str(path)

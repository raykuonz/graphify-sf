"""0.6.0 E5: Flow ``httpCallout`` actions are callout sites; both Named Credential shapes are read."""

from __future__ import annotations

from pathlib import Path

from graphify_sf.extract.flow import extract_flow


def _flow(tmp_path: Path, actions: str, name: str = "F") -> dict:
    p = tmp_path / f"{name}.flow-meta.xml"
    p.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<Flow xmlns="http://soap.sforce.com/2006/04/metadata">'
        f"<apiVersion>60.0</apiVersion>{actions}</Flow>",
        encoding="utf-8",
    )
    return extract_flow(p)


def _action(name: str, action_type: str = "httpCallout", action_name: str | None = None, *values: str) -> str:
    params = "".join(
        f"<inputParameters><name>p{i}</name><value><stringValue>{v}</stringValue></value></inputParameters>"
        for i, v in enumerate(values)
    )
    ref = f"<actionName>{action_name}</actionName>" if action_name else ""
    return f"<actionCalls><name>{name}</name><actionType>{action_type}</actionType>{ref}{params}</actionCalls>"


def _callouts(r: dict) -> list[dict]:
    return [e for e in r["edges"] if e["relation"] == "makes_callout"]


def test_string_value_shape(tmp_path):
    r = _flow(tmp_path, _action("Call", "httpCallout", None, "callout:Pay_NC/v1/charge"))
    (edge,) = _callouts(r)
    assert (edge["target"], edge["confidence"], edge["source_location"]) == (
        "namedcredential_pay_nc",
        "EXTRACTED",
        "Call",
    )
    assert (r["_sites"], r["_unresolved"]) == (1, 0)


def test_action_name_shape_with_mustache_braces(tmp_path):
    r = _flow(tmp_path, _action("Call", "httpCallout", "callout:{{Pay_NC}}"))
    (edge,) = _callouts(r)
    assert edge["target"] == "namedcredential_pay_nc" and edge["_tgt_name"] == "Pay_NC"


def test_action_name_shape_without_braces(tmp_path):
    (edge,) = _callouts(_flow(tmp_path, _action("Call", "httpCallout", "callout:Pay_NC")))
    assert edge["target"] == "namedcredential_pay_nc"


def test_unmatched_http_callout_is_an_unresolved_site(tmp_path):
    r = _flow(tmp_path, _action("Call", "httpCallout", "SomeModernExternalService", "{!endpoint}"))
    assert _callouts(r) == []
    assert (r["_sites"], r["_unresolved"]) == (1, 1)


def test_callout_text_in_other_actions_is_not_a_callout(tmp_path):
    r = _flow(tmp_path, _action("Mail", "emailSimple", None, "see callout:Foo for details"))
    assert _callouts(r) == []
    assert (r["_sites"], r["_unresolved"]) == (0, 0)


def test_two_actions_to_one_credential_become_one_edge_with_a_site_count(tmp_path):
    r = _flow(
        tmp_path,
        _action("A", "httpCallout", None, "callout:Pay_NC/a") + _action("B", "httpCallout", None, "callout:Pay_NC/b"),
    )
    (edge,) = _callouts(r)
    assert edge["site_count"] == 2 and edge["source_location"] == "A"
    assert (r["_sites"], r["_unresolved"]) == (2, 0)


def test_literal_url_creates_the_endpoint_node_and_is_extracted(tmp_path):
    r = _flow(tmp_path, _action("Call", "httpCallout", None, "https://API.example.com/x"))
    (edge,) = _callouts(r)
    assert edge["confidence"] == "EXTRACTED"
    (node,) = [n for n in r["nodes"] if n["sf_type"] == "ExternalEndpoint"]
    assert node["label"] == "api.example.com"


def test_merge_field_host_is_unresolved(tmp_path):
    r = _flow(tmp_path, _action("Call", "httpCallout", None, "https://{!Host}/x"))
    assert _callouts(r) == []
    assert r["_unresolved"] == 1


def test_truncated_flow_is_failed_not_zero_sites(tmp_path):
    p = tmp_path / "Broken.flow-meta.xml"
    p.write_text("<Flow><actionCalls>", encoding="utf-8")
    assert extract_flow(p)["_failed"] is True


def test_truncated_flow_withholds_the_capability(tmp_path):
    from graphify_sf.detect import detect
    from graphify_sf.extract import extract

    flows = tmp_path / "proj" / "force-app" / "main" / "default" / "flows"
    flows.mkdir(parents=True)
    (flows / "Good.flow-meta.xml").write_text(
        '<Flow xmlns="http://soap.sforce.com/2006/04/metadata">'
        + _action("C", "httpCallout", None, "callout:X")
        + "</Flow>",
        encoding="utf-8",
    )
    (flows / "Broken.flow-meta.xml").write_text("<Flow><actionCalls>", encoding="utf-8")
    block = extract(detect(tmp_path / "proj"), parallel=False)["analysis"]["callout-edges.flow-http"]
    assert block["status"] == "partial"
    assert (block["eligible"], block["analyzed"], block["failed"]) == (2, 1, 1)
    assert block["sites"] == 1

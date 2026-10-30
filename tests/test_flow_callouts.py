"""0.6.0 E5: Flow ``httpCallout`` actions are callout sites; both Named Credential shapes are read."""

from __future__ import annotations

from pathlib import Path

import pytest

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
        f"<inputParameters><name>{'url' if i == 0 else f'p{i}'}</name><value><stringValue>{v}</stringValue></value></inputParameters>"
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
    for action_type in ("emailSimple", "apex", "chatterPost"):
        r = _flow(tmp_path, _action("Other", action_type, None, "callout:Foo/x", "https://x.example.com/y"))
        assert _callouts(r) == [], action_type
        assert (r["_sites"], r["_unresolved"]) == (0, 0), action_type


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


def test_merge_field_credential_name_is_unresolved(tmp_path):
    for ref in ("callout:{!var}/x", "callout:Pay_NC{!suffix}", "callout:{{!var}}"):
        r = _flow(tmp_path, _action("Call", "httpCallout", None, ref))
        assert _callouts(r) == [], ref
        assert r["_unresolved"] == 1, ref


def test_action_name_wins_and_other_string_values_are_ignored(tmp_path):
    r = _flow(
        tmp_path,
        _action("Call", "httpCallout", "callout:{{Pay_NC}}", "callout:Pay_NC/v1", "https://callback.example.com/hook"),
    )
    (edge,) = _callouts(r)
    assert edge["target"] == "namedcredential_pay_nc" and edge["site_count"] == 1
    assert [n for n in r["nodes"] if n["sf_type"] == "ExternalEndpoint"] == []
    assert (r["_sites"], r["_unresolved"]) == (1, 0)


def test_non_endpoint_url_parameter_does_not_make_the_site_resolved(tmp_path):
    action = (
        "<actionCalls><name>Call</name><actionType>httpCallout</actionType>"
        "<inputParameters><name>url</name><value><elementReference>endpoint_var</elementReference></value></inputParameters>"
        "<inputParameters><name>callback</name><value><stringValue>https://callback.example.com/hook</stringValue></value></inputParameters>"
        "</actionCalls>"
    )
    r = _flow(tmp_path, action)
    assert _callouts(r) == [] and (r["_sites"], r["_unresolved"]) == (1, 1)


def test_an_action_naming_two_targets_is_unresolved(tmp_path):
    action = (
        "<actionCalls><name>Call</name><actionType>httpCallout</actionType>"
        "<inputParameters><name>url</name><value><stringValue>callout:A_NC/x</stringValue></value></inputParameters>"
        "<inputParameters><name>endpoint</name><value><stringValue>callout:B_NC/y</stringValue></value></inputParameters>"
        "</actionCalls>"
    )
    r = _flow(tmp_path, action)
    assert _callouts(r) == [] and r["_unresolved"] == 1


def test_external_service_action_edges_to_the_service(tmp_path):
    r = _flow(tmp_path, _action("Svc", "externalService", "MyService.getOrder"))
    (edge,) = _callouts(r)
    assert (edge["target"], edge["confidence"], edge["_tgt_name"]) == (
        "externalservice_myservice",
        "EXTRACTED",
        "MyService",
    )
    assert edge["source_location"] == "Svc" and (r["_sites"], r["_unresolved"]) == (1, 0)


def test_external_service_action_without_a_service_part_is_unresolved(tmp_path):
    for name in ("", ".op", "bad name.op"):
        r = _flow(tmp_path, _action("Svc", "externalService", name or None))
        assert _callouts(r) == [] and (r["_sites"], r["_unresolved"]) == (1, 1), name


def test_two_operations_of_one_service_aggregate(tmp_path):
    r = _flow(
        tmp_path,
        _action("A", "externalService", "Pay_Svc.charge") + _action("B", "externalService", "Pay_Svc.refund"),
    )
    (edge,) = _callouts(r)
    assert edge["site_count"] == 2 and edge["source_location"] == "A"


@pytest.mark.parametrize(
    "ref", ["callout:Pay NC/x", "callout: Pay_NC/x", "callout:{{Pay_NC}}x", "callout:Pä/x", "callout:Pay.NC/x"]
)
def test_partial_or_invalid_credential_names_are_unresolved(tmp_path, ref):
    r = _flow(tmp_path, _action("Call", "httpCallout", None, ref))
    assert _callouts(r) == [], ref


@pytest.mark.parametrize(
    "url",
    [
        "https:// api.example.com/x",
        "https://api.example.com\\@evil.com/",
        "https://%7B!Host%7D/x",
        "https://bücher.example/x",
    ],
)
def test_untrustworthy_hosts_are_unresolved(tmp_path, url):
    r = _flow(tmp_path, _action("Call", "httpCallout", None, url))
    assert _callouts(r) == [], url


def test_trailing_dot_host_is_normalised(tmp_path):
    r = _flow(tmp_path, _action("Call", "httpCallout", None, "https://api.example.com./x"))
    (node,) = [n for n in r["nodes"] if n["sf_type"] == "ExternalEndpoint"]
    assert node["label"] == "api.example.com"


def test_colliding_hosts_in_one_flow_are_both_visible(tmp_path):
    r = _flow(
        tmp_path,
        _action("A", "httpCallout", None, "https://api.example.com/a")
        + _action("B", "httpCallout", None, "https://api-example.com/b"),
    )
    labels = sorted(n["label"] for n in r["nodes"] if n["sf_type"] == "ExternalEndpoint")
    assert labels == ["api-example.com", "api.example.com"]

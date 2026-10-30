"""0.6.1: Flow ``externalService`` actions reach the Named Credential through the External Service registration."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from graphify_sf.detect import detect

FIXTURE = Path(__file__).parent / "fixtures" / "ext_service_flow"


def _build(project: Path, out: Path) -> dict:
    from graphify_sf.__main__ import _run_pipeline

    _run_pipeline(project, out, update=False, directed=False, no_viz=True, max_workers=1, force=True)
    return json.loads((out / "graph.json").read_text())


def _copy(tmp_path: Path, drop: tuple[str, ...] = ()) -> Path:
    project = tmp_path / "proj"
    shutil.copytree(FIXTURE, project)
    for rel in drop:
        (project / "force-app" / "main" / "default" / rel).unlink()
    return project


def _callouts(data: dict) -> list[dict]:
    return [e for e in data["links"] if e["relation"] == "makes_callout"]


def _flow_block(data: dict) -> dict:
    return data["graphify_sf"]["analysis"]["callout-edges.flow-http"]


def test_registration_suffix_is_detected(tmp_path):
    files = detect(_copy(tmp_path))["files"]
    assert any(str(p).endswith(".externalServiceRegistration-meta.xml") for group in files.values() for p in group)


def test_flow_reaches_the_credential_in_two_hops_plus_a_composed_edge(tmp_path):
    data = _build(_copy(tmp_path), tmp_path / "out")
    by_target = {e["target"]: e for e in _callouts(data) if e["source"] == "flow_charge_customer"}
    assert set(by_target) == {"externalservice_pay_svc", "namedcredential_pay_nc"}
    svc, nc = by_target["externalservice_pay_svc"], by_target["namedcredential_pay_nc"]
    assert (svc["confidence"], svc["site_count"]) == ("EXTRACTED", 2)
    assert (nc["confidence"], nc["site_count"], nc["via_external_service"]) == ("EXTRACTED", 2, "Pay_Svc")
    assert any(
        e["relation"] == "uses" and e["source"] == "externalservice_pay_svc" and e["target"] == "namedcredential_pay_nc"
        for e in data["links"]
    )
    node = next(n for n in data["nodes"] if n["id"] == "externalservice_pay_svc")
    assert node["named_credential_type"] == "Legacy" and not node.get("stub")
    block = _flow_block(data)
    assert (block["status"], block["sites"], block["unresolved"]) == ("complete", 2, 0)


def test_missing_registration_leaves_a_stub_and_unresolved_sites(tmp_path):
    project = _copy(tmp_path, ("externalServiceRegistrations/Pay_Svc.externalServiceRegistration-meta.xml",))
    data = _build(project, tmp_path / "out")
    stub = next(n for n in data["nodes"] if n["id"] == "externalservice_pay_svc")
    assert stub["stub"] is True and stub["label"] == "Pay_Svc" and stub["sf_type"] == "ExternalService"
    assert [e["target"] for e in _callouts(data)] == ["externalservice_pay_svc"]
    assert _flow_block(data)["unresolved"] == 2


def test_registration_without_a_credential_is_unresolved(tmp_path):
    project = _copy(tmp_path)
    reg = project / "force-app/main/default/externalServiceRegistrations/Pay_Svc.externalServiceRegistration-meta.xml"
    reg.write_text(reg.read_text().replace("<namedCredential>Pay_NC</namedCredential>", ""), encoding="utf-8")
    data = _build(project, tmp_path / "out")
    assert [e["target"] for e in _callouts(data)] == ["externalservice_pay_svc"]
    assert _flow_block(data)["unresolved"] == 2


def test_credential_missing_from_the_repo_still_gets_a_stub_and_a_composed_edge(tmp_path):
    project = _copy(tmp_path, ("namedCredentials/Pay_NC.namedCredential-meta.xml",))
    data = _build(project, tmp_path / "out")
    stub = next(n for n in data["nodes"] if n["id"] == "namedcredential_pay_nc")
    assert stub["stub"] is True and stub["label"] == "Pay_NC"
    assert "namedcredential_pay_nc" in {e["target"] for e in _callouts(data)}


def test_legacy_suffix_still_works(tmp_path):
    project = _copy(tmp_path)
    reg = project / "force-app/main/default/externalServiceRegistrations/Pay_Svc.externalServiceRegistration-meta.xml"
    reg.rename(reg.with_name("Pay_Svc.externalService-meta.xml"))
    data = _build(project, tmp_path / "out")
    assert "namedcredential_pay_nc" in {e["target"] for e in _callouts(data)}


def test_two_credentials_in_one_registration_are_not_guessed(tmp_path):
    project = _copy(tmp_path)
    reg = project / "force-app/main/default/externalServiceRegistrations/Pay_Svc.externalServiceRegistration-meta.xml"
    # the extractor reads the first <namedCredential>; add a second service file naming another credential via a
    # duplicate registration id is impossible, so exercise the composer directly
    from graphify_sf.extract import _compose_external_service_callouts

    nodes = [{"id": "externalservice_pay_svc", "sf_type": "ExternalService"}]
    edges = [
        {"source": "externalservice_pay_svc", "target": "namedcredential_a", "relation": "uses"},
        {"source": "externalservice_pay_svc", "target": "namedcredential_b", "relation": "uses"},
        {
            "source": "flow_f",
            "target": "externalservice_pay_svc",
            "relation": "makes_callout",
            "source_file": "/x/F.flow-meta.xml",
            "site_count": 3,
        },
    ]
    assert _compose_external_service_callouts(nodes, edges) == {"/x/F.flow-meta.xml": 3}
    assert len(edges) == 3 and reg.exists()


def test_operation_name_with_an_escaped_dot_keeps_its_service(tmp_path):
    from graphify_sf.extract.flow import extract_flow

    p = tmp_path / "F.flow-meta.xml"
    p.write_text(
        '<Flow xmlns="http://soap.sforce.com/2006/04/metadata"><actionCalls><name>A</name>'
        "<actionName>CodeGenieForSupport.postChatx2epostMessage</actionName><actionType>externalService</actionType>"
        "</actionCalls></Flow>",
        encoding="utf-8",
    )
    (edge,) = [e for e in extract_flow(p)["edges"] if e["relation"] == "makes_callout"]
    assert edge["target"] == "externalservice_codegenieforsupport"

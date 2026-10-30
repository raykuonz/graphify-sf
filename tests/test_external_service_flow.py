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


def _reg(project: Path, rel: str, body: str) -> None:
    path = project / "force-app/main/default" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<ExternalServiceRegistration xmlns="http://soap.sforce.com/2006/04/metadata">'
        f"<label>x</label>{body}<operations><active>true</active><name>charge</name></operations></ExternalServiceRegistration>",
        encoding="utf-8",
    )


def test_current_registrations_name_the_credential_in_namedcredentialreference(tmp_path):
    project = _copy(tmp_path)
    _reg(
        project,
        "externalServiceRegistrations/Pay_Svc.externalServiceRegistration-meta.xml",
        "<namedCredentialReference>Pay_NC</namedCredentialReference>",
    )
    data = _build(project, tmp_path / "out")
    assert "namedcredential_pay_nc" in {e["target"] for e in _callouts(data)}
    assert _flow_block(data)["unresolved"] == 0


def test_two_files_for_one_service_where_one_names_no_credential_are_not_composed(tmp_path):
    project = _copy(tmp_path)
    _reg(project, "legacy/Pay_Svc.externalService-meta.xml", "")  # same service id, no credential stated
    data = _build(project, tmp_path / "out")
    assert [e["target"] for e in _callouts(data)] == ["externalservice_pay_svc"]
    assert _flow_block(data)["unresolved"] == 2


def test_two_files_for_one_service_naming_different_credentials_are_not_composed(tmp_path):
    project = _copy(tmp_path)
    _reg(project, "legacy/Pay_Svc.externalService-meta.xml", "<namedCredential>Other_NC</namedCredential>")
    data = _build(project, tmp_path / "out")
    assert "namedcredential_pay_nc" not in {e["target"] for e in _callouts(data)}
    assert _flow_block(data)["unresolved"] == 2


def test_a_registration_naming_two_credentials_is_not_composed(tmp_path):
    project = _copy(tmp_path)
    _reg(
        project,
        "externalServiceRegistrations/Pay_Svc.externalServiceRegistration-meta.xml",
        "<namedCredential>Pay_NC</namedCredential><namedCredentialReference>Other_NC</namedCredentialReference>",
    )
    data = _build(project, tmp_path / "out")
    assert [e["target"] for e in _callouts(data)] == ["externalservice_pay_svc"]
    assert _flow_block(data)["unresolved"] == 2


def test_via_external_service_uses_the_registrations_spelling(tmp_path):
    from graphify_sf.extract.flow import extract_flow

    project = _copy(tmp_path)
    flow = project / "force-app/main/default/flows/Charge_Customer.flow-meta.xml"
    flow.write_text(flow.read_text().replace("Pay_Svc.charge", "PAY_SVC.charge"), encoding="utf-8")
    data = _build(project, tmp_path / "out")
    (nc_edge,) = [e for e in _callouts(data) if e["target"] == "namedcredential_pay_nc"]
    assert nc_edge["via_external_service"] == "Pay_Svc"
    assert extract_flow(flow)  # still parses


def test_multi_dot_or_bare_action_names_are_unresolved_sites(tmp_path):
    from graphify_sf.extract.flow import extract_flow

    for name in ("acme.Pay_Svc.charge", "Pay_Svc"):
        p = tmp_path / "F.flow-meta.xml"
        p.write_text(
            '<Flow xmlns="http://soap.sforce.com/2006/04/metadata"><actionCalls><name>A</name>'
            f"<actionName>{name}</actionName><actionType>externalService</actionType></actionCalls></Flow>",
            encoding="utf-8",
        )
        r = extract_flow(p)
        assert [e for e in r["edges"] if e["relation"] == "makes_callout"] == [], name
        assert (r["_sites"], r["_unresolved"]) == (1, 1), name


def test_registration_uses_edge_survives_a_prefix_guess_at_the_same_name(tmp_path):
    project = _copy(
        tmp_path, ("namedCredentials/Pay_NC.namedCredential-meta.xml", "flows/Charge_Customer.flow-meta.xml")
    )
    classes = project / "force-app/main/default/classes"
    classes.mkdir(parents=True)
    (classes / "Guess.cls").write_text(
        "public class Guess { String env; void go() { HttpRequest r = new HttpRequest(); r.setEndpoint('callout:Pay_NC' + env); } }",
        encoding="utf-8",
    )
    (classes / "Guess.cls-meta.xml").write_text("<ApexClass/>", encoding="utf-8")
    data = _build(project, tmp_path / "out")
    assert any(
        e["relation"] == "uses" and e["source"] == "externalservice_pay_svc" and e["target"] == "namedcredential_pay_nc"
        for e in data["links"]
    )
    assert any(n["id"] == "namedcredential_pay_nc" and n.get("stub") for n in data["nodes"])


def test_label_dedup_does_not_merge_two_real_credentials_with_similar_names():
    from graphify_sf.build import deduplicate_by_label

    a = {"id": "namedcredential_pay_nc", "label": "Pay_NC", "sf_type": "NamedCredential", "source_file": "/r/a"}
    b = {"id": "namedcredential_paync", "label": "PayNC", "sf_type": "NamedCredential", "source_file": "/r/b"}
    nodes, _ = deduplicate_by_label([a, b], [])
    assert {n["id"] for n in nodes} == {"namedcredential_pay_nc", "namedcredential_paync"}


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

"""0.6.0 E4: static resolution of Apex ``setEndpoint`` call sites (constants, concatenation, receivers, test context)."""

from __future__ import annotations

import json
from pathlib import Path

from graphify_sf.extract.apex import extract_apex_class, extract_apex_trigger


def _cls(tmp_path: Path, body: str, name: str = "Svc") -> dict:
    p = tmp_path / f"{name}.cls"
    p.write_text(body, encoding="utf-8")
    return extract_apex_class(p)


def _edges(result: dict) -> list[dict]:
    return [e for e in result["edges"] if e["relation"] == "makes_callout"]


def _by_target(result: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in _edges(result):
        out.setdefault(e["target"], []).append(e)
    return out


def _method(stmts: str, fields: str = "") -> str:
    return f"public class Svc {{ {fields} public void go() {{ HttpRequest req = new HttpRequest(); {stmts} }} }}"


# ── value rules ──────────────────────────────────────────────────────────────────────


def test_constant_plus_path_is_extracted_to_the_credential(tmp_path):
    r = _cls(
        tmp_path,
        _method("req.setEndpoint(BASE + '/v1/orders');", "private static final String BASE = 'callout:Acme_NC';"),
    )
    (edge,) = _edges(r)
    assert edge["target"] == "namedcredential_acme_nc"
    assert edge["confidence"] == "EXTRACTED"
    assert "inference_reason" not in edge


def test_bare_credential_literal_is_exact(tmp_path):
    (edge,) = _edges(_cls(tmp_path, _method("req.setEndpoint('callout:Bare_NC');")))
    assert edge["target"] == "namedcredential_bare_nc"
    assert edge["confidence"] == "EXTRACTED"


def test_concatenated_literals_resolve_to_the_joined_name(tmp_path):
    (edge,) = _edges(_cls(tmp_path, _method("req.setEndpoint('callout:Acme' + '_ERP');")))
    assert edge["target"] == "namedcredential_acme_erp"
    assert edge["confidence"] == "EXTRACTED"


def test_dynamic_suffix_after_the_credential_is_inferred(tmp_path):
    r = _cls(tmp_path, _method("req.setEndpoint('callout:Acme' + env);", "String env;"))
    (edge,) = _edges(r)
    assert edge["target"] == "namedcredential_acme"
    assert edge["confidence"] == "INFERRED"
    assert edge["inference_reason"] == "dynamic_suffix"


def test_delimiter_in_the_known_prefix_keeps_the_edge_extracted(tmp_path):
    (edge,) = _edges(_cls(tmp_path, _method("req.setEndpoint('callout:Acme/v1/' + id);", "String id;")))
    assert edge["confidence"] == "EXTRACTED"


def test_non_final_static_prefix_is_flagged(tmp_path):
    r = _cls(tmp_path, _method("req.setEndpoint('callout:Acme' + suffix);", "static String suffix = '_x';"))
    (edge,) = _edges(r)
    assert (edge["confidence"], edge["inference_reason"]) == ("INFERRED", "non_final_static")


def test_partial_host_yields_no_edge(tmp_path):
    r = _cls(tmp_path, _method("req.setEndpoint('https://api' + sub + '.example.com/x');", "String sub;"))
    assert _edges(r) == []
    assert r["_sites"] == 1 and r["_unresolved"] == 1


def test_literal_url_is_extracted_and_creates_the_endpoint_node(tmp_path):
    r = _cls(tmp_path, _method("req.setEndpoint('https://API.Example.com/x');"))
    (edge,) = _edges(r)
    assert edge["confidence"] == "EXTRACTED"
    node = next(n for n in r["nodes"] if n["sf_type"] == "ExternalEndpoint")
    assert node["label"] == "api.example.com"


def test_unresolvable_argument_is_a_site_but_not_an_edge(tmp_path):
    r = _cls(tmp_path, _method("req.setEndpoint(helper());", "String helper() { return 'x'; }"))
    assert _edges(r) == []
    assert (r["_sites"], r["_unresolved"]) == (1, 1)


# ── code vs comments/strings ─────────────────────────────────────────────────────────


def test_commented_and_in_string_calls_are_not_code(tmp_path):
    body = _method(
        "// req.setEndpoint('callout:Commented');\n"
        "/* req.setEndpoint('callout:Block'); */\n"
        "String s = 'req.setEndpoint(\\'callout:InString\\')';"
    )
    r = _cls(tmp_path, body)
    assert _edges(r) == []
    assert r["_sites"] == 0


# ── receivers ────────────────────────────────────────────────────────────────────────


def test_receiver_declared_as_another_type_is_not_a_callout(tmp_path):
    body = "public class Svc { public void go() { Builder b = new Builder(); b.setEndpoint('callout:Nope'); } }"
    r = _cls(tmp_path, body)
    assert _edges(r) == []
    assert r["_sites"] == 0


def test_unknown_receiver_is_inferred(tmp_path):
    r = _cls(tmp_path, "public class Svc { public void go(Thing t) { other.setEndpoint('callout:Maybe'); } }")
    (edge,) = _edges(r)
    assert (edge["confidence"], edge["inference_reason"]) == ("INFERRED", "receiver_unproven")


def test_new_httprequest_chain_is_a_proven_receiver(tmp_path):
    r = _cls(tmp_path, "public class Svc { void go() { new HttpRequest().setEndpoint('callout:Chain'); } }")
    (edge,) = _edges(r)
    assert edge["confidence"] == "EXTRACTED"


def test_qualified_httprequest_type_is_proven(tmp_path):
    r = _cls(
        tmp_path,
        "public class Svc { void go() { System.HttpRequest r = new System.HttpRequest(); r.setEndpoint('callout:Q'); } }",
    )
    (edge,) = _edges(r)
    assert edge["confidence"] == "EXTRACTED"


# ── test context ─────────────────────────────────────────────────────────────────────


def test_istest_class_method_and_testmethod_are_test_context(tmp_path):
    body = """
@IsTest
private class T1 { static void a() { HttpRequest r = new HttpRequest(); r.setEndpoint('callout:A'); } }
"""
    (e1,) = _edges(_cls(tmp_path, body, "T1"))
    assert e1["test_context"] is True

    body = """
public class T2 {
  @IsTest static void a() { HttpRequest r = new HttpRequest(); r.setEndpoint('callout:B'); }
  static void prod() { HttpRequest r = new HttpRequest(); r.setEndpoint('callout:C'); }
  static testMethod void legacy() { HttpRequest r = new HttpRequest(); r.setEndpoint('callout:D'); }
}
"""
    by = _by_target(_cls(tmp_path, body, "T2"))
    assert by["namedcredential_b"][0]["test_context"] is True
    assert "test_context" not in by["namedcredential_c"][0]
    assert by["namedcredential_d"][0]["test_context"] is True


# ── edge aggregation ─────────────────────────────────────────────────────────────────


def test_repeated_sites_aggregate_and_mixed_ones_stay_parallel(tmp_path):
    body = """
public class Svc {
  public void a() { HttpRequest r = new HttpRequest(); r.setEndpoint('callout:Same/1'); r.setEndpoint('callout:Same/2'); }
  public void b(String s) { HttpRequest r = new HttpRequest(); r.setEndpoint('callout:Same' + s); }
  @IsTest static void t() { HttpRequest r = new HttpRequest(); r.setEndpoint('callout:Same/3'); }
}
"""
    edges = _by_target(_cls(tmp_path, body))["namedcredential_same"]
    shapes = {(e["confidence"], e.get("test_context", False), e.get("inference_reason")): e for e in edges}
    assert set(shapes) == {
        ("EXTRACTED", False, None),
        ("INFERRED", False, "dynamic_suffix"),
        ("EXTRACTED", True, None),
    }
    assert shapes[("EXTRACTED", False, None)]["site_count"] == 2


def test_original_case_name_is_carried_for_stubs(tmp_path):
    (edge,) = _edges(_cls(tmp_path, _method("req.setEndpoint('callout:MiXed_Case');")))
    assert edge["_tgt_name"] == "MiXed_Case"


# ── triggers ─────────────────────────────────────────────────────────────────────────


def test_trigger_callouts_are_scanned(tmp_path):
    p = tmp_path / "Acc.trigger"
    p.write_text(
        "trigger Acc on Account (before insert) { HttpRequest r = new HttpRequest(); r.setEndpoint('callout:Trig_NC/x'); }",
        encoding="utf-8",
    )
    r = extract_apex_trigger(p)
    (edge,) = _edges(r)
    assert edge["target"] == "namedcredential_trig_nc"
    assert edge["confidence"] == "EXTRACTED"
    assert r["_sites"] == 1 and r["_unresolved"] == 0


# ── ledger fail-closed ───────────────────────────────────────────────────────────────


def test_a_result_without_the_sites_marker_counts_as_failed(tmp_path, monkeypatch):
    """An Apex extractor that forgets to report ``_sites`` must not be counted as analysed."""
    from graphify_sf import extract as ex
    from graphify_sf.detect import detect

    root = tmp_path / "proj" / "force-app" / "main" / "default" / "classes"
    root.mkdir(parents=True)
    (root / "Svc.cls").write_text(_method("req.setEndpoint('callout:X');"), encoding="utf-8")
    (root / "Svc.cls-meta.xml").write_text("<ApexClass/>", encoding="utf-8")

    def no_marker(path):
        return {"nodes": [], "edges": []}

    monkeypatch.setitem(ex._DISPATCH, ".cls", no_marker)
    result = ex.extract(detect(tmp_path / "proj"), parallel=False)
    block = result["analysis"]["callout-edges.apex"]
    assert block["status"] == "failed"
    assert (block["eligible"], block["analyzed"], block["failed"]) == (1, 0, 1)
    json.dumps(result["analysis"])  # serialisable

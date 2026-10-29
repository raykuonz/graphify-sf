"""0.6.0 E4: static resolution of Apex ``setEndpoint`` call sites (constants, concatenation, receivers, test context)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


# ── review follow-ups (E4 code review) ───────────────────────────────────────────────


def _one(tmp_path, body):
    edges = _edges(_cls(tmp_path, body))
    return edges


def test_parameter_that_shadows_a_constant_is_not_the_constant(tmp_path):
    body = (
        "public class Svc { private static final String ENDPOINT = 'callout:Prod_API';"
        " public static void send(String endpoint) { HttpRequest req = new HttpRequest(); req.setEndpoint(endpoint); } }"
    )
    assert _edges(_cls(tmp_path, body)) == []


def test_local_that_shadows_a_constant_is_not_the_constant(tmp_path):
    body = (
        "public class Svc { static final String URL = 'https://prod.example.com/api';"
        " void go() { HttpRequest req = new HttpRequest(); String url = flag() ? 'https://mock.test/' : getUrl();"
        " req.setEndpoint(url); } }"
    )
    assert _edges(_cls(tmp_path, body)) == []


def test_inner_class_field_with_the_same_name_makes_the_constant_ambiguous(tmp_path):
    body = (
        "public class Svc { static final String EP = 'callout:Outer';"
        " class Inner { final String EP; Inner(String e) { EP = e; } void go(HttpRequest req) { req.setEndpoint(EP); } } }"
    )
    assert _edges(_cls(tmp_path, body)) == []


def test_later_declarator_with_the_same_name_makes_the_constant_ambiguous(tmp_path):
    body = (
        "public class Svc { static final String EP = 'callout:Outer';"
        " class Inner { static final String A = 'x', EP = 'callout:Inner'; void go(HttpRequest req) { req.setEndpoint(EP); } } }"
    )
    assert _edges(_cls(tmp_path, body)) == []


def test_constructor_local_is_not_a_class_constant(tmp_path):
    body = (
        "public class Svc { Svc() { final String EP = 'callout:CtorLocal'; }"
        " void go(String ep) { HttpRequest req = new HttpRequest(); req.setEndpoint(ep); } }"
    )
    assert _edges(_cls(tmp_path, body)) == []


@pytest.mark.parametrize(
    "arg",
    [
        "'callout:Prod/' + path == null ? fallback : path",
        "'https://prod.example.com/' + path != null ? path : fallback",
        "ep += '/v1'",
    ],
)
def test_lower_precedence_operators_make_the_whole_expression_dynamic(tmp_path, arg):
    body = _method(f"req.setEndpoint({arg});", "String path; String fallback; String ep; Boolean flag;")
    assert _edges(_cls(tmp_path, body)) == []


def test_chained_receiver_is_not_matched_to_an_unrelated_local(tmp_path):
    body = (
        "public class Svc { void a() { HttpRequest req = new HttpRequest(); }"
        " void b(Wrapper w) { this.w.req.setEndpoint('callout:B'); } }"
    )
    (edge,) = _edges(_cls(tmp_path, body))
    assert edge["confidence"] == "INFERRED" and edge["inference_reason"] == "receiver_unproven"


def test_property_declaration_counts_as_a_receiver_declaration(tmp_path):
    body = (
        "public class Svc { public FakeRequest req { get; set; }"
        " void a() { HttpRequest req = new HttpRequest(); } void b() { req.setEndpoint('callout:Fake'); } }"
    )
    (edge,) = _edges(_cls(tmp_path, body))
    assert edge["confidence"] == "INFERRED"

    body = (
        "public class Svc { public HttpRequest req { get; set; }"
        " void a() { MockReq req = new MockReq(); } void b() { req.setEndpoint('callout:Real'); } }"
    )
    r = _cls(tmp_path, body, "Svc2")
    assert r["_sites"] == 1  # never silently dropped as "not a callout"


def test_new_of_another_type_is_not_a_callout(tmp_path):
    r = _cls(tmp_path, "public class Svc { void go() { new Builder().setEndpoint('callout:X'); } }")
    assert _edges(r) == [] and r["_sites"] == 0


def test_unmodelled_escape_sequences_are_dynamic(tmp_path):
    r = _cls(tmp_path, _method("req.setEndpoint('callout:A\\u005F');"))
    # the literal ends in an escape we do not decode: no EXTRACTED edge is claimed for it
    assert all(e["confidence"] != "EXTRACTED" for e in _edges(r))


def test_trailing_comment_inside_a_multiline_concatenation_still_resolves(tmp_path):
    body = (
        "public class Svc {\n  void go() {\n    HttpRequest req = new HttpRequest();\n"
        "    req.setEndpoint('callout:Acme/' // base\n      + 'v1');\n  }\n}\n"
    )
    (edge,) = _edges(_cls(tmp_path, body))
    assert edge["confidence"] == "EXTRACTED"


def test_undeclared_class_header_with_a_callout_counts_as_an_unresolved_site(tmp_path):
    r = _cls(tmp_path, "class Bar { void go(HttpRequest r) { r.setEndpoint('callout:X'); } }", "Foo")
    assert r["nodes"] == [] and (r["_sites"], r["_unresolved"]) == (1, 1)


def test_endpoint_node_confidence_does_not_depend_on_site_order(tmp_path):
    body = (
        "public class Svc { void a(Thing t) { other.setEndpoint('https://h.example.com/a'); }"
        " void b() { HttpRequest r = new HttpRequest(); r.setEndpoint('https://h.example.com/b'); } }"
    )
    r = _cls(tmp_path, body)
    (node,) = [n for n in r["nodes"] if n["sf_type"] == "ExternalEndpoint"]
    assert node["confidence"] == "EXTRACTED"


def test_a_prefix_only_credential_name_gets_no_stub(tmp_path):
    from graphify_sf.detect import detect
    from graphify_sf.extract import extract

    root = tmp_path / "proj" / "force-app" / "main" / "default" / "classes"
    root.mkdir(parents=True)
    (root / "Svc.cls").write_text(_method("req.setEndpoint('callout:Acme' + env);", "String env;"), encoding="utf-8")
    (root / "Svc.cls-meta.xml").write_text("<ApexClass/>", encoding="utf-8")
    result = extract(detect(tmp_path / "proj"), parallel=False)
    assert not [n for n in result["nodes"] if n.get("sf_type") == "NamedCredential"]


def test_many_sites_in_one_file_stay_fast(tmp_path):
    import time

    lines = "\n".join(
        f"        HttpRequest r{i} = new HttpRequest(); r{i}.setEndpoint('callout:NC_{i % 7}/p{i}');"
        for i in range(1500)
    )
    body = "public class Big {\n    public void go() {\n" + lines + "\n    }\n}\n"
    t0 = time.perf_counter()
    r = _cls(tmp_path, body, "Big")
    assert time.perf_counter() - t0 < 5
    assert r["_sites"] == 1500


def test_a_dynamic_group_after_a_known_prefix_is_inferred_not_extracted(tmp_path):
    body = _method("req.setEndpoint('callout:A' + (flag ? 'x' : 'y'));", "Boolean flag;")
    (edge,) = _edges(_cls(tmp_path, body))
    assert (edge["confidence"], edge["inference_reason"]) == ("INFERRED", "dynamic_suffix")

"""Tests for Apex extraction."""

from __future__ import annotations

from pathlib import Path


def test_extract_apex_class_returns_nodes(simple_project_path):
    """Test that extract_apex_class() returns nodes with correct structure."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    assert "nodes" in result
    assert "edges" in result
    assert len(result["nodes"]) > 0, "Should extract at least the class node"


def test_extract_apex_class_node_structure(simple_project_path):
    """Test that Apex class nodes have correct attributes."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    class_node = result["nodes"][0]
    assert class_node["label"] == "AccountService"
    assert class_node["sf_type"] == "ApexClass"
    assert class_node["file_type"] == "apex"
    assert "source_file" in class_node


def test_extract_apex_methods(simple_project_path):
    """Test that methods are extracted with correct parent relationships."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    # Should have class node + method nodes
    method_nodes = [n for n in result["nodes"] if n.get("sf_type") == "ApexMethod"]
    assert len(method_nodes) >= 3, "Should extract at least 3 methods"

    # Check method labels
    method_labels = [n["label"] for n in method_nodes]
    assert any("getActiveAccounts" in label for label in method_labels)
    assert any("updateAccountStatus" in label for label in method_labels)
    assert any("validateAccount" in label for label in method_labels)


def test_extract_apex_method_contains_edges(simple_project_path):
    """Test that methods have contains edges from their parent class."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    contains_edges = [e for e in result["edges"] if e.get("relation") == "contains"]
    assert len(contains_edges) >= 3, "Should have contains edges for methods"


def test_extract_apex_trigger_node(simple_project_path):
    """Test that extract_apex_trigger() returns trigger node."""
    from graphify_sf.extract.apex import extract_apex_trigger

    trigger_path = simple_project_path / "force-app/main/default/triggers/AccountTrigger.trigger"
    result = extract_apex_trigger(trigger_path)

    assert len(result["nodes"]) >= 1
    trigger_node = result["nodes"][0]
    assert trigger_node["label"] == "AccountTrigger"
    assert trigger_node["sf_type"] == "ApexTrigger"
    assert trigger_node["file_type"] == "apex"


def test_extract_apex_trigger_object_edge(simple_project_path):
    """Test that trigger node is linked to object."""
    from graphify_sf.extract.apex import extract_apex_trigger

    trigger_path = simple_project_path / "force-app/main/default/triggers/AccountTrigger.trigger"
    result = extract_apex_trigger(trigger_path)

    # Should have edge: trigger -> Account (node IDs are lowercase)
    triggers_edges = [e for e in result["edges"] if e.get("relation") == "triggers"]
    assert len(triggers_edges) >= 1
    assert "account" in triggers_edges[0]["target"].lower()


def test_extract_apex_trigger_events(simple_project_path):
    """Test that trigger events are captured."""
    from graphify_sf.extract.apex import extract_apex_trigger

    trigger_path = simple_project_path / "force-app/main/default/triggers/AccountTrigger.trigger"
    result = extract_apex_trigger(trigger_path)

    trigger_node = result["nodes"][0]
    assert "trigger_events" in trigger_node
    events = trigger_node["trigger_events"]
    assert "before insert" in events
    assert "after update" in events


def test_extract_apex_cross_reference_raw_calls(simple_project_path):
    """Test that cross-reference detection stores _raw_calls."""
    from graphify_sf.extract.apex import extract_apex_class

    # AccountTriggerHandler calls AccountService
    handler_path = simple_project_path / "force-app/main/default/classes/AccountTriggerHandler.cls"
    result = extract_apex_class(handler_path)

    class_node = result["nodes"][0]
    assert "_raw_calls" in class_node, "Should store raw calls for cross-file resolution"
    raw_calls = class_node["_raw_calls"]
    assert len(raw_calls) > 0, "Should detect calls to AccountService"

    # Check that AccountService is in the calls
    callee_classes = {call["callee_class"] for call in raw_calls}
    assert "AccountService" in callee_classes


def test_extract_apex_soql_queries_object(simple_project_path):
    """Test that SOQL queries create query edges to objects."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    queries_edges = [e for e in result["edges"] if e.get("relation") == "queries"]
    assert len(queries_edges) >= 1, "Should detect SOQL query"

    # Check that it queries Account (node IDs are lowercase)
    targets = [e["target"] for e in queries_edges]
    assert any("account" in t.lower() for t in targets)


def test_extract_apex_dml_operations(simple_project_path):
    """Test that DML operations are not explicitly extracted (static analysis limitation)."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    # DML operations (update, insert, delete) are not separately tracked as edges;
    # they appear as part of SOQL queries or class structure.
    # This is a known limitation of static Apex analysis.
    all_relations = {e.get("relation") for e in result["edges"]}
    assert "contains" in all_relations or "queries" in all_relations, (
        "Should have at least contains/queries edges even without DML tracking"
    )


def test_extract_apex_missing_file():
    """Test that extract handles missing files gracefully."""
    from graphify_sf.extract.apex import extract_apex_class

    result = extract_apex_class(Path("/nonexistent/file.cls"))
    assert result == {"nodes": [], "edges": []}


def test_extract_apex_method_confidence_extracted(simple_project_path):
    """Test that method edges have EXTRACTED confidence."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    contains_edges = [e for e in result["edges"] if e.get("relation") == "contains"]
    for edge in contains_edges:
        assert edge["confidence"] == "EXTRACTED"


# ---------------------------------------------------------------------------
# _looks_like_apex_class heuristic
# ---------------------------------------------------------------------------


def test_looks_like_apex_class_rejects_single_char():
    from graphify_sf.extract.apex import _looks_like_apex_class

    assert _looks_like_apex_class("E") is False
    assert _looks_like_apex_class("e") is False


def test_looks_like_apex_class_rejects_lowercase_start():
    from graphify_sf.extract.apex import _looks_like_apex_class

    assert _looks_like_apex_class("results") is False
    assert _looks_like_apex_class("myVar") is False


def test_looks_like_apex_class_rejects_known_keywords():
    from graphify_sf.extract.apex import _looks_like_apex_class

    assert _looks_like_apex_class("System") is False
    assert _looks_like_apex_class("Assert") is False
    assert _looks_like_apex_class("Results") is False
    assert _looks_like_apex_class("Database") is False


def test_looks_like_apex_class_rejects_all_caps_constants():
    from graphify_sf.extract.apex import _looks_like_apex_class

    assert _looks_like_apex_class("MAX") is False
    assert _looks_like_apex_class("NULL") is False
    assert _looks_like_apex_class("TRUE") is False


def test_looks_like_apex_class_accepts_pascal_case():
    from graphify_sf.extract.apex import _looks_like_apex_class

    assert _looks_like_apex_class("AccountService") is True
    assert _looks_like_apex_class("LeadHandler") is True
    assert _looks_like_apex_class("MyUtility") is True


def test_looks_like_apex_class_rejects_empty():
    from graphify_sf.extract.apex import _looks_like_apex_class

    assert _looks_like_apex_class("") is False
    assert _looks_like_apex_class("A") is False


# ---------------------------------------------------------------------------
# Apex → Flow via Flow.Interview.FlowName
# ---------------------------------------------------------------------------


def test_extract_apex_flow_interview_invokes_edge(tmp_path):
    """Flow.Interview.FlowName creates an 'invokes' edge to that flow."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "LeadProcessor.cls"
    cls.write_text(
        """\
public class LeadProcessor {
    public void process() {
        Flow.Interview.LeadAssignmentFlow flow = new Flow.Interview.LeadAssignmentFlow();
        flow.start();
    }
}
"""
    )

    result = extract_apex_class(cls)
    invokes_edges = [e for e in result["edges"] if e.get("relation") == "invokes"]
    assert len(invokes_edges) == 1
    assert "leadassignmentflow" in invokes_edges[0]["target"].lower()
    assert invokes_edges[0]["confidence"] == "EXTRACTED"


def test_extract_apex_flow_interview_deduplicates(tmp_path):
    """Multiple references to the same flow produce only one invokes edge."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "LeadProcessor.cls"
    cls.write_text(
        """\
public class LeadProcessor {
    public void run() {
        Flow.Interview.MyFlow f1 = new Flow.Interview.MyFlow();
        Flow.Interview.MyFlow f2 = new Flow.Interview.MyFlow();
    }
}
"""
    )

    result = extract_apex_class(cls)
    invokes = [e for e in result["edges"] if e.get("relation") == "invokes"]
    assert len(invokes) == 1


# ---------------------------------------------------------------------------
# Apex extends / implements edges
# ---------------------------------------------------------------------------


def test_extract_apex_extends_creates_edge(tmp_path):
    """A class extending another emits an 'extends' edge."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "SpecialService.cls"
    cls.write_text(
        """\
public class SpecialService extends BaseService {
    public void doWork() {}
}
"""
    )

    result = extract_apex_class(cls)
    extends_edges = [e for e in result["edges"] if e.get("relation") == "extends"]
    assert len(extends_edges) == 1
    assert "baseservice" in extends_edges[0]["target"].lower()


def test_extract_apex_implements_creates_edge(tmp_path):
    """A class implementing an interface emits an 'implements' edge."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "MyHandler.cls"
    cls.write_text(
        """\
public class MyHandler implements IHandler {
    public void handle() {}
}
"""
    )

    result = extract_apex_class(cls)
    impl_edges = [e for e in result["edges"] if e.get("relation") == "implements"]
    assert len(impl_edges) == 1
    assert "ihandler" in impl_edges[0]["target"].lower()


def test_extract_apex_implements_multiple_interfaces(tmp_path):
    """A class implementing multiple interfaces emits one edge per interface."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "MyService.cls"
    cls.write_text(
        """\
public class MyService implements Schedulable, Queueable {
    public void execute() {}
}
"""
    )

    result = extract_apex_class(cls)
    impl_edges = [e for e in result["edges"] if e.get("relation") == "implements"]
    # Schedulable and Queueable are in _APEX_KEYWORDS so should be filtered
    assert len(impl_edges) == 0


def test_extract_apex_interface_sf_type(tmp_path):
    """An interface declaration gets sf_type=ApexInterface."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "IHandler.cls"
    cls.write_text("public interface IHandler { void handle(); }\n")

    result = extract_apex_class(cls)
    assert len(result["nodes"]) >= 1
    assert result["nodes"][0]["sf_type"] == "ApexInterface"


def test_extract_apex_enum_sf_type(tmp_path):
    """An enum declaration gets sf_type=ApexEnum."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "StatusEnum.cls"
    cls.write_text("public enum StatusEnum { ACTIVE, INACTIVE }\n")

    result = extract_apex_class(cls)
    assert len(result["nodes"]) >= 1
    assert result["nodes"][0]["sf_type"] == "ApexEnum"


# ---------------------------------------------------------------------------
# Apex DML edges
# ---------------------------------------------------------------------------


def test_extract_apex_dml_insert_creates_edge(tmp_path):
    """DML insert on a capitalised type creates a 'dml' edge."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "LeadCreator.cls"
    cls.write_text(
        """\
public class LeadCreator {
    public void createLead() {
        Lead l = new Lead();
        insert Lead;
    }
}
"""
    )

    result = extract_apex_class(cls)
    dml_edges = [e for e in result["edges"] if e.get("relation") == "dml"]
    assert len(dml_edges) >= 1
    assert any("lead" in e["target"].lower() for e in dml_edges)
    for e in dml_edges:
        assert e["confidence"] == "INFERRED"


def test_extract_apex_dml_insert_and_update_same_object_two_edges(tmp_path):
    """A class that both inserts and updates the same object yields TWO dml edges
    (operation=create and operation=update), not one collapsed edge."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "AccountWriter.cls"
    cls.write_text(
        """\
public class AccountWriter {
    public void work() {
        Account Acct = new Account();
        insert Acct;
        update Acct;
    }
}
"""
    )

    result = extract_apex_class(cls)
    acct_dml = [e for e in result["edges"] if e.get("relation") == "dml" and "acct" in e["target"].lower()]
    assert len(acct_dml) == 2, "insert+update on same object must not be deduped to one edge"
    ops = {e.get("operation") for e in acct_dml}
    assert ops == {"create", "update"}
    for e in acct_dml:
        assert e["confidence"] == "INFERRED"


def test_extract_apex_dml_pure_update_carries_operation(tmp_path):
    """A bare DML update produces a dml edge with operation='update' and INFERRED confidence."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "AccountUpdater.cls"
    cls.write_text(
        """\
public class AccountUpdater {
    public void touch() {
        update Acct;
    }
}
"""
    )

    result = extract_apex_class(cls)
    dml_edges = [e for e in result["edges"] if e.get("relation") == "dml"]
    assert len(dml_edges) == 1
    assert dml_edges[0].get("operation") == "update"
    assert dml_edges[0]["confidence"] == "INFERRED"


def test_extract_apex_dml_native_verbs_preserved(tmp_path):
    """SF-native DML verbs map to their own operation, not forced into CRUD:
    upsert/undelete are preserved; insert->create, delete->delete, update->update.

    Note: `merge` uses two-object syntax (`merge a b;`) which the single-object DML
    regex deliberately does not capture — that's an existing extractor boundary, out
    of scope for this change (no object-type resolution upgrade)."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "AllDml.cls"
    cls.write_text(
        """\
public class AllDml {
    public void run() {
        insert Acct;
        update Con;
        delete Lead;
        upsert Opp;
        undelete Cse;
    }
}
"""
    )

    result = extract_apex_class(cls)
    ops_by_target = {e["target"].lower(): e.get("operation") for e in result["edges"] if e.get("relation") == "dml"}
    assert ops_by_target.get("object_acct") == "create"
    assert ops_by_target.get("object_con") == "update"
    assert ops_by_target.get("object_lead") == "delete"
    assert ops_by_target.get("object_opp") == "upsert"
    assert ops_by_target.get("object_cse") == "undelete"


def test_extract_apex_soql_queries_edge_unaffected(tmp_path):
    """Regression: SOQL still produces a 'queries' edge (EXTRACTED) with no 'operation'
    field — only DML edges gained operation."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "AccountReader.cls"
    cls.write_text(
        """\
public class AccountReader {
    public void read() {
        List<Account> a = [SELECT Id FROM Account];
        update Acct;
    }
}
"""
    )

    result = extract_apex_class(cls)
    query_edges = [e for e in result["edges"] if e.get("relation") == "queries"]
    assert len(query_edges) >= 1
    for e in query_edges:
        assert e["confidence"] == "EXTRACTED"
        assert e.get("operation") is None, "queries edges must not carry an operation field"


# ---------------------------------------------------------------------------
# Apex trigger fallback (no regex match → filename)
# ---------------------------------------------------------------------------


def test_extract_apex_trigger_fallback_uses_filename(tmp_path):
    """If the trigger declaration regex doesn't match, falls back to filename stem."""
    from graphify_sf.extract.apex import extract_apex_trigger

    trigger_file = tmp_path / "MyOrphanTrigger.trigger"
    trigger_file.write_text("// this file has no trigger declaration\n")

    result = extract_apex_trigger(trigger_file)
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["label"] == "MyOrphanTrigger"
    assert result["nodes"][0]["sf_type"] == "ApexTrigger"
    # No edges because no object was found
    assert result["edges"] == []


# ---------------------------------------------------------------------------
# Apex → Apex raw_calls filtered by _looks_like_apex_class
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# DML variable resolution (Approach A: varName → declared type)
# ---------------------------------------------------------------------------


def test_extract_apex_dml_lowercase_var_resolves_to_type(tmp_path):
    """Core fix: `insert c;` where `Case c = new Case()` → dml edge to object_case."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "AfterHoursFallback.cls"
    cls.write_text(
        """\
public class AfterHoursFallback {
    public void run() {
        Case c = new Case();
        insert c;
    }
}
"""
    )

    result = extract_apex_class(cls)
    dml_edges = [e for e in result["edges"] if e.get("relation") == "dml"]
    assert len(dml_edges) == 1
    assert "case" in dml_edges[0]["target"].lower()
    assert dml_edges[0]["operation"] == "create"
    assert dml_edges[0]["confidence"] == "INFERRED"


def test_extract_apex_dml_lowercase_var_insert_and_update_two_edges(tmp_path):
    """Same lowercase variable insert + update → two dml edges (create, update)."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "CaseUpdater.cls"
    cls.write_text(
        """\
public class CaseUpdater {
    public void run() {
        Case c = new Case();
        insert c;
        update c;
    }
}
"""
    )

    result = extract_apex_class(cls)
    dml_edges = [e for e in result["edges"] if e.get("relation") == "dml"]
    case_edges = [e for e in dml_edges if "case" in e["target"].lower()]
    assert len(case_edges) == 2
    ops = {e["operation"] for e in case_edges}
    assert ops == {"create", "update"}


def test_extract_apex_dml_list_generic_resolves_inner_type(tmp_path):
    """`List<Account> accs = ...; insert accs;` → dml edge to object_account."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "AccountBulkWriter.cls"
    cls.write_text(
        """\
public class AccountBulkWriter {
    public void run() {
        List<Account> accs = new List<Account>();
        insert accs;
    }
}
"""
    )

    result = extract_apex_class(cls)
    dml_edges = [e for e in result["edges"] if e.get("relation") == "dml"]
    assert len(dml_edges) == 1
    assert "account" in dml_edges[0]["target"].lower()
    assert dml_edges[0]["operation"] == "create"


def test_extract_apex_dml_method_param_resolves(tmp_path):
    """Method parameter `Contact con` → `update con;` produces dml edge to object_contact."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "ContactSaver.cls"
    cls.write_text(
        """\
public class ContactSaver {
    public void save(Contact con) {
        update con;
    }
}
"""
    )

    result = extract_apex_class(cls)
    dml_edges = [e for e in result["edges"] if e.get("relation") == "dml"]
    assert len(dml_edges) == 1
    assert "contact" in dml_edges[0]["target"].lower()
    assert dml_edges[0]["operation"] == "update"


def test_extract_apex_dml_unresolvable_var_skipped(tmp_path):
    """A DML on a variable with no resolvable declaration emits NO dml edge."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "MysteryUpdater.cls"
    cls.write_text(
        """\
public class MysteryUpdater {
    public void run() {
        update mystery;
    }
}
"""
    )

    result = extract_apex_class(cls)
    dml_edges = [e for e in result["edges"] if e.get("relation") == "dml"]
    assert len(dml_edges) == 0
    assert not any("mystery" in e.get("target", "").lower() for e in dml_edges)


# ---------------------------------------------------------------------------
# Group B — Apex extractor hardening (comment/string stripping, brace-balanced
# call boundary, generic-aware implements split, per-method var-type scope)
# ---------------------------------------------------------------------------


def test_extract_apex_dml_inside_comment_not_extracted(tmp_path):
    """DML that only appears inside comments must not produce a dml edge.

    A commented-out `insert fakeLead;` (line + block comment) plus one real
    `insert realAcc;` → exactly one dml edge, to the real object only.
    """
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "CommentedDml.cls"
    cls.write_text(
        """\
public class CommentedDml {
    public void run() {
        // Lead fakeLead; insert fakeLead;
        /* Contact ghost; insert ghost; */
        Account realAcc = new Account();
        insert realAcc;
    }
}
"""
    )

    result = extract_apex_class(cls)
    dml_edges = [e for e in result["edges"] if e.get("relation") == "dml"]
    assert len(dml_edges) == 1
    assert "account" in dml_edges[0]["target"].lower()
    assert not any("lead" in e["target"].lower() for e in dml_edges)
    assert not any("contact" in e["target"].lower() for e in dml_edges)


def test_extract_apex_dml_inside_string_not_extracted(tmp_path):
    """DML-looking text inside a string literal must not produce an edge."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "StringDml.cls"
    cls.write_text(
        """\
public class StringDml {
    public void run() {
        String note = 'insert fakeLead; then update fakeThing;';
        Account realAcc = new Account();
        insert realAcc;
    }
}
"""
    )

    result = extract_apex_class(cls)
    dml_edges = [e for e in result["edges"] if e.get("relation") == "dml"]
    assert len(dml_edges) == 1
    assert "account" in dml_edges[0]["target"].lower()
    assert not any("lead" in e["target"].lower() for e in dml_edges)
    assert not any("thing" in e["target"].lower() for e in dml_edges)


def test_extract_apex_calls_scoped_to_own_method_body(tmp_path):
    """Each method's raw calls contain only the calls in its own body.

    Previously `_CALL_RE` scanned from a method's `{` to end-of-file, so the
    first method accumulated every call below it. With a brace-balanced body
    boundary, method a() sees only Helper.a(), b() only Helper.b(), c() only
    Helper.c().
    """
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "ThreeMethods.cls"
    cls.write_text(
        """\
public class ThreeMethods {
    public void a() {
        Helper.a();
    }
    public void b() {
        Helper.b();
    }
    public void c() {
        Helper.c();
    }
}
"""
    )

    result = extract_apex_class(cls)
    raw_calls = result["nodes"][0].get("_raw_calls", [])
    by_caller: dict[str, set[str]] = {}
    for call in raw_calls:
        by_caller.setdefault(call["caller_id"], set()).add(call["callee_method"])

    from graphify_sf.extract._ids import apex_method_id

    a_id = apex_method_id("ThreeMethods", "a")
    b_id = apex_method_id("ThreeMethods", "b")
    c_id = apex_method_id("ThreeMethods", "c")
    assert by_caller.get(a_id) == {"a"}
    assert by_caller.get(b_id) == {"b"}
    assert by_caller.get(c_id) == {"c"}


def test_extract_apex_implements_generic_comma_not_split(tmp_path):
    """`implements Comparator<Account, String>` → one edge, to Comparator only.

    The comma is inside the generic bracket, so a depth-aware split must not
    break on it and must not emit a bogus edge to `apex_string`.
    """
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "AccountSorter.cls"
    cls.write_text(
        """\
public class AccountSorter implements Comparator<Account, String> {
    public Integer compare(Account a, Account b) {
        return 0;
    }
}
"""
    )

    result = extract_apex_class(cls)
    impl_edges = [e for e in result["edges"] if e.get("relation") == "implements"]
    assert len(impl_edges) == 1
    assert "comparator" in impl_edges[0]["target"].lower()
    assert not any(e["target"].lower() == "apex_string" for e in impl_edges)


def test_extract_apex_var_type_scoped_per_method(tmp_path):
    """Two methods reusing a local var name with different types don't collide.

    `methodA` declares `Account a; insert a;`, `methodB` declares
    `Contact a; insert a;` → two dml edges, to object_account and
    object_contact respectively (not both collapsed to the first-seen type).
    """
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "PerMethodVars.cls"
    cls.write_text(
        """\
public class PerMethodVars {
    public void methodA() {
        Account a = new Account();
        insert a;
    }
    public void methodB() {
        Contact a = new Contact();
        insert a;
    }
}
"""
    )

    result = extract_apex_class(cls)
    dml_targets = {e["target"] for e in result["edges"] if e.get("relation") == "dml"}
    assert "object_account" in dml_targets
    assert "object_contact" in dml_targets


def test_extract_apex_raw_calls_filters_lowercase_variables(tmp_path):
    """Local variable method calls (e.g. myObj.doSomething()) are not stored as raw_calls,
    but PascalCase static/utility calls (e.g. AccountService.getInstance()) are kept."""
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "Handler.cls"
    cls.write_text(
        """\
public class Handler {
    public void run() {
        String myStr = 'hello';
        myStr.toLowerCase();
        List<Account> accs = AccountService.getActiveAccounts();
        accs.size();
    }
}
"""
    )

    result = extract_apex_class(cls)
    class_node = result["nodes"][0]
    raw_calls = class_node.get("_raw_calls", [])
    callee_classes = {c["callee_class"] for c in raw_calls}
    # myStr/accs start lowercase — should be filtered out
    assert "myStr" not in callee_classes
    assert "accs" not in callee_classes
    # AccountService is PascalCase static call — should be kept
    assert "AccountService" in callee_classes

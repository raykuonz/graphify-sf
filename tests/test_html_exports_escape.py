"""Node text comes from project files; HTML exports must never parse it as markup."""

from __future__ import annotations

import re
import shutil
import subprocess

import networkx as nx
import pytest

HOSTILE = '</script><img src=x onerror=alert(1)>"]'


def _graph() -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    G.add_node("a", label=HOSTILE, sf_type="ApexClass", source_file="/p/A.cls")
    G.add_node("b", label="Plain", sf_type="Flow", source_file="/p/B.flow-meta.xml")
    G.add_edge("a", "b", relation="calls", confidence="EXTRACTED")
    return G


def test_tree_html_cannot_break_out_of_script_or_inject_tooltip_markup(tmp_path):
    from graphify_sf.export import to_tree_html

    out = tmp_path / "tree.html"
    to_tree_html(_graph(), {0: ["a", "b"]}, str(out), {0: HOSTILE})
    html = out.read_text(encoding="utf-8")

    assert "tooltip.innerHTML" not in html
    assert "tooltip.textContent" in html or "createTextNode" in html
    # The only closing script tags are the template's own; the payload's is escaped.
    assert html.count("</script>") == len(re.findall(r"<script\b", html))
    assert "\\u003c/script" in html


def test_tree_html_survives_an_html_comment_opener_in_node_text(tmp_path):
    from graphify_sf.export import to_tree_html

    G = _graph()
    G.nodes["a"]["label"] = "<!--<script>"
    out = tmp_path / "tree.html"
    to_tree_html(G, {0: ["a", "b"]}, str(out), {0: "C0"})
    script = re.findall(r"<script>(.*?)</script>", out.read_text(encoding="utf-8"), re.S)[-1]

    assert "<!--" not in script
    assert "<script" not in script


def test_callflow_html_escapes_node_text(tmp_path):
    from graphify_sf.export import to_callflow_html

    out = tmp_path / "callflow.html"
    to_callflow_html(_graph(), str(out))
    html = out.read_text(encoding="utf-8")

    assert "<img src=x" not in html
    assert "&lt;img src=x" in html
    assert html.count("</script>") == len(re.findall(r"<script\b", html))


def test_callflow_html_keeps_quotes_inside_mermaid_labels(tmp_path):
    from graphify_sf.export import to_callflow_html

    G = _graph()
    G.nodes["b"]["label"] = 'Say "hi"'
    out = tmp_path / "callflow.html"
    to_callflow_html(G, str(out))

    # A raw quote would end the Mermaid label string early; Mermaid's entity form keeps it text.
    assert "Say #quot;hi#quot;" in out.read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to parse the generated JavaScript")
def test_tree_html_script_is_valid_javascript(tmp_path):
    from graphify_sf.export import to_tree_html

    out = tmp_path / "tree.html"
    to_tree_html(_graph(), {0: ["a", "b"]}, str(out), {0: "C0"})
    scripts = re.findall(r"<script>(.*?)</script>", out.read_text(encoding="utf-8"), re.S)
    js = tmp_path / "tree.js"
    js.write_text(scripts[-1], encoding="utf-8")

    result = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr

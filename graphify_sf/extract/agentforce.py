"""Agentforce metadata extractors (Bot, BotVersion, GenAiPlugin, GenAiFunction,
GenAiPlannerBundle, AiAuthoringBundle, PromptTemplate).

SFDX directory layout for bots:
  bots/AgentName/AgentName.bot-meta.xml
  bots/AgentName/v1.botVersion-meta.xml

All other Agentforce types live in their own top-level directories:
  genAiPlugins/MyPlugin.genAiPlugin-meta.xml
  genAiFunctions/MyFunction.genAiFunction-meta.xml
  genAiPlannerBundles/MyPlanner.genAiPlannerBundle-meta.xml
  aiAuthoringBundles/MyBundle.aiAuthoringBundle-meta.xml
  promptTemplates/MyTemplate.promptTemplate-meta.xml
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ._ids import (
    apex_class_id,
    bot_id,
    bot_version_id,
    flow_id,
    gen_ai_function_id,
    gen_ai_planner_id,
    gen_ai_plugin_id,
    object_id,
    prompt_template_id,
)

_SF_NS = "http://soap.sforce.com/2006/04/metadata"


# ---------------------------------------------------------------------------
# Shared XML helpers (mirrors flow.py pattern)
# ---------------------------------------------------------------------------


def _find_text(el: ET.Element, tag: str, ns: str = "") -> str | None:
    """Find a direct child element and return its text."""
    if ns:
        child = el.find(f"{{{ns}}}{tag}")
        if child is None:
            child = el.find(tag)
    else:
        child = el.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _find_all(root: ET.Element, tag: str, ns: str = "") -> list[ET.Element]:
    """Find all descendants with the given tag, with/without namespace."""
    if ns:
        result = root.findall(f".//{{{ns}}}{tag}")
        if not result:
            result = root.findall(f".//{tag}")
    else:
        result = root.findall(f".//{tag}")
    return result


def _make_edge(src: str, tgt: str, relation: str, confidence: str, source_file: str) -> dict:
    return {
        "source": src,
        "target": tgt,
        "relation": relation,
        "confidence": confidence,
        "source_file": source_file,
        "source_location": None,
        "weight": 1.0,
        "_src": src,
        "_tgt": tgt,
    }


def _stem_strip(path: Path, suffix: str) -> str:
    """Strip a compound suffix from path.name and return the stem."""
    name = path.name
    if name.endswith(suffix):
        return name[: -len(suffix)]
    # Fallback: strip last two suffixes (e.g. .bot-meta.xml → name)
    stem = path.stem
    if stem.endswith(".bot-meta") or stem.endswith("-meta"):
        stem = stem.rsplit("-meta", 1)[0]
    return stem


def _detect_ns(root_el: ET.Element) -> str:
    """Extract XML namespace from root element tag, or empty string."""
    if root_el.tag.startswith("{"):
        return root_el.tag.split("}")[0][1:]
    return ""


def _parse_xml(path: Path):
    """Parse XML file; return (root_element, ns) or raise on failure."""
    tree = ET.parse(str(path))
    root_el = tree.getroot()
    return root_el, _detect_ns(root_el)


# ---------------------------------------------------------------------------
# Bot  (.bot-meta.xml)
# ---------------------------------------------------------------------------


def extract_bot(path: Path) -> dict:
    """Extract the top-level Bot (Agentforce agent) definition.

    A Bot node is created.  BotVersion files living in the same directory
    are linked via ``contains`` edges when they are later extracted — the
    ``bot_version_id`` ID function encodes the bot name in the version ID
    so the cross-reference resolver can connect them automatically.
    """
    str_path = str(path)
    nodes: list[dict] = []
    edges: list[dict] = []

    bot_name = _stem_strip(path, ".bot-meta.xml")
    b_id = bot_id(bot_name)

    try:
        root_el, ns = _parse_xml(path)
    except (ET.ParseError, FileNotFoundError, OSError):
        return {"nodes": [], "edges": []}

    label = _find_text(root_el, "label", ns) or bot_name
    description = _find_text(root_el, "description", ns) or ""
    bot_user = _find_text(root_el, "botUser", ns) or ""

    nodes.append(
        {
            "id": b_id,
            "label": label,
            "sf_type": "Bot",
            "file_type": "agentforce",
            "source_file": str_path,
            "source_location": None,
            **({"description": description} if description else {}),
            **({"bot_user": bot_user} if bot_user else {}),
        }
    )

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# BotVersion  (.botVersion-meta.xml)
# ---------------------------------------------------------------------------


def extract_bot_version(path: Path) -> dict:
    """Extract a Bot version and its links to topics, flows, and planners.

    The bot name is inferred from the parent directory name
    (``bots/AgentName/v1.botVersion-meta.xml`` → bot_name = AgentName).
    """
    str_path = str(path)
    nodes: list[dict] = []
    edges: list[dict] = []

    version_name = _stem_strip(path, ".botVersion-meta.xml")
    # Bot name comes from the containing directory (e.g. bots/AgentName/)
    bot_name = path.parent.name
    bv_id = bot_version_id(bot_name, version_name)
    b_id = bot_id(bot_name)

    try:
        root_el, ns = _parse_xml(path)
    except (ET.ParseError, FileNotFoundError, OSError):
        return {"nodes": [], "edges": []}

    label = _find_text(root_el, "label", ns) or f"{bot_name} {version_name}"
    description = _find_text(root_el, "description", ns) or ""
    agent_type = _find_text(root_el, "agentType", ns) or ""

    nodes.append(
        {
            "id": bv_id,
            "label": label,
            "sf_type": "BotVersion",
            "file_type": "agentforce",
            "source_file": str_path,
            "source_location": None,
            **({"description": description} if description else {}),
            **({"agent_type": agent_type} if agent_type else {}),
        }
    )

    # Bot → BotVersion edge
    edges.append(_make_edge(b_id, bv_id, "contains", "EXTRACTED", str_path))

    # Conversation definition (an Orchestrator Flow)
    conv_flow = _find_text(root_el, "conversationDefinition", ns)
    if conv_flow:
        edges.append(_make_edge(bv_id, flow_id(conv_flow), "invokes", "EXTRACTED", str_path))

    # GenAiPlugin references  (<genAiPlugins><genAiPlugin>ApiName</genAiPlugin>...)
    for el in _find_all(root_el, "genAiPlugins", ns):
        plugin_name = _find_text(el, "genAiPlugin", ns)
        if plugin_name:
            edges.append(_make_edge(bv_id, gen_ai_plugin_id(plugin_name), "references", "EXTRACTED", str_path))

    # Planner reference  (<planner><genAiPlannerBundle>ApiName</genAiPlannerBundle>...)
    for planner_el in _find_all(root_el, "planner", ns):
        planner_name = _find_text(planner_el, "genAiPlannerBundle", ns)
        if planner_name:
            edges.append(_make_edge(bv_id, gen_ai_planner_id(planner_name), "references", "EXTRACTED", str_path))

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# GenAiPlugin  (.genAiPlugin-meta.xml)  — Topic
# ---------------------------------------------------------------------------


def extract_gen_ai_plugin(path: Path) -> dict:
    """Extract a GenAiPlugin (Agentforce Topic) and its function members."""
    str_path = str(path)
    nodes: list[dict] = []
    edges: list[dict] = []

    plugin_name = _stem_strip(path, ".genAiPlugin-meta.xml")
    p_id = gen_ai_plugin_id(plugin_name)

    try:
        root_el, ns = _parse_xml(path)
    except (ET.ParseError, FileNotFoundError, OSError):
        return {"nodes": [], "edges": []}

    label = _find_text(root_el, "masterLabel", ns) or plugin_name
    description = _find_text(root_el, "description", ns) or ""
    plugin_type = _find_text(root_el, "pluginType", ns) or ""

    nodes.append(
        {
            "id": p_id,
            "label": label,
            "sf_type": "GenAiPlugin",
            "file_type": "agentforce",
            "source_file": str_path,
            "source_location": None,
            **({"description": description} if description else {}),
            **({"plugin_type": plugin_type} if plugin_type else {}),
        }
    )

    # Function members  (<functions><functionName>ApiName</functionName>...)
    for fn_el in _find_all(root_el, "functions", ns):
        fn_name = _find_text(fn_el, "functionName", ns)
        if fn_name:
            edges.append(_make_edge(p_id, gen_ai_function_id(fn_name), "contains", "EXTRACTED", str_path))

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# GenAiFunction  (.genAiFunction-meta.xml)  — Action
# ---------------------------------------------------------------------------


def extract_gen_ai_function(path: Path) -> dict:
    """Extract a GenAiFunction (Agentforce Action) and its Apex/Flow target."""
    str_path = str(path)
    nodes: list[dict] = []
    edges: list[dict] = []

    fn_name = _stem_strip(path, ".genAiFunction-meta.xml")
    fn_id = gen_ai_function_id(fn_name)

    try:
        root_el, ns = _parse_xml(path)
    except (ET.ParseError, FileNotFoundError, OSError):
        return {"nodes": [], "edges": []}

    label = _find_text(root_el, "masterLabel", ns) or fn_name
    description = _find_text(root_el, "description", ns) or ""
    action_type = _find_text(root_el, "invocableActionType", ns) or ""
    action_name = _find_text(root_el, "invocableActionName", ns) or ""

    nodes.append(
        {
            "id": fn_id,
            "label": label,
            "sf_type": "GenAiFunction",
            "file_type": "agentforce",
            "source_file": str_path,
            "source_location": None,
            **({"description": description} if description else {}),
            **({"action_type": action_type} if action_type else {}),
        }
    )

    # Invocable action target
    if action_name:
        if action_type in ("apex", "apexAction"):
            target_id = apex_class_id(action_name)
        elif action_type in ("flow", "Flow"):
            target_id = flow_id(action_name)
        else:
            # Unrecognised type — still link with INFERRED confidence
            target_id = apex_class_id(action_name)
            edges.append(_make_edge(fn_id, target_id, "invokes", "INFERRED", str_path))
            target_id = None  # skip the EXTRACTED edge below

        if target_id:
            edges.append(_make_edge(fn_id, target_id, "invokes", "EXTRACTED", str_path))

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# GenAiPlannerBundle  (.genAiPlannerBundle-meta.xml)
# ---------------------------------------------------------------------------


def extract_gen_ai_planner_bundle(path: Path) -> dict:
    """Extract a GenAiPlannerBundle (Agentforce Planner) and its plugin map."""
    str_path = str(path)
    nodes: list[dict] = []
    edges: list[dict] = []

    planner_name = _stem_strip(path, ".genAiPlannerBundle-meta.xml")
    pl_id = gen_ai_planner_id(planner_name)

    try:
        root_el, ns = _parse_xml(path)
    except (ET.ParseError, FileNotFoundError, OSError):
        return {"nodes": [], "edges": []}

    label = _find_text(root_el, "masterLabel", ns) or planner_name
    description = _find_text(root_el, "description", ns) or ""
    planner_type = _find_text(root_el, "plannerType", ns) or ""

    nodes.append(
        {
            "id": pl_id,
            "label": label,
            "sf_type": "GenAiPlannerBundle",
            "file_type": "agentforce",
            "source_file": str_path,
            "source_location": None,
            **({"description": description} if description else {}),
            **({"planner_type": planner_type} if planner_type else {}),
        }
    )

    # Sub-agent GenAiPlugin references
    # <subAgentDefinitions><genAiPlugin>ApiName</genAiPlugin>...
    for sub_el in _find_all(root_el, "subAgentDefinitions", ns):
        plugin_name = _find_text(sub_el, "genAiPlugin", ns)
        if plugin_name:
            edges.append(_make_edge(pl_id, gen_ai_plugin_id(plugin_name), "references", "EXTRACTED", str_path))

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# AiAuthoringBundle  (.aiAuthoringBundle-meta.xml)
# ---------------------------------------------------------------------------


def extract_ai_authoring_bundle(path: Path) -> dict:
    """Extract an AiAuthoringBundle and its bot/version references."""
    str_path = str(path)
    nodes: list[dict] = []
    edges: list[dict] = []

    bundle_name = _stem_strip(path, ".aiAuthoringBundle-meta.xml")

    try:
        root_el, ns = _parse_xml(path)
    except (ET.ParseError, FileNotFoundError, OSError):
        return {"nodes": [], "edges": []}

    from ._ids import make_sf_id

    bundle_id = make_sf_id("aiauthoringbundle", bundle_name)
    label = _find_text(root_el, "masterLabel", ns) or bundle_name

    nodes.append(
        {
            "id": bundle_id,
            "label": label,
            "sf_type": "AiAuthoringBundle",
            "file_type": "agentforce",
            "source_file": str_path,
            "source_location": None,
        }
    )

    # References to Bot and BotVersion
    linked_bot = _find_text(root_el, "bot", ns)
    linked_version = _find_text(root_el, "botVersion", ns)

    if linked_bot:
        edges.append(_make_edge(bundle_id, bot_id(linked_bot), "references", "EXTRACTED", str_path))
        if linked_version:
            edges.append(
                _make_edge(bundle_id, bot_version_id(linked_bot, linked_version), "references", "EXTRACTED", str_path)
            )

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# PromptTemplate  (.promptTemplate-meta.xml)
# ---------------------------------------------------------------------------


def extract_prompt_template(path: Path) -> dict:
    """Extract a PromptTemplate and its object/class/flow references."""
    str_path = str(path)
    nodes: list[dict] = []
    edges: list[dict] = []

    template_name = _stem_strip(path, ".promptTemplate-meta.xml")
    pt_id = prompt_template_id(template_name)

    try:
        root_el, ns = _parse_xml(path)
    except (ET.ParseError, FileNotFoundError, OSError):
        return {"nodes": [], "edges": []}

    label = _find_text(root_el, "masterLabel", ns) or template_name
    template_type = _find_text(root_el, "promptTemplateType", ns) or ""
    description = _find_text(root_el, "description", ns) or ""

    nodes.append(
        {
            "id": pt_id,
            "label": label,
            "sf_type": "PromptTemplate",
            "file_type": "agentforce",
            "source_file": str_path,
            "source_location": None,
            **({"template_type": template_type} if template_type else {}),
            **({"description": description} if description else {}),
        }
    )

    # Primary sObject context
    primary_obj = _find_text(root_el, "primaryObject", ns)
    if primary_obj:
        edges.append(_make_edge(pt_id, object_id(primary_obj), "references", "EXTRACTED", str_path))

    # Related objects in template body
    seen_objects: set[str] = set()
    for obj_el in _find_all(root_el, "relatedObject", ns):
        obj_name = obj_el.text.strip() if obj_el.text else None
        if obj_name and obj_name not in seen_objects:
            seen_objects.add(obj_name)
            edges.append(_make_edge(pt_id, object_id(obj_name), "references", "EXTRACTED", str_path))

    # Flex template references (Apex invocable actions, flows used as context)
    for action_el in _find_all(root_el, "flexTemplateActionCalls", ns):
        a_type = _find_text(action_el, "actionType", ns) or ""
        a_name = _find_text(action_el, "actionName", ns) or ""
        if a_name:
            if a_type == "apex":
                edges.append(_make_edge(pt_id, apex_class_id(a_name), "references", "EXTRACTED", str_path))
            elif a_type in ("flow", "Flow"):
                edges.append(_make_edge(pt_id, flow_id(a_name), "references", "EXTRACTED", str_path))

    return {"nodes": nodes, "edges": edges}

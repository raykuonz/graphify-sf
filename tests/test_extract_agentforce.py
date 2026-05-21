"""Tests for Agentforce metadata extractors.

Uses tmp_path for inline XML fixtures — no dependency on the simple_project fixture.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

_NS = 'xmlns="http://soap.sforce.com/2006/04/metadata"'


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

BOT_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<Bot {_NS}>
    <label>My Sales Agent</label>
    <description>An Agentforce sales agent</description>
    <botUser>agentuser@example.com</botUser>
    <defaultLocale>en_US</defaultLocale>
</Bot>
"""


def test_extract_bot_node(tmp_path):
    from graphify_sf.extract.agentforce import extract_bot

    bot_dir = tmp_path / "bots" / "MySalesAgent"
    bot_dir.mkdir(parents=True)
    bot_file = bot_dir / "MySalesAgent.bot-meta.xml"
    bot_file.write_text(BOT_XML)

    result = extract_bot(bot_file)
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["sf_type"] == "Bot"
    assert node["file_type"] == "agentforce"
    assert node["label"] == "My Sales Agent"
    assert node["id"] == "bot_mysalesagent"


def test_extract_bot_no_edges(tmp_path):
    from graphify_sf.extract.agentforce import extract_bot

    bot_dir = tmp_path / "bots" / "MySalesAgent"
    bot_dir.mkdir(parents=True)
    bot_file = bot_dir / "MySalesAgent.bot-meta.xml"
    bot_file.write_text(BOT_XML)

    result = extract_bot(bot_file)
    # Bot extractor produces no edges itself; BotVersion creates the Bot→BotVersion edge
    assert result["edges"] == []


def test_extract_bot_missing_file():
    from graphify_sf.extract.agentforce import extract_bot

    result = extract_bot(Path("/nonexistent/MySalesAgent.bot-meta.xml"))
    assert result == {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# BotVersion
# ---------------------------------------------------------------------------

BOT_VERSION_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<BotVersion {_NS}>
    <fullName>v1</fullName>
    <agentType>Agent</agentType>
    <label>Version 1</label>
    <description>Initial version</description>
    <conversationDefinition>MySalesFlow</conversationDefinition>
    <genAiPlugins>
        <genAiPlugin>ProductQueries</genAiPlugin>
    </genAiPlugins>
    <genAiPlugins>
        <genAiPlugin>OrderManagement</genAiPlugin>
    </genAiPlugins>
    <planner>
        <genAiPlannerBundle>SalesPlanner</genAiPlannerBundle>
    </planner>
</BotVersion>
"""


def test_extract_bot_version_node(tmp_path):
    from graphify_sf.extract.agentforce import extract_bot_version

    bot_dir = tmp_path / "bots" / "MySalesAgent"
    bot_dir.mkdir(parents=True)
    version_file = bot_dir / "v1.botVersion-meta.xml"
    version_file.write_text(BOT_VERSION_XML)

    result = extract_bot_version(version_file)
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["sf_type"] == "BotVersion"
    assert node["file_type"] == "agentforce"


def test_extract_bot_version_contains_bot_edge(tmp_path):
    from graphify_sf.extract.agentforce import extract_bot_version

    bot_dir = tmp_path / "bots" / "MySalesAgent"
    bot_dir.mkdir(parents=True)
    version_file = bot_dir / "v1.botVersion-meta.xml"
    version_file.write_text(BOT_VERSION_XML)

    result = extract_bot_version(version_file)
    contains_edges = [e for e in result["edges"] if e["relation"] == "contains"]
    assert len(contains_edges) == 1
    assert contains_edges[0]["source"] == "bot_mysalesagent"


def test_extract_bot_version_flow_edge(tmp_path):
    from graphify_sf.extract.agentforce import extract_bot_version

    bot_dir = tmp_path / "bots" / "MySalesAgent"
    bot_dir.mkdir(parents=True)
    version_file = bot_dir / "v1.botVersion-meta.xml"
    version_file.write_text(BOT_VERSION_XML)

    result = extract_bot_version(version_file)
    invokes_edges = [e for e in result["edges"] if e["relation"] == "invokes"]
    assert len(invokes_edges) == 1
    assert "mysalesflow" in invokes_edges[0]["target"]


def test_extract_bot_version_plugin_references(tmp_path):
    from graphify_sf.extract.agentforce import extract_bot_version

    bot_dir = tmp_path / "bots" / "MySalesAgent"
    bot_dir.mkdir(parents=True)
    version_file = bot_dir / "v1.botVersion-meta.xml"
    version_file.write_text(BOT_VERSION_XML)

    result = extract_bot_version(version_file)
    ref_edges = [e for e in result["edges"] if e["relation"] == "references"]
    plugin_edges = [e for e in ref_edges if "genaiplugin" in e["target"]]
    assert len(plugin_edges) == 2
    targets = {e["target"] for e in plugin_edges}
    assert any("productqueries" in t for t in targets)
    assert any("ordermanagement" in t for t in targets)


def test_extract_bot_version_planner_reference(tmp_path):
    from graphify_sf.extract.agentforce import extract_bot_version

    bot_dir = tmp_path / "bots" / "MySalesAgent"
    bot_dir.mkdir(parents=True)
    version_file = bot_dir / "v1.botVersion-meta.xml"
    version_file.write_text(BOT_VERSION_XML)

    result = extract_bot_version(version_file)
    planner_edges = [e for e in result["edges"] if e["relation"] == "references" and "genaiplanner" in e["target"]]
    assert len(planner_edges) == 1
    assert "salesplanner" in planner_edges[0]["target"]


# ---------------------------------------------------------------------------
# GenAiPlugin
# ---------------------------------------------------------------------------

PLUGIN_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<GenAiPlugin {_NS}>
    <masterLabel>Product Queries</masterLabel>
    <description>Handle product-related questions</description>
    <pluginType>Topic</pluginType>
    <pluginInstructions>Answer questions about products.</pluginInstructions>
    <functions>
        <functionName>GetProductDetails</functionName>
    </functions>
    <functions>
        <functionName>SearchProducts</functionName>
    </functions>
</GenAiPlugin>
"""


def test_extract_gen_ai_plugin_node(tmp_path):
    from graphify_sf.extract.agentforce import extract_gen_ai_plugin

    plugin_file = tmp_path / "ProductQueries.genAiPlugin-meta.xml"
    plugin_file.write_text(PLUGIN_XML)

    result = extract_gen_ai_plugin(plugin_file)
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["sf_type"] == "GenAiPlugin"
    assert node["label"] == "Product Queries"
    assert node["id"] == "genaiplugin_productqueries"


def test_extract_gen_ai_plugin_contains_functions(tmp_path):
    from graphify_sf.extract.agentforce import extract_gen_ai_plugin

    plugin_file = tmp_path / "ProductQueries.genAiPlugin-meta.xml"
    plugin_file.write_text(PLUGIN_XML)

    result = extract_gen_ai_plugin(plugin_file)
    contains_edges = [e for e in result["edges"] if e["relation"] == "contains"]
    assert len(contains_edges) == 2
    targets = {e["target"] for e in contains_edges}
    assert any("getproductdetails" in t for t in targets)
    assert any("searchproducts" in t for t in targets)


def test_extract_gen_ai_plugin_missing_file():
    from graphify_sf.extract.agentforce import extract_gen_ai_plugin

    result = extract_gen_ai_plugin(Path("/nonexistent/Plugin.genAiPlugin-meta.xml"))
    assert result == {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# GenAiFunction
# ---------------------------------------------------------------------------

FUNCTION_APEX_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<GenAiFunction {_NS}>
    <masterLabel>Get Product Details</masterLabel>
    <description>Fetch details for a specific product</description>
    <invocableActionType>apex</invocableActionType>
    <invocableActionName>ProductService</invocableActionName>
    <functionParameters>
        <parameterName>productId</parameterName>
        <parameterType>String</parameterType>
    </functionParameters>
</GenAiFunction>
"""

FUNCTION_FLOW_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<GenAiFunction {_NS}>
    <masterLabel>Create Order</masterLabel>
    <description>Create a new order via flow</description>
    <invocableActionType>flow</invocableActionType>
    <invocableActionName>CreateOrderFlow</invocableActionName>
</GenAiFunction>
"""


def test_extract_gen_ai_function_apex(tmp_path):
    from graphify_sf.extract.agentforce import extract_gen_ai_function

    fn_file = tmp_path / "GetProductDetails.genAiFunction-meta.xml"
    fn_file.write_text(FUNCTION_APEX_XML)

    result = extract_gen_ai_function(fn_file)
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["sf_type"] == "GenAiFunction"
    assert node["label"] == "Get Product Details"

    invokes_edges = [e for e in result["edges"] if e["relation"] == "invokes"]
    assert len(invokes_edges) == 1
    assert "productservice" in invokes_edges[0]["target"]
    assert invokes_edges[0]["confidence"] == "EXTRACTED"


def test_extract_gen_ai_function_flow(tmp_path):
    from graphify_sf.extract.agentforce import extract_gen_ai_function

    fn_file = tmp_path / "CreateOrder.genAiFunction-meta.xml"
    fn_file.write_text(FUNCTION_FLOW_XML)

    result = extract_gen_ai_function(fn_file)
    invokes_edges = [e for e in result["edges"] if e["relation"] == "invokes"]
    assert len(invokes_edges) == 1
    assert "createorderflow" in invokes_edges[0]["target"]


def test_extract_gen_ai_function_no_action(tmp_path):
    from graphify_sf.extract.agentforce import extract_gen_ai_function

    xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<GenAiFunction {_NS}>
    <masterLabel>No Action</masterLabel>
</GenAiFunction>
"""
    fn_file = tmp_path / "NoAction.genAiFunction-meta.xml"
    fn_file.write_text(xml)

    result = extract_gen_ai_function(fn_file)
    assert result["edges"] == []


# ---------------------------------------------------------------------------
# GenAiPlannerBundle
# ---------------------------------------------------------------------------

PLANNER_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<GenAiPlannerBundle {_NS}>
    <masterLabel>Sales Planner</masterLabel>
    <description>Main planner for the sales agent</description>
    <plannerType>Standard</plannerType>
    <subAgentDefinitions>
        <genAiPlugin>ProductQueries</genAiPlugin>
    </subAgentDefinitions>
    <subAgentDefinitions>
        <genAiPlugin>OrderManagement</genAiPlugin>
    </subAgentDefinitions>
</GenAiPlannerBundle>
"""


def test_extract_gen_ai_planner_bundle_node(tmp_path):
    from graphify_sf.extract.agentforce import extract_gen_ai_planner_bundle

    planner_file = tmp_path / "SalesPlanner.genAiPlannerBundle-meta.xml"
    planner_file.write_text(PLANNER_XML)

    result = extract_gen_ai_planner_bundle(planner_file)
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["sf_type"] == "GenAiPlannerBundle"
    assert node["label"] == "Sales Planner"
    assert node["id"] == "genaiplanner_salesplanner"


def test_extract_gen_ai_planner_bundle_plugin_references(tmp_path):
    from graphify_sf.extract.agentforce import extract_gen_ai_planner_bundle

    planner_file = tmp_path / "SalesPlanner.genAiPlannerBundle-meta.xml"
    planner_file.write_text(PLANNER_XML)

    result = extract_gen_ai_planner_bundle(planner_file)
    ref_edges = [e for e in result["edges"] if e["relation"] == "references"]
    assert len(ref_edges) == 2
    targets = {e["target"] for e in ref_edges}
    assert any("productqueries" in t for t in targets)
    assert any("ordermanagement" in t for t in targets)


# ---------------------------------------------------------------------------
# AiAuthoringBundle
# ---------------------------------------------------------------------------

AUTHORING_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<AiAuthoringBundle {_NS}>
    <masterLabel>Sales Agent Bundle</masterLabel>
    <bot>MySalesAgent</bot>
    <botVersion>v1</botVersion>
</AiAuthoringBundle>
"""


def test_extract_ai_authoring_bundle_node(tmp_path):
    from graphify_sf.extract.agentforce import extract_ai_authoring_bundle

    bundle_file = tmp_path / "SalesAgentBundle.aiAuthoringBundle-meta.xml"
    bundle_file.write_text(AUTHORING_XML)

    result = extract_ai_authoring_bundle(bundle_file)
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["sf_type"] == "AiAuthoringBundle"
    assert node["label"] == "Sales Agent Bundle"


def test_extract_ai_authoring_bundle_references(tmp_path):
    from graphify_sf.extract.agentforce import extract_ai_authoring_bundle

    bundle_file = tmp_path / "SalesAgentBundle.aiAuthoringBundle-meta.xml"
    bundle_file.write_text(AUTHORING_XML)

    result = extract_ai_authoring_bundle(bundle_file)
    ref_edges = [e for e in result["edges"] if e["relation"] == "references"]
    # Should have edge to Bot and edge to BotVersion
    assert len(ref_edges) == 2
    targets = {e["target"] for e in ref_edges}
    assert any("bot_mysalesagent" == t for t in targets)
    assert any("botversion" in t for t in targets)


# ---------------------------------------------------------------------------
# PromptTemplate
# ---------------------------------------------------------------------------

PROMPT_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<PromptTemplate {_NS}>
    <masterLabel>Account Summary</masterLabel>
    <promptTemplateType>einstein_gpt__fieldsGeneration</promptTemplateType>
    <description>Summarise an account</description>
    <primaryObject>Account</primaryObject>
    <relatedObject>Opportunity</relatedObject>
</PromptTemplate>
"""


def test_extract_prompt_template_node(tmp_path):
    from graphify_sf.extract.agentforce import extract_prompt_template

    pt_file = tmp_path / "AccountSummary.promptTemplate-meta.xml"
    pt_file.write_text(PROMPT_XML)

    result = extract_prompt_template(pt_file)
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    assert node["sf_type"] == "PromptTemplate"
    assert node["label"] == "Account Summary"
    assert node["id"] == "prompttemplate_accountsummary"


def test_extract_prompt_template_object_references(tmp_path):
    from graphify_sf.extract.agentforce import extract_prompt_template

    pt_file = tmp_path / "AccountSummary.promptTemplate-meta.xml"
    pt_file.write_text(PROMPT_XML)

    result = extract_prompt_template(pt_file)
    ref_edges = [e for e in result["edges"] if e["relation"] == "references"]
    # primaryObject + relatedObject
    assert len(ref_edges) >= 1
    targets = {e["target"] for e in ref_edges}
    assert any("account" in t for t in targets)


def test_extract_prompt_template_missing_file():
    from graphify_sf.extract.agentforce import extract_prompt_template

    result = extract_prompt_template(Path("/nonexistent/Template.promptTemplate-meta.xml"))
    assert result == {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# _ids helpers
# ---------------------------------------------------------------------------


def test_bot_id():
    from graphify_sf.extract._ids import bot_id

    assert bot_id("MySalesAgent") == "bot_mysalesagent"


def test_bot_version_id():
    from graphify_sf.extract._ids import bot_version_id

    assert bot_version_id("MySalesAgent", "v1") == "botversion_mysalesagent_v1"


def test_gen_ai_plugin_id():
    from graphify_sf.extract._ids import gen_ai_plugin_id

    assert gen_ai_plugin_id("ProductQueries") == "genaiplugin_productqueries"


def test_gen_ai_function_id():
    from graphify_sf.extract._ids import gen_ai_function_id

    assert gen_ai_function_id("GetProductDetails") == "genaifunction_getproductdetails"


def test_gen_ai_planner_id():
    from graphify_sf.extract._ids import gen_ai_planner_id

    assert gen_ai_planner_id("SalesPlanner") == "genaiplanner_salesplanner"


def test_prompt_template_id():
    from graphify_sf.extract._ids import prompt_template_id

    assert prompt_template_id("AccountSummary") == "prompttemplate_accountsummary"


# ---------------------------------------------------------------------------
# detect — file type classification
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# BotVersion — conversationDefinitionPlanners alternative XML path
# ---------------------------------------------------------------------------

BOT_VERSION_CDP_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<BotVersion {_NS}>
    <fullName>v2</fullName>
    <label>Version 2</label>
    <conversationDefinitionPlanners>
        <genAiPlannerName>NewStylePlanner</genAiPlannerName>
    </conversationDefinitionPlanners>
</BotVersion>
"""


def test_extract_bot_version_conversation_definition_planners(tmp_path):
    """BotVersion <conversationDefinitionPlanners> path also creates planner reference edge."""
    from graphify_sf.extract.agentforce import extract_bot_version

    bot_dir = tmp_path / "bots" / "MySalesAgent"
    bot_dir.mkdir(parents=True)
    version_file = bot_dir / "v2.botVersion-meta.xml"
    version_file.write_text(BOT_VERSION_CDP_XML)

    result = extract_bot_version(version_file)
    planner_edges = [e for e in result["edges"] if "genaiplanner" in e.get("target", "")]
    assert len(planner_edges) == 1
    assert "newstyleplanner" in planner_edges[0]["target"].lower()


def test_extract_bot_version_deduplicates_planners(tmp_path):
    """If both planner XML patterns name the same planner, only one edge is produced."""
    from graphify_sf.extract.agentforce import extract_bot_version

    xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<BotVersion {_NS}>
    <fullName>v3</fullName>
    <label>Version 3</label>
    <planner>
        <genAiPlannerBundle>SamePlanner</genAiPlannerBundle>
    </planner>
    <conversationDefinitionPlanners>
        <genAiPlannerName>SamePlanner</genAiPlannerName>
    </conversationDefinitionPlanners>
</BotVersion>
"""
    bot_dir = tmp_path / "bots" / "MySalesAgent"
    bot_dir.mkdir(parents=True)
    version_file = bot_dir / "v3.botVersion-meta.xml"
    version_file.write_text(xml)

    result = extract_bot_version(version_file)
    planner_edges = [e for e in result["edges"] if "genaiplanner" in e.get("target", "")]
    assert len(planner_edges) == 1, "Duplicate planner reference should be deduplicated"


# ---------------------------------------------------------------------------
# GenAiPlannerBundle — localTopics / localActions
# ---------------------------------------------------------------------------

PLANNER_LOCAL_ACTIONS_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<GenAiPlannerBundle {_NS}>
    <masterLabel>Referral Planner</masterLabel>
    <plannerType>Standard</plannerType>
    <localTopics>
        <localActions>
            <fullName>CreateReferral</fullName>
            <masterLabel>Create Referral</masterLabel>
            <invocationTarget>CreateReferralFlow</invocationTarget>
            <invocationTargetType>flow</invocationTargetType>
        </localActions>
        <localActions>
            <fullName>ValidateReferral</fullName>
            <masterLabel>Validate Referral</masterLabel>
            <invocationTarget>ReferralValidationService</invocationTarget>
            <invocationTargetType>apex</invocationTargetType>
        </localActions>
    </localTopics>
</GenAiPlannerBundle>
"""


def test_extract_planner_local_actions_creates_nodes(tmp_path):
    """localActions elements create GenAiFunction nodes with scope=local."""
    from graphify_sf.extract.agentforce import extract_gen_ai_planner_bundle

    planner_file = tmp_path / "ReferralPlanner.genAiPlannerBundle-meta.xml"
    planner_file.write_text(PLANNER_LOCAL_ACTIONS_XML)

    result = extract_gen_ai_planner_bundle(planner_file)
    local_fn_nodes = [n for n in result["nodes"] if n.get("sf_type") == "GenAiFunction"]
    assert len(local_fn_nodes) == 2
    for n in local_fn_nodes:
        assert n.get("scope") == "local"


def test_extract_planner_local_actions_contains_edges(tmp_path):
    """Planner → local action 'contains' edges are created."""
    from graphify_sf.extract.agentforce import extract_gen_ai_planner_bundle

    planner_file = tmp_path / "ReferralPlanner.genAiPlannerBundle-meta.xml"
    planner_file.write_text(PLANNER_LOCAL_ACTIONS_XML)

    result = extract_gen_ai_planner_bundle(planner_file)
    planner_id = result["nodes"][0]["id"]
    contains_edges = [e for e in result["edges"] if e.get("relation") == "contains" and e["source"] == planner_id]
    assert len(contains_edges) == 2


def test_extract_planner_local_action_flow_invokes_edge(tmp_path):
    """Local action with invocationTargetType=flow creates an 'invokes' edge to the flow."""
    from graphify_sf.extract.agentforce import extract_gen_ai_planner_bundle

    planner_file = tmp_path / "ReferralPlanner.genAiPlannerBundle-meta.xml"
    planner_file.write_text(PLANNER_LOCAL_ACTIONS_XML)

    result = extract_gen_ai_planner_bundle(planner_file)
    invokes_edges = [e for e in result["edges"] if e.get("relation") == "invokes"]
    flow_invokes = [
        e for e in invokes_edges if "flow" in e["target"].lower() or "createreferral" in e["target"].lower()
    ]
    assert len(flow_invokes) >= 1
    assert any("createreferralflow" in e["target"].lower() for e in invokes_edges)


def test_extract_planner_local_action_apex_invokes_edge(tmp_path):
    """Local action with invocationTargetType=apex creates an 'invokes' edge to the Apex class."""
    from graphify_sf.extract.agentforce import extract_gen_ai_planner_bundle

    planner_file = tmp_path / "ReferralPlanner.genAiPlannerBundle-meta.xml"
    planner_file.write_text(PLANNER_LOCAL_ACTIONS_XML)

    result = extract_gen_ai_planner_bundle(planner_file)
    invokes_edges = [e for e in result["edges"] if e.get("relation") == "invokes"]
    assert any("referralvalidationservice" in e["target"].lower() for e in invokes_edges)


# ---------------------------------------------------------------------------
# GenAiFunction — unknown invocableActionType
# ---------------------------------------------------------------------------

FUNCTION_UNKNOWN_TYPE_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<GenAiFunction {_NS}>
    <masterLabel>Webhook Action</masterLabel>
    <invocableActionType>externalService</invocableActionType>
    <invocableActionName>WebhookTarget</invocableActionName>
</GenAiFunction>
"""


def test_extract_gen_ai_function_unknown_type_inferred_edge(tmp_path):
    """Unknown invocableActionType creates an INFERRED invokes edge."""
    from graphify_sf.extract.agentforce import extract_gen_ai_function

    fn_file = tmp_path / "WebhookAction.genAiFunction-meta.xml"
    fn_file.write_text(FUNCTION_UNKNOWN_TYPE_XML)

    result = extract_gen_ai_function(fn_file)
    invokes_edges = [e for e in result["edges"] if e.get("relation") == "invokes"]
    assert len(invokes_edges) == 1
    assert invokes_edges[0]["confidence"] == "INFERRED"


# ---------------------------------------------------------------------------
# PromptTemplate — flexTemplateActionCalls and multiple relatedObjects
# ---------------------------------------------------------------------------

PROMPT_FLEX_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<PromptTemplate {_NS}>
    <masterLabel>Lead Summary</masterLabel>
    <promptTemplateType>einstein_gpt__salesEmail</promptTemplateType>
    <primaryObject>Lead</primaryObject>
    <relatedObject>Account</relatedObject>
    <relatedObject>Contact</relatedObject>
    <flexTemplateActionCalls>
        <actionType>apex</actionType>
        <actionName>LeadSummaryService</actionName>
    </flexTemplateActionCalls>
    <flexTemplateActionCalls>
        <actionType>flow</actionType>
        <actionName>EnrichLeadFlow</actionName>
    </flexTemplateActionCalls>
</PromptTemplate>
"""


def test_extract_prompt_template_multiple_related_objects(tmp_path):
    """Multiple relatedObject elements all create reference edges."""
    from graphify_sf.extract.agentforce import extract_prompt_template

    pt_file = tmp_path / "LeadSummary.promptTemplate-meta.xml"
    pt_file.write_text(PROMPT_FLEX_XML)

    result = extract_prompt_template(pt_file)
    ref_edges = [e for e in result["edges"] if e.get("relation") == "references"]
    targets = {e["target"] for e in ref_edges}
    assert any("account" in t.lower() for t in targets)
    assert any("contact" in t.lower() for t in targets)


def test_extract_prompt_template_flex_apex_action(tmp_path):
    """flexTemplateActionCalls with actionType=apex creates a references edge to Apex class."""
    from graphify_sf.extract.agentforce import extract_prompt_template

    pt_file = tmp_path / "LeadSummary.promptTemplate-meta.xml"
    pt_file.write_text(PROMPT_FLEX_XML)

    result = extract_prompt_template(pt_file)
    ref_edges = [e for e in result["edges"] if e.get("relation") == "references"]
    assert any("leadsummaryservice" in e["target"].lower() for e in ref_edges)


def test_extract_prompt_template_flex_flow_action(tmp_path):
    """flexTemplateActionCalls with actionType=flow creates a references edge to Flow."""
    from graphify_sf.extract.agentforce import extract_prompt_template

    pt_file = tmp_path / "LeadSummary.promptTemplate-meta.xml"
    pt_file.write_text(PROMPT_FLEX_XML)

    result = extract_prompt_template(pt_file)
    ref_edges = [e for e in result["edges"] if e.get("relation") == "references"]
    assert any("enrichleadflow" in e["target"].lower() for e in ref_edges)


def test_detect_classifies_agentforce_files(tmp_path):
    from graphify_sf.detect import SFFileType, detect

    # Create minimal valid files for each Agentforce type
    bots_dir = tmp_path / "force-app" / "main" / "default" / "bots" / "MyAgent"
    bots_dir.mkdir(parents=True)
    (bots_dir / "MyAgent.bot-meta.xml").write_text("<Bot/>")
    (bots_dir / "v1.botVersion-meta.xml").write_text("<BotVersion/>")

    plugins_dir = tmp_path / "force-app" / "main" / "default" / "genAiPlugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "MyPlugin.genAiPlugin-meta.xml").write_text("<GenAiPlugin/>")

    fns_dir = tmp_path / "force-app" / "main" / "default" / "genAiFunctions"
    fns_dir.mkdir(parents=True)
    (fns_dir / "MyFunction.genAiFunction-meta.xml").write_text("<GenAiFunction/>")

    planners_dir = tmp_path / "force-app" / "main" / "default" / "genAiPlannerBundles"
    planners_dir.mkdir(parents=True)
    (planners_dir / "MyPlanner.genAiPlannerBundle-meta.xml").write_text("<GenAiPlannerBundle/>")

    bundles_dir = tmp_path / "force-app" / "main" / "default" / "aiAuthoringBundles"
    bundles_dir.mkdir(parents=True)
    (bundles_dir / "MyBundle.aiAuthoringBundle-meta.xml").write_text("<AiAuthoringBundle/>")

    prompts_dir = tmp_path / "force-app" / "main" / "default" / "promptTemplates"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "MyTemplate.promptTemplate-meta.xml").write_text("<PromptTemplate/>")

    result = detect(tmp_path)
    agentforce_files = result["files"].get(SFFileType.AGENTFORCE.value, [])
    assert len(agentforce_files) == 7, f"Expected 7 agentforce files, got {len(agentforce_files)}: {agentforce_files}"

import re
from urllib.parse import urlparse


def make_sf_id(*parts: str) -> str:
    combined = "_".join(p.strip("_. ") for p in parts if p)
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", combined)
    return cleaned.strip("_").lower()


def apex_class_id(class_name: str) -> str:
    return make_sf_id("apex", class_name)


def apex_method_id(class_name: str, method_name: str) -> str:
    return make_sf_id("method", class_name, method_name)


def object_id(object_name: str) -> str:
    return make_sf_id("object", object_name)


def field_id(object_name: str, field_name: str) -> str:
    return make_sf_id("field", object_name, field_name)


def flow_id(flow_name: str) -> str:
    return make_sf_id("flow", flow_name)


def lwc_id(component_name: str) -> str:
    return make_sf_id("lwc", component_name)


def aura_id(component_name: str) -> str:
    return make_sf_id("aura", component_name)


def profile_id(name: str) -> str:
    return make_sf_id("profile", name)


def permset_id(name: str) -> str:
    return make_sf_id("permset", name)


def layout_id(name: str) -> str:
    return make_sf_id("layout", name)


def page_id(name: str) -> str:
    return make_sf_id("page", name)


def label_id(name: str) -> str:
    return make_sf_id("label", name)


def trigger_id(name: str) -> str:
    return make_sf_id("trigger", name)


def bot_id(name: str) -> str:
    return make_sf_id("bot", name)


def bot_version_id(bot_name: str, version_name: str) -> str:
    return make_sf_id("botversion", bot_name, version_name)


def gen_ai_plugin_id(name: str) -> str:
    return make_sf_id("genaiplugin", name)


def gen_ai_function_id(name: str) -> str:
    return make_sf_id("genaifunction", name)


def gen_ai_planner_id(name: str) -> str:
    return make_sf_id("genaiplanner", name)


def prompt_template_id(name: str) -> str:
    return make_sf_id("prompttemplate", name)


_HOST_RE = re.compile(r"[a-z0-9.-]+|[0-9a-f:]+")


def endpoint_host(url: str) -> str | None:
    """The host of an ``http(s)`` URL, or None when it cannot be stated with certainty.

    Rejects anything the id scheme would conflate or that parsers disagree on: merge fields, percent-escapes,
    backslashes, spaces, non-ASCII (IDN) hosts. A trailing dot is dropped (``api.example.com.`` is the same host).
    """
    if "\\" in url or " " in url.strip():
        return None
    try:
        host = urlparse(url.strip()).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.rstrip(".")
    return host if host and _HOST_RE.fullmatch(host) else None

"""Turn the app's API-format graphs into ComfyUI canvas workflows people can read.

An API graph says only what runs. A canvas workflow also says what each part is for: nodes laid out
left to right in the order the data flows, colour-coded groups ("The lead → Picture 2", "Anchor frame →
Picture 1", "Identity pass"…), titled inputs and a note explaining the recipe. Widget values are placed
from the live ComfyUI's /object_info, so the canvas converts back to exactly the API graph.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}
COLORS = {"inputs": "#3f789e", "lead": "#a1309b", "world": "#b58b2a", "models": "#444444", "prompt": "#8a6d3b",
          "sample": "#335f55", "output": "#2f6f3f", "cinema": "#b06634"}
ROLE_OF_CLASS = {
    "CheckpointLoaderSimple": "models", "UNETLoader": "models", "CLIPLoader": "models", "VAELoader": "models",
    "LoraLoaderModelOnly": "models", "ModelSamplingAuraFlow": "models", "CFGNorm": "models",
    "ModelNoiseScale": "models", "HiDreamO1PatchSeamSmoothing": "models", "LatentUpscaleModelLoader": "models",
    "CLIPTextEncode": "prompt", "TextEncodeQwenImageEditPlus": "prompt", "FluxKontextMultiReferenceLatentMethod": "prompt",
    "LTXVConditioning": "prompt", "TextGenerate": "prompt",
    "KSampler": "sample", "SamplerCustomAdvanced": "sample", "EmptySD3LatentImage": "sample", "VAEEncode": "sample",
    "EmptyLatentImage": "sample",
    "VAEDecode": "output", "VAEDecodeTiled": "output", "SaveImage": "output", "SaveVideo": "output",
    "CreateVideo": "output", "PreviewAny": "output", "PreviewImage": "output",
    "LoadImage": "inputs", "LoadVideo": "inputs", "LoadAudio": "inputs",
}
ROLE_TITLES = {"inputs": "Inputs", "models": "Models", "prompt": "Prompt", "sample": "Sample", "output": "Output",
               "cinema": "Open Cinema", "lead": "The lead", "world": "The world"}
ROLE_ORDER = ["inputs", "world", "lead", "cinema", "models", "prompt", "sample", "output"]


def object_info(base: str = "http://127.0.0.1:8288") -> dict[str, Any]:
    with urllib.request.urlopen(base + "/object_info", timeout=30) as r:
        return json.loads(r.read())


def _default(spec: list[Any]) -> Any:
    kind, opts = spec[0], (spec[1] if len(spec) > 1 else {}) or {}
    if isinstance(kind, list):
        return opts.get("default", kind[0] if kind else "")
    if kind == "COMBO":
        return opts.get("default", (opts.get("options") or [""])[0])
    return opts.get("default", {"INT": 0, "FLOAT": 0.0, "STRING": "", "BOOLEAN": False}.get(kind, ""))


def _is_widget(spec: list[Any]) -> bool:
    opts = (spec[1] if len(spec) > 1 else {}) or {}
    return (isinstance(spec[0], list) or spec[0] in WIDGET_TYPES or spec[0] == "COMFY_DYNAMICCOMBO_V3"
            or opts.get("widgetType") in WIDGET_TYPES)  # e.g. "FLOAT,INT" shown as a FLOAT widget


def _ordered_inputs(info: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    spec = info["input"]
    order = info.get("input_order") or {k: list(v) for k, v in spec.items() if k in ("required", "optional")}
    return [(name, spec[section][name]) for section in ("required", "optional") for name in order.get(section, [])
            if name in spec.get(section, {})]


def _widgets(inputs: dict[str, Any], info: dict[str, Any]) -> list[Any]:
    """Widget values in the positional order the frontend expects."""
    values: list[Any] = []
    for name, spec in _ordered_inputs(info):
        if not _is_widget(spec):
            continue  # a socket
        if isinstance(inputs.get(name), list):  # a widget driven by a link still holds its slot
            values.append(_default(spec))
            if (spec[1] if len(spec) > 1 else {}).get("control_after_generate"):
                values.append("fixed")
            continue
        if spec[0] == "COMFY_DYNAMICCOMBO_V3":
            choice = inputs.get(name, spec[1]["options"][0]["key"])
            values.append(choice)
            option = next(o for o in spec[1]["options"] if o["key"] == choice)
            for section in ("required", "optional"):
                for sub, sub_spec in option["inputs"].get(section, {}).items():
                    values.append(inputs.get(f"{name}.{sub}", _default(sub_spec)))
                    if (sub_spec[1] if len(sub_spec) > 1 else {}).get("control_after_generate"):
                        values.append("fixed")
            continue
        values.append(inputs.get(name, _default(spec)))
        if (spec[1] if len(spec) > 1 else {}).get("control_after_generate"):
            values.append("fixed")
    return values


def to_canvas(graph: dict[str, Any], info: dict[str, Any], titles: dict[str, str] | None = None,
              groups: list[tuple[str, str, list[str]]] | None = None, note: str = "") -> dict[str, Any]:
    """API graph → canvas workflow. `groups` are (title, colour role, node ids), laid out left to right."""
    titles = titles or {}
    ids = {key: n + 1 for n, key in enumerate(graph)}
    # group membership: explicit groups first, then a role from the node's class
    member: dict[str, tuple[str, str]] = {}
    for title, role, keys in groups or []:
        for key in keys:
            member[key] = (title, role)
    for key, node in graph.items():
        if key not in member:
            role = ROLE_OF_CLASS.get(node["class_type"], "cinema" if node["class_type"].startswith("OpenCinema") else "sample")
            member[key] = (ROLE_TITLES[role], role)
    order: list[tuple[str, str]] = []
    for title, role, _ in groups or []:
        if (title, role) not in order:
            order.append((title, role))
    for role in ROLE_ORDER:
        for key in graph:
            if member[key][1] == role and member[key] not in order:
                order.append(member[key])

    links: list[list[Any]] = []
    out_links: dict[tuple[str, int], list[int]] = {}
    nodes: list[dict[str, Any]] = []
    x, gap, col_w = 60, 70, 340
    group_boxes = []
    if note:
        nodes.append({"id": len(graph) + 1, "type": "MarkdownNote", "pos": [x, 120], "size": [360, 420], "flags": {},
                      "order": 0, "mode": 0, "inputs": [], "outputs": [], "title": "How this works",
                      "properties": {}, "widgets_values": [note], "color": "#432", "bgcolor": "#653"})
        x += 360 + gap
    for title, role in order:
        keys = [k for k in graph if member[k] == (title, role)]
        y, top = 160, 160
        for key in keys:
            node, info_c = graph[key], info.get(graph[key]["class_type"], {})
            sockets = [(n, s) for n, s in _ordered_inputs(info_c) if not _is_widget(s) or isinstance(node["inputs"].get(n), list)]
            height = 46 + 24 * (len(sockets) + len(_widgets(node["inputs"], info_c)) + len(info_c.get("output", [])))
            if node["class_type"] in ("LoadImage", "LoadVideo"):
                height += 260  # room for the preview
            nodes.append({"id": ids[key], "type": node["class_type"], "pos": [x, y], "size": [col_w - 40, height],
                          "flags": {}, "order": 0, "mode": 0, "inputs": [], "outputs": [],
                          "title": titles.get(key) or info_c.get("display_name") or node["class_type"],
                          "properties": {"Node name for S&R": node["class_type"]},
                          "widgets_values": _widgets(node["inputs"], info_c), "color": COLORS[role] if role in ("lead", "world") else None})
            nodes[-1] = {k: v for k, v in nodes[-1].items() if v is not None}
            y += height + 40
        group_boxes.append({"title": title, "bounding": [x - 20, top - 60, col_w, y - top + 40],
                            "color": COLORS[role], "font_size": 22, "flags": {}})
        x += col_w + gap
    by_id = {n["id"]: n for n in nodes}
    for key, node in graph.items():
        info_c = info.get(node["class_type"], {})
        target = by_id[ids[key]]
        for name, spec in _ordered_inputs(info_c):
            value = node["inputs"].get(name)
            if isinstance(value, list):
                src, slot = value
                link_id = len(links) + 1
                kind = info.get(graph[src]["class_type"], {}).get("output", ["*"])[slot]
                links.append([link_id, ids[src], slot, ids[key], len(target["inputs"]), kind])
                out_links.setdefault((src, slot), []).append(link_id)
                entry = {"name": name, "type": spec[0] if isinstance(spec[0], str) else "COMBO", "link": link_id}
                if _is_widget(spec):
                    entry["widget"] = {"name": name}
                target["inputs"].append(entry)
            elif not _is_widget(spec):
                target["inputs"].append({"name": name, "type": spec[0], "link": None})
    for key, node in graph.items():  # outputs once every consumer's link exists
        info_c, target = info.get(node["class_type"], {}), by_id[ids[key]]
        for slot, (kind, label) in enumerate(zip(info_c.get("output", []), info_c.get("output_name", []))):
            target["outputs"].append({"name": label, "type": kind, "links": out_links.get((key, slot), []),
                                      "slot_index": slot})
    for n, node in enumerate(nodes):
        node["order"] = n
    return {"last_node_id": max(by_id), "last_link_id": len(links), "nodes": nodes, "links": links,
            "groups": group_boxes, "config": {}, "extra": {"ds": {"scale": 0.6, "offset": [0, 0]}}, "version": 0.4}

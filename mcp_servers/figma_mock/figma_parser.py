"""Turn a Figma REST file payload (GET /v1/files/:key) into simplified UX intent."""
from typing import Any

KIND_BY_COMPONENT = {
    "Heading": "heading",
    "Text": "text",
    "TextInput": "text-input",
    "PasswordInput": "password-input",
    "ReadOnlyField": "readonly-field",
    "TextArea": "text-area",
    "Button": "button",
    "Link": "link",
    "MultiSelect": "multi-select",
    "Select": "select",
    "Checkbox": "checkbox",
    "Table": "table",
    "ErrorText": "error-text",
}


def _prop(node: dict, name: str) -> Any:
    return (node.get("componentProperties") or {}).get(name, {}).get("value")


def _walk(node: dict):
    yield node
    for child in node.get("children", []) or []:
        yield from _walk(child)


def _box(node: dict, origin: dict) -> dict | None:
    b = node.get("absoluteBoundingBox")
    if not b:
        return None
    return {"x": b["x"] - origin.get("x", 0), "y": b["y"] - origin.get("y", 0), "width": b["width"], "height": b["height"]}


def parse_file(payload: dict) -> dict:
    frames: dict[str, dict] = {}
    id_to_frame: dict[str, str] = {}

    for canvas in payload["document"].get("children", []):
        for frame in canvas.get("children", []):
            if frame.get("type") != "FRAME":
                continue
            id_to_frame[frame["id"]] = frame["name"]
            size = frame.get("absoluteBoundingBox", {})
            frames[frame["name"]] = {"id": frame["id"], "name": frame["name"], "components": [],
                                     "width": size.get("width"), "height": size.get("height")}

    flows = []
    for canvas in payload["document"].get("children", []):
        for frame in canvas.get("children", []):
            if frame.get("type") != "FRAME":
                continue
            for node in _walk(frame):
                if node.get("type") != "INSTANCE":
                    continue
                label = _prop(node, "Label") or node.get("name")
                component = {
                    "node_id": node["id"],
                    "kind": KIND_BY_COMPONENT.get(node.get("name"), node.get("name", "").lower()),
                    "label": label,
                    "required": _prop(node, "State") != "Conditional",
                }
                box = _box(node, frame.get("absoluteBoundingBox", {}))
                if box:
                    component["box"] = box
                columns = _prop(node, "Columns")
                if columns:
                    component["columns"] = columns.split("|")
                for interaction in node.get("interactions", []) or []:
                    for action in interaction.get("actions", []):
                        dest = id_to_frame.get(action.get("destinationId", ""))
                        if dest:
                            component["navigates_to"] = dest
                            flows.append({
                                "from_frame": frame["name"],
                                "trigger": interaction.get("trigger", {}).get("type", "ON_CLICK"),
                                "trigger_label": label,
                                "to_frame": dest,
                            })
                frames[frame["name"]]["components"].append(component)

    return {
        "file_name": payload.get("name"),
        "version": payload.get("version"),
        "frames": frames,
        "flows": flows,
        "frame_routes": payload.get("x-frameRoutes", {}),
        "story_links": payload.get("x-storyLinks", {}),
        "approved_variances": payload.get("x-approvedVariances", []),
    }

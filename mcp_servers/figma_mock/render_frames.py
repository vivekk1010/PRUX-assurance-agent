"""Render Figma frames from the fixture into PNG design images (stand-in for Figma's GET /v1/images export).

  python -m mcp_servers.figma_mock.render_frames
"""
import html
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURE_DIR / "blog_notes.figma.json"
FRAMES_DIR = FIXTURE_DIR / "frames"

CSS = """
* { box-sizing: border-box; }
body { margin: 0; font-family: 'Segoe UI', system-ui, sans-serif; color: #1d2330; }
.n { position: absolute; }
.label { font-weight: 600; font-size: 14px; margin-bottom: 6px; }
.box { border: 1px solid #c6cbd4; border-radius: 4px; background: #fff; height: 36px; padding: 8px; font-size: 14px; color: #8a919c; }
.ro { background: #eef0f3; color: #1d2330; }
.btn { border-radius: 4px; font-size: 14px; display: flex; align-items: center; justify-content: center; height: 100%; }
.primary { background: #3b5bdb; color: #fff; }
.secondary { background: #495057; color: #fff; }
.chip { display: inline-block; background: #e7ecff; color: #3b5bdb; border-radius: 12px; padding: 2px 10px; margin-right: 6px; font-size: 13px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { text-align: left; padding: 8px; border-bottom: 1px solid #e3e6eb; }
td { padding: 10px 8px; border-bottom: 1px solid #f0f1f4; }
.bar { height: 10px; border-radius: 5px; background: #e3e6eb; }
"""


def _rgba(fills: list | None, default: str = "transparent") -> str:
    for f in fills or []:
        if f.get("type") == "SOLID":
            c = f["color"]
            return f"rgba({round(c['r'] * 255)},{round(c['g'] * 255)},{round(c['b'] * 255)},{c.get('a', 1)})"
    return default


def _prop(node: dict, name: str, default: str = "") -> str:
    return (node.get("componentProperties") or {}).get(name, {}).get("value", default)


def _instance(node: dict) -> str:
    kind, label = node["name"], html.escape(_prop(node, "Label"))
    sample = html.escape(_prop(node, "Sample"))
    if _prop(node, "State") == "Conditional":
        return ""
    if kind == "Heading":
        return f'<div style="font-size:28px;font-weight:700">{label}</div>'
    if kind == "Text":
        color = "#fff" if _prop(node, "Tone") == "Inverse" else "#1d2330"
        return f'<div style="font-size:14px;color:{color};text-align:right">{label} {sample}</div>'
    if kind in {"TextInput", "PasswordInput", "ReadOnlyField"}:
        value = "••••••••" if kind == "PasswordInput" else sample or html.escape(_prop(node, "Placeholder"))
        cls = "box ro" if kind == "ReadOnlyField" else "box"
        return f'<div class="label">{label}</div><div class="{cls}">{value}</div>'
    if kind == "TextArea":
        return f'<div class="label">{label}</div><div class="box" style="height:calc(100% - 26px)"></div>'
    if kind == "Button":
        variant = "secondary" if _prop(node, "Variant") == "Secondary" else "primary"
        return f'<div class="btn {variant}">{label}</div>'
    if kind == "Link":
        return f'<div style="color:#3b5bdb;text-decoration:underline;font-size:14px">{label}</div>'
    if kind == "MultiSelect":
        chips = "".join(f'<span class="chip">{html.escape(o)} ×</span>' for o in _prop(node, "Options").split(",") if o)
        return (f'<div style="display:flex;align-items:center;gap:12px;height:100%"><div class="label" style="margin:0">{label}</div>'
                f'<div class="box" style="flex:1;display:flex;align-items:center;justify-content:space-between">'
                f'<span>{chips}</span><span>▾</span></div></div>')
    if kind == "Table":
        cols = _prop(node, "Columns").split("|")
        head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
        row = "".join(f'<td><div class="bar" style="width:{60 + (i * 13) % 30}%"></div></td>' for i in range(len(cols)))
        return f"<table><tr>{head}</tr>" + f"<tr>{row}</tr>" * 3 + "</table>"
    return f"<div>{label}</div>"


def _node_html(node: dict, origin: dict) -> str:
    b = node.get("absoluteBoundingBox")
    if not b:
        return ""
    style = f"left:{b['x'] - origin['x']}px;top:{b['y'] - origin['y']}px;width:{b['width']}px;height:{b['height']}px;"
    t = node.get("type")
    if t == "RECTANGLE":
        radius = node.get("cornerRadius", 0)
        shadow = "box-shadow:0 1px 3px rgba(0,0,0,.08);" if radius else ""
        return f'<div class="n" style="{style}background:{_rgba(node.get("fills"))};border-radius:{radius}px;{shadow}"></div>'
    if t == "TEXT":
        s = node.get("style", {})
        return (f'<div class="n" style="{style}font-size:{s.get("fontSize", 14)}px;font-weight:{s.get("fontWeight", 400)};'
                f'color:{_rgba(node.get("fills"), "#1d2330")}">{html.escape(node.get("characters", ""))}</div>')
    if t == "INSTANCE":
        inner = _instance(node)
        return f'<div class="n" style="{style}">{inner}</div>' if inner else ""
    return ""


def frame_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def render_all(fixture: Path = FIXTURE, out_dir: Path = FRAMES_DIR) -> list[Path]:
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for canvas in payload["document"]["children"]:
            for frame in canvas["children"]:
                if frame.get("type") != "FRAME":
                    continue
                origin = frame["absoluteBoundingBox"]
                body = "".join(_node_html(n, origin) for n in frame.get("children", []))
                doc = (f"<html><head><style>{CSS}</style></head><body>"
                       f'<div style="position:relative;width:{origin["width"]}px;height:{origin["height"]}px;'
                       f'background:{_rgba(frame.get("fills"), "#fff")}">{body}</div></body></html>')
                page = browser.new_page(viewport={"width": origin["width"], "height": origin["height"]})
                page.set_content(doc)
                path = out_dir / f"{frame_slug(frame['name'])}.png"
                page.screenshot(path=str(path))
                page.close()
                written.append(path)
        browser.close()
    return written


if __name__ == "__main__":
    for p in render_all():
        print(f"Rendered {p}")

"""Semantic comparison of a live page against Figma components (kinds, labels, control types)."""
from typing import Optional

from playwright.sync_api import Locator, Page

from agent.models import UIComponent

QUICK_MS = 1500


def _visible(loc: Locator) -> bool:
    try:
        loc.first.wait_for(state="visible", timeout=QUICK_MS)
        return True
    except Exception:
        return False


def _locate(page: Page, kind: str, label: str) -> Locator:
    if kind in {"button", "link"}:
        return page.get_by_role(kind, name=label, exact=True)
    if kind == "heading":
        return page.get_by_role("heading", name=label, exact=True)
    if kind == "table":
        return page.get_by_role("table", name=label)
    if kind in {"text", "error-text"}:
        return page.get_by_text(label)
    return page.get_by_label(label, exact=True)


def _check_control(loc: Locator, kind: str) -> Optional[str]:
    el = loc.first
    tag, input_type, multiple = el.evaluate("e => [e.tagName.toLowerCase(), (e.type || '').toLowerCase(), !!e.multiple]")
    if kind == "multi-select" and not (tag == "select" and multiple):
        return "single-select observed, multi-select expected" if tag == "select" else f"<{tag}> observed, multi-select expected"
    if kind == "select" and tag != "select":
        return f"<{tag}> observed, select expected"
    if kind == "password-input" and input_type != "password":
        return "input is not masked (type != password)"
    if kind == "text-area" and tag != "textarea":
        return f"<{tag}> observed, multi-line text area expected"
    if kind == "readonly-field" and el.is_editable():
        return "field is editable, read-only expected"
    return None


def compare_frame(page: Page, components: list[UIComponent], variances: list[dict],
                  only_labels: Optional[list[str]] = None) -> list[dict]:
    findings = []
    for comp in components:
        if only_labels and comp.label not in only_labels:
            continue
        base = {"node_id": comp.node_id, "kind": comp.kind, "label": comp.label, "box": comp.box}
        if not comp.required and not only_labels:
            findings.append({**base, "status": "skipped", "detail": "conditional state in design"})
            continue

        loc = _locate(page, comp.kind, comp.label)
        note = ""
        if not _visible(loc):
            loc = None
            for v in variances:
                if v.get("node_id") != comp.node_id:
                    continue
                for alt in v.get("allowed_labels", []):
                    candidate = _locate(page, comp.kind, alt)
                    if _visible(candidate):
                        loc, note = candidate, f"label '{alt}' approved: {v.get('reason')}"
                        break
                for kind in v.get("allowed_kinds", []):
                    if loc is None:
                        candidate = _locate(page, kind, comp.label)
                        if _visible(candidate):
                            loc, note = candidate, f"rendered as {kind}, approved: {v.get('reason')}"
        if loc is None:
            findings.append({**base, "status": "missing", "detail": f"no {comp.kind} labelled '{comp.label}' on page"})
            continue

        problem = None if comp.kind in {"button", "link", "heading", "text", "error-text", "table"} else _check_control(loc, comp.kind)
        if comp.kind == "table" and comp.columns:
            absent = [c for c in comp.columns if loc.first.get_by_role("columnheader", name=c, exact=True).count() == 0]
            if absent:
                problem = f"missing columns: {absent}"
        if problem:
            findings.append({**base, "status": "mismatch", "detail": problem})
        else:
            findings.append({**base, "status": "approved_variance" if note else "matched", "detail": note})
    return findings

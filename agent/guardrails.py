"""Safety boundary between LLM-planned steps and the StageUI environment."""
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlparse

from agent.models import Step

ALLOWED_ACTIONS = set(Step.model_fields["action"].annotation.__args__)
DESTRUCTIVE = re.compile(r"\b(delete|remove|drop|destroy|purge|reset|admin|truncate|wipe)\b", re.IGNORECASE)
MASK = "••••••"


def check_step(step: Step, base_url: str) -> Optional[str]:
    """Return a refusal reason, or None when the step is allowed."""
    if step.action not in ALLOWED_ACTIONS:
        return f"action '{step.action}' is not allow-listed"
    if step.path:
        parsed = urlparse(step.path)
        if parsed.scheme or parsed.netloc:
            if not step.path.startswith(base_url):
                return f"navigation outside StageUI ({step.path})"
        if DESTRUCTIVE.search(step.path):
            return f"destructive path '{step.path}'"
    if step.action in {"click", "fill", "select"} and step.target:
        described = " ".join(filter(None, [step.target.name, step.target.label, step.target.text, step.target.testid]))
        if DESTRUCTIVE.search(described):
            return f"destructive target '{described}'"
    return None


def resolve_placeholders(value: str, user: str, password: str) -> str:
    return (value.replace("${STAGE_USER}", user)
                 .replace("${STAGE_PASSWORD}", password)
                 .replace("${TODAY}", date.today().isoformat()))


def mask_secrets(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, MASK)
    return text


def scrub_zip(path: Path, secrets: list[str]) -> None:
    """Rewrite an archive (e.g. Playwright trace) with secrets masked, including URL-encoded forms."""
    needles = {s.encode() for s in secrets if s} | {quote_plus(s).encode() for s in secrets if s}
    tmp = path.with_suffix(".scrub")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item)
            for needle in needles:
                data = data.replace(needle, MASK.encode())
            dst.writestr(item, data)
    tmp.replace(path)

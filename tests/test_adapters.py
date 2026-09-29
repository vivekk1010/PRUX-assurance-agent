import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.adapters.generic_web import GenericWebAdapter
from agent.guardrails import check_step, resolve_placeholders
from agent.models import Step, Target


def settings(tmp_path: Path, **overrides):
    values = dict(
        target_profile=None, target_health_path="/health",
        stage_base_url="https://app.example.com", stage_user="user", stage_password="secret",
        target_allowed_origins=[], target_auth_method="form", target_storage_state=None,
        target_headers_json="{}", target_read_only=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_generic_form_login_keeps_secret_placeholders(tmp_path: Path):
    adapter = GenericWebAdapter(settings(tmp_path))
    steps = adapter.login_steps()
    assert steps[1].value == "${TARGET_USER}"
    assert steps[2].value == "${TARGET_PASSWORD}"
    assert resolve_placeholders(steps[2].value, "u", "p") == "p"


def test_storage_state_and_header_auth(tmp_path: Path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"cookies": [{"value": "token-secret"}]}), encoding="utf-8")
    adapter = GenericWebAdapter(settings(
        tmp_path, target_auth_method="storage_state", target_storage_state=state
    ))
    assert adapter.context_options()["storage_state"] == str(state)
    assert "token-secret" in adapter.secrets()

    adapter = GenericWebAdapter(settings(
        tmp_path, target_auth_method="headers",
        target_headers_json='{"Authorization":"Bearer abc"}',
    ))
    assert adapter.context_options()["extra_http_headers"]["Authorization"] == "Bearer abc"


def test_guardrail_uses_exact_origin_and_read_only():
    base = "https://app.example.com"
    assert check_step(Step(action="goto", path="https://app.example.com.evil/x"), base)
    assert check_step(Step(action="goto", path="javascript:alert(1)"), base)
    assert check_step(
        Step(action="click", target=Target(role="button", name="Publish")),
        base, read_only=True,
    )
    assert check_step(
        Step(action="click", target=Target(role="button", name="Log in")),
        base, read_only=True,
    ) is None


def test_storage_state_must_exist(tmp_path: Path):
    adapter = GenericWebAdapter(settings(
        tmp_path, target_auth_method="storage_state", target_storage_state=tmp_path / "missing.json"
    ))
    with pytest.raises(FileNotFoundError):
        adapter.context_options()

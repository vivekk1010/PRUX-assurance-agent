import json

from agent.adapters.base import BaseAdapter
from agent.models import Step, Target


def _string_values(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    return []


class GenericWebAdapter(BaseAdapter):
    name = "generic_web"

    def login_steps(self) -> list[Step]:
        if self.settings.target_auth_method != "form":
            return []
        auth = self.profile.get("auth", {})
        return [
            Step(action="goto", path=auth.get("login_path", "/login")),
            Step(action="fill", target=Target(label=auth.get("username_label", "Username")), value="${TARGET_USER}"),
            Step(action="fill", target=Target(label=auth.get("password_label", "Password")), value="${TARGET_PASSWORD}"),
            Step(action="click", target=Target(role="button", name=auth.get("submit_name", "Log in"))),
        ]

    def context_options(self) -> dict:
        options = {}
        method = self.settings.target_auth_method
        if method == "storage_state":
            path = self.settings.target_storage_state
            if path is None or not path.is_file():
                raise FileNotFoundError("TARGET_STORAGE_STATE is required and must exist")
            options["storage_state"] = str(path)
        elif method == "headers":
            headers = json.loads(self.settings.target_headers_json)
            if not isinstance(headers, dict):
                raise ValueError("TARGET_HEADERS_JSON must be a JSON object")
            options["extra_http_headers"] = {str(k): str(v) for k, v in headers.items()}
        elif method not in {"form", "none"}:
            raise ValueError(f"Unsupported TARGET_AUTH_METHOD '{method}'")
        return options

    def secrets(self) -> list[str]:
        values = [self.settings.stage_password]
        try:
            values += _string_values(json.loads(self.settings.target_headers_json))
        except json.JSONDecodeError:
            pass
        if self.settings.target_storage_state and self.settings.target_storage_state.is_file():
            try:
                values += _string_values(json.loads(self.settings.target_storage_state.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
        return [value for value in values if value]

    def supports(self, capability: str) -> bool:
        if capability == "form_auth":
            return self.settings.target_auth_method == "form"
        return super().supports(capability)

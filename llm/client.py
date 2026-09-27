"""Provider-agnostic LLM gateway.

LLM_PROVIDER=openai  -> OpenAI API (OPENAI_API_KEY, optional OPENAI_BASE_URL for compatible endpoints)
LLM_PROVIDER=azure   -> Azure OpenAI (AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT)
LLM_PROVIDER=replay  -> recorded outputs in llm/replay/<task>/<key>.json (no key, zero cost)
"""
import base64
import json
import os
import time
from pathlib import Path
from string import Template
from typing import Optional, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class ReplayMissing(Exception):
    pass


class LLM:
    def __init__(self, provider: str, model: str, replay_dir: Path, prompts_dir: Path, record: bool = False,
                 vision_model: Optional[str] = None):
        self.provider = provider
        self.model = model
        self.vision_model = vision_model or model
        self.replay_dir = replay_dir
        self.prompts_dir = prompts_dir
        self.record = record
        self.calls: list[dict] = []
        self._client = None

    @classmethod
    def from_settings(cls, settings) -> "LLM":
        return cls(settings.llm_provider, settings.llm_model, settings.replay_dir, settings.prompts_dir,
                   settings.llm_record, settings.vision_model)

    @property
    def is_live(self) -> bool:
        return self.provider in {"openai", "azure"}

    def prompt(self, name: str, **values) -> str:
        return Template((self.prompts_dir / f"{name}.md").read_text(encoding="utf-8")).safe_substitute(**values)

    def usage_summary(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model if self.is_live else "replay",
            "calls": len(self.calls),
            "prompt_tokens": sum(c.get("prompt_tokens", 0) for c in self.calls),
            "completion_tokens": sum(c.get("completion_tokens", 0) for c in self.calls),
            "latency_ms": sum(c.get("latency_ms", 0) for c in self.calls),
            "by_task": [{k: c[k] for k in ("task", "key", "source", "model", "latency_ms", "prompt_tokens", "completion_tokens")
                         if k in c} for c in self.calls],
        }

    def vision(self, task: str, key: str, system: str, text: str, images: list[Path], schema: type[T]) -> T:
        """Structured output from a vision-capable model given one or more PNG images."""
        content: list[dict] = [{"type": "text", "text": text}]
        for img in images:
            b64 = base64.b64encode(Path(img).read_bytes()).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}})
        return self.structured(task, key, system, content, schema, model=self.vision_model)

    def structured(self, task: str, key: str, system: str, user: str | list, schema: type[T],
                   model: Optional[str] = None) -> T:
        if not self.is_live:
            data = self._replay(task, key)
            self.calls.append({"task": task, "key": key, "source": "replay", "latency_ms": 0})
            return schema.model_validate(data)

        messages = [
            {"role": "system", "content": system + "\n\nRespond with a single JSON object that matches this JSON schema:\n"
                + json.dumps(schema.model_json_schema())},
            {"role": "user", "content": user},
        ]
        last_error: Optional[str] = None
        for _ in range(2):
            if last_error:
                messages.append({"role": "user", "content": f"Your JSON failed validation: {last_error}. Return corrected JSON only."})
            content = self._chat(task, key, messages, model=model, response_format={"type": "json_object"}).content or "{}"
            try:
                result = schema.model_validate_json(content)
                self._save_replay(task, key, json.loads(content))
                return result
            except ValidationError as exc:
                messages.append({"role": "assistant", "content": content})
                last_error = str(exc)[:2000]
        raise ValueError(f"LLM output for {task}/{key} failed validation: {last_error}")

    def choose_tool(self, task: str, key: str, system: str, user: str, tools: list[dict]) -> Optional[dict]:
        """Ask the model to pick exactly one tool. Returns {"name", "arguments"} or None."""
        if not self.is_live:
            try:
                data = self._replay(task, key)
            except ReplayMissing:
                return None
            self.calls.append({"task": task, "key": key, "source": "replay", "latency_ms": 0})
            return data
        message = self._chat(
            task, key,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=tools, tool_choice="required",
        )
        if not message.tool_calls:
            return None
        call = message.tool_calls[0].function
        result = {"name": call.name, "arguments": json.loads(call.arguments or "{}")}
        self._save_replay(task, key, result)
        return result

    def _chat(self, task: str, key: str, messages: list[dict], model: Optional[str] = None, **kwargs):
        client = self._get_client()
        model = model or self.model
        if self.provider == "azure":
            env = "AZURE_OPENAI_VISION_DEPLOYMENT" if model == self.vision_model != self.model else "AZURE_OPENAI_DEPLOYMENT"
            model = os.getenv(env, model)
        start = time.perf_counter()
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0, **kwargs)
        usage = resp.usage
        self.calls.append({
            "task": task, "key": key, "source": self.provider, "model": model,
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
        })
        return resp.choices[0].message

    def _get_client(self):
        if self._client is None:
            if self.provider == "azure":
                from openai import AzureOpenAI
                self._client = AzureOpenAI(
                    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                    api_key=os.environ["AZURE_OPENAI_API_KEY"],
                    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
                )
            else:
                from openai import OpenAI
                self._client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None)
        return self._client

    def _replay(self, task: str, key: str) -> dict:
        path = self.replay_dir / task / f"{key}.json"
        if not path.exists():
            raise ReplayMissing(str(path))
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_replay(self, task: str, key: str, data: dict) -> None:
        if not self.record:
            return
        path = self.replay_dir / task / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

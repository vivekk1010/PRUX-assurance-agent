import json
import os
from typing import Any

from agent.evaluation.models import AdvisoryMetricConfig, JudgeConfig


class DeepEvalUnavailable(RuntimeError):
    pass


def _openai_compatible_model(config: JudgeConfig):
    try:
        from deepeval.models import DeepEvalBaseLLM
        from openai import AsyncOpenAI, OpenAI
    except ImportError as exc:
        raise DeepEvalUnavailable(
            "DeepEval advisory evaluation is enabled but optional dependencies are "
            "missing; install requirements-evaluation.txt"
        ) from exc

    api_key = os.getenv(config.api_key_env)
    if not api_key and config.provider == "openai-compatible":
        raise ValueError(f"{config.api_key_env} is required for openai-compatible judges")
    api_key = api_key or "local-evaluator"

    class OpenAICompatibleJudge(DeepEvalBaseLLM):
        def __init__(self):
            self.client = OpenAI(
                api_key=api_key, base_url=config.base_url, timeout=config.timeout_seconds
            )
            self.async_client = AsyncOpenAI(
                api_key=api_key, base_url=config.base_url, timeout=config.timeout_seconds
            )

        def load_model(self):
            return self.client

        @staticmethod
        def _content(response) -> str:
            content = response.choices[0].message.content
            if not content:
                raise ValueError("judge returned an empty response")
            return content

        @staticmethod
        def _coerce(content: str, schema):
            if schema is None:
                return content
            return schema.model_validate_json(content)

        def generate(self, prompt: str, schema=None, **_: Any):
            kwargs: dict[str, Any] = {
                "model": config.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            }
            if schema is not None:
                kwargs["response_format"] = {"type": "json_object"}
            response = self.client.chat.completions.create(**kwargs)
            return self._coerce(self._content(response), schema)

        async def a_generate(self, prompt: str, schema=None, **_: Any):
            kwargs: dict[str, Any] = {
                "model": config.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            }
            if schema is not None:
                kwargs["response_format"] = {"type": "json_object"}
            response = await self.async_client.chat.completions.create(**kwargs)
            return self._coerce(self._content(response), schema)

        def get_model_name(self):
            return f"{config.provider}:{config.model}"

    return OpenAICompatibleJudge()


class DeepEvalGEvalJudge:
    """DeepEval adapter kept behind lazy imports so disabled mode stays lightweight."""

    def __init__(self, config: JudgeConfig):
        self.config = config
        self.model = _openai_compatible_model(config)

    def evaluate(
        self,
        *,
        metric: AdvisoryMetricConfig,
        story_key: str,
        input_text: str,
        actual_output: dict,
        expected_output: str,
        context: list[str],
    ) -> tuple[float, str]:
        try:
            from deepeval.metrics import GEval
            from deepeval.test_case import LLMTestCase, SingleTurnParams
        except ImportError as exc:
            raise DeepEvalUnavailable(
                "DeepEval advisory evaluation is enabled but deepeval is unavailable"
            ) from exc

        params = [
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
            SingleTurnParams.CONTEXT,
        ]
        kwargs: dict[str, Any] = {
            "name": metric.name,
            "criteria": metric.criteria,
            "evaluation_params": params,
            "threshold": metric.threshold,
            "model": self.model,
            "async_mode": False,
        }
        if metric.evaluation_steps:
            kwargs["evaluation_steps"] = metric.evaluation_steps
            kwargs.pop("criteria")
        evaluator = GEval(**kwargs)
        test_case = LLMTestCase(
            input=input_text,
            actual_output=json.dumps(actual_output, sort_keys=True),
            expected_output=expected_output,
            context=context,
        )
        evaluator.measure(test_case)
        return float(evaluator.score or 0.0), str(evaluator.reason or "")

import json
from pathlib import Path

from agent.evaluation.models import AdvisoryEvaluationConfig


def load_advisory_config(path: Path) -> AdvisoryEvaluationConfig:
    if not path.is_file():
        return AdvisoryEvaluationConfig()
    return AdvisoryEvaluationConfig.model_validate_json(path.read_text(encoding="utf-8"))


def dump_advisory_config(config: AdvisoryEvaluationConfig) -> str:
    return json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"

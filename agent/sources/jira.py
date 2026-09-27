"""Requirements source. File-based mock of Jira; swap for the Jira REST API behind the same functions."""
import json
from pathlib import Path

from agent.models import Story


def list_story_keys(stories_dir: Path) -> list[str]:
    return sorted(p.stem for p in stories_dir.glob("*.json"))


def load_story(stories_dir: Path, key: str) -> Story:
    path = stories_dir / f"{key}.json"
    if not path.exists():
        raise FileNotFoundError(f"Story {key} not found in {stories_dir}")
    return Story.model_validate(json.loads(path.read_text(encoding="utf-8")))

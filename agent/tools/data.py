"""Read-only source data access and four-way calculation reconciliation (UI, API, calculated, source)."""
import math
import re
import sqlite3
from pathlib import Path


class ReadOnlyDB:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        if not re.match(r"^\s*select\b", sql, re.IGNORECASE) or ";" in sql.strip().rstrip(";"):
            raise PermissionError("Only single SELECT statements are allowed")
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def close(self) -> None:
        self.conn.close()


def _words(content: str) -> int:
    return len(content.split())


CALCULATIONS = {
    "word_count": {
        "rule": "BR-META-01",
        "ui_testid": "post-words",
        "api_field": "word_count",
        "expected": _words,
        "parse_ui": lambda s: int(s.strip()),
    },
    "reading_time": {
        "rule": "BR-META-02",
        "ui_testid": "post-reading-time",
        "api_field": "reading_time_min",
        "expected": lambda content: max(1, math.ceil(_words(content) / 200)),
        "parse_ui": lambda s: int(s.strip().split()[0]),
    },
}


def reconcile(name: str, ui_rows: dict[int, str], api_posts: list[dict], source_rows: list[dict]) -> dict:
    """Compare per post: value shown in UI, value from API, value calculated from source content."""
    calc = CALCULATIONS[name]
    api_by_id = {p["id"]: p for p in api_posts}
    source_by_id = {r["id"]: r for r in source_rows}
    rows, problems = [], []
    for post_id, ui_text in ui_rows.items():
        source = source_by_id.get(post_id)
        api = api_by_id.get(post_id, {})
        ui_value = calc["parse_ui"](ui_text)
        api_value = api.get(calc["api_field"])
        expected = calc["expected"](source["content"]) if source else None
        finding = "ok"
        if source is None:
            finding = "source row missing (data issue)"
        elif api_value != expected:
            finding = "API value breaks business rule (calculation issue)"
        elif ui_value != api_value:
            finding = "UI differs from API (display issue)"
        row = {
            "post_id": post_id,
            "title": source["title"] if source else api.get("title"),
            "source_words": _words(source["content"]) if source else None,
            "ui": ui_value, "api": api_value, "expected": expected, "finding": finding,
        }
        rows.append(row)
        if finding != "ok":
            problems.append(row)
    return {"calculation": name, "rule": calc["rule"], "rows": rows, "problems": problems}

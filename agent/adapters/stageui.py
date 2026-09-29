import subprocess
import sys
import json

from agent.config import ROOT
from agent.adapters.base import BaseAdapter
from agent.models import Step, Target
from agent.tools.data import CALCULATIONS, ReadOnlyDB, reconcile


class StageUIAdapter(BaseAdapter):
    name = "stageui"

    @property
    def start_module(self) -> str | None:
        return "stageui_app"

    @property
    def list_path(self) -> str:
        return "/blogs"

    @property
    def row_title_testid(self) -> str:
        return "post-title"

    def login_steps(self) -> list[Step]:
        return [
            Step(action="goto", path="/login"),
            Step(action="fill", target=Target(label="Username"), value="${TARGET_USER}"),
            Step(action="fill", target=Target(label="Password"), value="${TARGET_PASSWORD}"),
            Step(action="click", target=Target(role="button", name="Log in")),
        ]

    def reset(self) -> None:
        subprocess.run(
            [sys.executable, "-m", self.settings.stage_reset_module],
            cwd=ROOT, check=True, capture_output=True,
        )

    def supports(self, capability: str) -> bool:
        return capability in {"form_auth", "reset", "rows", "calculations", "sqlite"}

    def check_calculation(self, session, name: str):
        if name not in CALCULATIONS:
            return "error", f"unknown calculation '{name}'", {}
        if not session.page.url.rstrip("/").endswith(self.list_path.rstrip("/")):
            session.page.goto(self.list_path)
            session._settle()
        rows = session.page.get_by_test_id("post-row")
        if not session._visible(rows, session.s.step_timeout_ms):
            return "missing", "no post rows on My Blogs", {"reason": "not_found"}
        testid = CALCULATIONS[name]["ui_testid"]
        ui_rows = {int(r.get_attribute("data-post-id")): r.get_by_test_id(testid).inner_text() for r in rows.all()}
        api = session.page.request.get("/api/posts")
        api_posts = api.json()
        session.network.append({"method": "GET", "url": api.url, "status": api.status, "body": api_posts, "source": "agent"})
        db = ReadOnlyDB(session.s.stage_db_path)
        try:
            marks = ",".join("?" * len(ui_rows))
            source = db.query(f"SELECT id, title, content FROM posts WHERE id IN ({marks})", tuple(ui_rows))
        finally:
            db.close()
        result = reconcile(name, ui_rows, api_posts, source)
        (session.out_dir / f"calculation-{name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        if result["problems"]:
            summary = "; ".join(
                f"'{p['title']}': UI={p['ui']} API={p['api']} expected={p['expected']} "
                f"(words={p['source_words']}) -> {p['finding']}"
                for p in result["problems"]
            )
            return (
                "mismatch",
                f"{len(result['problems'])}/{len(result['rows'])} posts break {result['rule']}: {summary}",
                result,
            )
        return "ok", f"all {len(result['rows'])} posts match {result['rule']}", result

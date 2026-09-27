import os

import pytest

from stageui_app import seed
from stageui_app.app import create_app


@pytest.fixture()
def client():
    seed.reset()
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _login(client, password=None):
    return client.post("/login", data={"username": "alice", "password": password or os.environ["STAGE_PASSWORD"]})


def test_login_and_isolation(client):
    assert _login(client, "wrong").status_code == 200
    assert _login(client).status_code == 302
    titles = [p["title"] for p in client.get("/api/posts").get_json()]
    assert titles == ["Notes on RAG", "Getting started with Playwright", "Weekend hike"]


def test_protected_pages_redirect(client):
    assert client.get("/blogs").status_code == 302
    assert client.get("/api/posts").status_code == 401


def test_known_reading_time_defect_is_present(client):
    _login(client)
    post = next(p for p in client.get("/api/posts").get_json() if p["word_count"] == 450)
    assert post["reading_time_min"] == 2  # BR-META-02 expects 3

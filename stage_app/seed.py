"""Reset the Stage database to the controlled seed in knowledge_base/test_data.md."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

from stage_app.db import DB_PATH, connect, init_schema

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

WORDS = (
    "the quick agent reads each story then plans small steps checks the page "
    "records evidence and writes a clear report for the team to review"
).split()


def filler(n_words: int) -> str:
    return " ".join(WORDS[i % len(WORDS)] for i in range(n_words))


def users() -> list[tuple[str, str, str]]:
    password = os.getenv("STAGE_PASSWORD")
    if not password:
        raise SystemExit("STAGE_PASSWORD is not set. Add it to .env (see .env.example).")
    return [
        ("alice", "Alice Sharma", password),
        ("bob", "Bob Mehta", os.getenv("STAGE_BOB_PASSWORD") or secrets.token_urlsafe(16)),
    ]

POSTS = [
    ("alice", "Weekend hike", 260, "travel", "2026-09-18"),
    ("alice", "Getting started with Playwright", 450, "testing,automation", "2026-09-20"),
    ("bob", "Bob's dal recipe", 80, "food", "2026-09-21"),
    ("alice", "Notes on RAG", 120, "ai,rag", "2026-09-22"),
]


def reset() -> None:
    conn = connect()
    init_schema(conn)
    conn.executescript("DELETE FROM posts; DELETE FROM users; DELETE FROM sqlite_sequence;")
    ids = {}
    for username, display, password in users():
        cur = conn.execute(
            "INSERT INTO users (username, display_name, password_hash) VALUES (?, ?, ?)",
            (username, display, generate_password_hash(password)),
        )
        ids[username] = cur.lastrowid
    for username, title, words, tags, published in POSTS:
        conn.execute(
            "INSERT INTO posts (user_id, title, content, tags, published) VALUES (?, ?, ?, ?, ?)",
            (ids[username], title, filler(words), tags, published),
        )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    reset()
    print(f"Seeded {DB_PATH}")

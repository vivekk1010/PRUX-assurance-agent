"""Blog Notes: reference StageUI application.

Known issues seeded in this build (expected findings, see PRD-001 §11):
  1. reading_time_min uses floor instead of ceil          -> BLOG-103 AC-03 DEFECT
  2. tag filter is a single-select, Figma has multi-select -> BLOG-104 AC-01 GAP
  3. save button says "Save post", Figma says "Publish"   -> approved variance, PASS
"""
import os
import secrets
from datetime import date
from functools import wraps

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from stageui_app.db import connect


def word_count(content: str) -> int:
    return len(content.split())


def reading_time_min(words: int) -> int:
    return max(1, words // 200)


def parse_tags(raw: str) -> list[str]:
    return [t.strip().lower() for t in raw.split(",") if t.strip()]


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("STAGE_SECRET_KEY") or secrets.token_hex(32)

    def db():
        if "db" not in g:
            g.db = connect()
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    def current_user():
        uid = session.get("user_id")
        if uid is None:
            return None
        return db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()

    def login_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if current_user() is None:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "unauthorized"}), 401
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapper

    def serialize(row, author: str) -> dict:
        words = word_count(row["content"])
        return {
            "id": row["id"],
            "title": row["title"],
            "author": author,
            "published": row["published"],
            "tags": parse_tags(row["tags"]),
            "word_count": words,
            "reading_time_min": reading_time_min(words),
        }

    @app.get("/")
    def index():
        return redirect(url_for("blogs"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            user = db().execute(
                "SELECT * FROM users WHERE username = ?", (request.form.get("username", ""),)
            ).fetchone()
            if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
                session.clear()
                session["user_id"] = user["id"]
                return redirect(url_for("blogs"))
            error = "Invalid username or password"
        return render_template("login.html", error=error)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/blogs")
    @login_required
    def blogs():
        user = current_user()
        rows = db().execute("SELECT tags FROM posts WHERE user_id = ?", (user["id"],)).fetchall()
        all_tags = sorted({t for r in rows for t in parse_tags(r["tags"])})
        return render_template(
            "blogs.html", user=user, all_tags=all_tags, selected=request.args.get("tag", "")
        )

    @app.route("/blogs/new", methods=["GET", "POST"])
    @login_required
    def new_post():
        user = current_user()
        error = None
        form = {"title": "", "content": "", "tags": ""}
        if request.method == "POST":
            form = {k: request.form.get(k, "").strip() for k in form}
            if not form["title"]:
                error = "Title is required"
            elif not form["content"]:
                error = "Content is required"
            else:
                db().execute(
                    "INSERT INTO posts (user_id, title, content, tags, published) VALUES (?, ?, ?, ?, ?)",
                    (user["id"], form["title"], form["content"],
                     ",".join(parse_tags(form["tags"])), date.today().isoformat()),
                )
                db().commit()
                return redirect(url_for("blogs"))
        return render_template("new_post.html", user=user, error=error, form=form)

    @app.get("/api/me")
    @login_required
    def api_me():
        user = current_user()
        return jsonify({"username": user["username"], "display_name": user["display_name"]})

    @app.get("/api/posts")
    @login_required
    def api_posts():
        user = current_user()
        wanted = set(parse_tags(request.args.get("tags", "")))
        rows = db().execute(
            "SELECT * FROM posts WHERE user_id = ? ORDER BY published DESC, id DESC", (user["id"],)
        ).fetchall()
        posts = [serialize(r, user["display_name"]) for r in rows]
        if wanted:
            posts = [p for p in posts if wanted & set(p["tags"])]
        return jsonify(posts)

    return app


if __name__ == "__main__":
    port = int(os.getenv("STAGE_PORT", "5055"))
    create_app().run(host="127.0.0.1", port=port, debug=False)

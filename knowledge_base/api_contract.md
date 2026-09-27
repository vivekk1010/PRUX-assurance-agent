# Blog Notes: StageUI API and UI Contract (Engineering Context)

Base URL: `STAGE_BASE_URL` (default `http://127.0.0.1:5055`). All `/api/*` endpoints require a session cookie.

## Pages

| Path | Purpose |
|---|---|
| `GET /login` | Login form (Username, Password, `Log in`) |
| `POST /login` | Sign in; redirects to `/blogs` |
| `GET /blogs` | My Blogs list; accepts `?tag=<tag>` |
| `GET /blogs/new` | New post form |
| `POST /blogs/new` | Save post; redirects to `/blogs` |
| `POST /logout` | End session; redirects to `/login` |

## JSON API

### `GET /api/me`
```json
{"username": "alice", "display_name": "Alice Sharma"}
```

### `GET /api/posts?tags=a,b`
Returns the logged-in user's posts, newest first.
```json
[
  {
    "id": 1,
    "title": "Getting started with Playwright",
    "author": "Alice Sharma",
    "published": "2026-09-20",
    "tags": ["testing", "automation"],
    "word_count": 450,
    "reading_time_min": 3
  }
]
```

## Stable UI hooks (data-testid)

| testid | Element |
|---|---|
| `welcome` | Welcome banner on My Blogs |
| `post-row` | One row per post (`data-post-id` attribute) |
| `post-title`, `post-author`, `post-date`, `post-words`, `post-reading-time` | Cells inside a row |
| `login-error` | Login error message |
| `form-error` | New post validation error |

## Data store (read-only for the agent)

SQLite file `stageui_app/instance/blog.db`.

| Table | Columns |
|---|---|
| `users` | `id`, `username`, `display_name`, `password_hash` |
| `posts` | `id`, `user_id`, `title`, `content`, `tags` (comma-separated), `published` (YYYY-MM-DD) |

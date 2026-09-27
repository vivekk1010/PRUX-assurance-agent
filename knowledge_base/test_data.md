# Blog Notes: Controlled Test Data

The Stage database is reset to this seed before each assurance run (`python -m stage_app.seed`).

## Users

Passwords are **not** stored here. The agent reads them from `STAGE_USER` / `STAGE_PASSWORD` and never sends them to the LLM.

| Username (login) | Display name (shown in the UI) | Role in tests |
|---|---|---|
| `alice` | Alice Sharma | Primary test user (`STAGE_USER`) |
| `bob` | Bob Mehta | Second user, used to check post isolation |

After login the header shows `Welcome, Alice Sharma` and the Author field shows `Alice Sharma`.

## Alice's seeded posts (what the primary test user sees, newest first)

The primary test user sees exactly these three posts and never sees Bob's posts.

| Title | Published | Tags | Words | Expected reading time |
|---|---|---|---|---|
| Notes on RAG | 2026-09-22 | ai, rag | 120 | 1 min |
| Getting started with Playwright | 2026-09-20 | testing, automation | 450 | 3 min |
| Weekend hike | 2026-09-18 | travel | 260 | 2 min |

## Bob's seeded posts (never visible to Alice)

| Title | Published | Tags | Words |
|---|---|---|---|
| Bob's dal recipe | 2026-09-21 | food | 80 |

## Tag filter expectations for the primary test user

Available tags: ai, automation, rag, testing, travel.

| Selected tags | Expected titles (complete list) |
|---|---|
| `ai` | Notes on RAG |
| `travel` | Weekend hike |
| `testing` | Getting started with Playwright |
| `ai`, `travel` | Notes on RAG, Weekend hike |
| none (after Clear filters) | Notes on RAG, Getting started with Playwright, Weekend hike |

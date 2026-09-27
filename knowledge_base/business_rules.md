# Blog Notes: Business Rules

## Authentication

### BR-AUTH-01 Valid login
A user with a matching username and password is signed in and redirected to `My Blogs` (`/blogs`). The header shows `Welcome, <display name>`.

### BR-AUTH-02 Invalid login
A wrong username or password shows exactly `Invalid username or password`. The user stays on the Login page. The message must not reveal which field was wrong.

### BR-AUTH-03 Session protection
All pages except Login require a session. Without a session the app redirects to `/login`. `Log out` clears the session.

## Posts

### BR-POST-01 Required fields
Title and Content are required. Missing title shows `Title is required`. Missing content shows `Content is required`.

### BR-POST-02 Author
Author is always the logged-in user's display name. Users cannot set or edit the author.

### BR-POST-03 Published date
The published date is the server date when the post is saved, shown as `YYYY-MM-DD`.

### BR-POST-04 Ordering
`My Blogs` lists the user's own posts, newest first. Users never see other users' posts.

## Metadata calculations

### BR-META-01 Word count
Word count = number of whitespace-separated tokens in Content. Example: `"hello   big world"` → 3.

### BR-META-02 Reading time
Reading time (minutes) = `ceil(word_count / 200)`, minimum 1.
Examples: 120 words → 1 min, 200 words → 1 min, 201 words → 2 min, 450 words → 3 min.

### BR-META-03 Display
The list shows `Words` as an integer and `Reading time` as `<n> min`.

## Tags

### BR-TAG-01 Tag format
Tags are entered comma-separated, stored lowercase and trimmed. Example: `" AI, Rag "` → `ai`, `rag`.

### BR-TAG-02 Tag filter
Filtering by several tags uses OR logic: a post matches if it has any selected tag. `Clear filters` removes all tag filters.

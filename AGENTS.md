# AGENTS.md

Conventions for AI sessions working on study.Now(). Read this before editing.

## What this is

A study-time tracker. Users register, create categories, run a stopwatch, and
save a session with a duration and an optional description. History lists past
sessions per user.

## Stack

Flask application factory, Flask-SQLAlchemy, Alembic via Flask-Migrate,
PostgreSQL via psycopg 3, Flask-WTF CSRF, Flask-Limiter, pytest. Templates are
Jinja2. The front end is hand-written CSS in `static/styles.css` plus two plain
JavaScript files. There is **no CSS framework and no build step**, and none
should be added.

## Layout

| Path | Purpose |
| --- | --- |
| `app.py` | Application factory, error handlers, security headers, `duration` and `human` filters |
| `config.py` | `development` / `testing` / `production` config classes |
| `extensions.py` | Unbound extension singletons, imported by models and blueprints |
| `models.py` | `User`, `Category`, `StudySession` |
| `auth.py` | `/register`, `/login`, `/logout` |
| `categories.py` | `/categories`, `/delete-category`, `/goupdate` |
| `timer.py` | `/`, `/history`, `/finish`, `/desc`, `/delete-session`, `/select-category` |
| `stats.py` | Read-only aggregates over the caller's own sessions |
| `helpers.py` | `login_required`, `current_user_id`, and the id/ownership rules in `read_id` / `load_owned` |
| `wsgi.py` | Entry point for gunicorn on Render |
| `static/styles.css` | The whole design system. Tokens at the top. |
| `static/app.js` | Shared UI: nav toggle, toasts, delete confirmation |
| `static/timer.js` | Focus timer. Owns the client-side session state. |
| `migrations/` | Alembic; always the source of truth for schema |
| `tests/` | pytest suite |

## Environment

- Always use `.venv\Scripts\python.exe`. Never install into global Python.
- `pip install -r requirements.txt`. Keep `requirements.txt` pinned.
- `.env` holds `SECRET_KEY`, `DATABASE_URL`, and `TEST_DATABASE_URL`. Copy from
  `.env.example`. Never commit `.env` or paste secrets into chat.
- `APP_ENV` selects the config class.

## Rules

1. **Never trust an id from the client.** Every read or write of a category or
   session must filter on `user_id == current_user_id()`. The policy is: an id
   that does not exist is `404`; an id that exists but belongs to someone else
   is `403`. Do not return the same code for both, and do not use one policy in
   one route and a different one in another. Parse the id as an integer first
   (`helpers.read_id`) so a junk value is a `404` rather than a `500` from the
   driver. Implement the lookup with `helpers.load_owned`, which is the only
   place that rule lives; a route that hand-rolls its own query will drift.
   Note that distinguishing 403 from 404 is deliberately an existence oracle,
   which is the accepted trade for telling the caller which mistake they made.
2. **Never accept bare `int()` from user input.** Durations arrive as JSON and
   need a type check, a positivity check, and an upper bound. Booleans are not
   valid durations.
3. **Every mutating route needs CSRF.** Forms carry
   `<input name="csrf_token" type="hidden" value="{{ csrf_token() }}">`;
   JSON calls send an `X-CSRFToken` header read from the
   `<meta name="csrf-token">` tag in `layout.html`.
   Two routes are deliberate exceptions, because a plain navigation cannot
   carry a token: `GET /logout`, which is an `<a href>` in the nav, and
   `GET /finish`, which the timer reaches with `location.href`. Both are kept
   safe another way — `/finish` hands out a single-use token that `POST /desc`
   requires, so a forged GET records nothing. Treat adding a third such route
   as a rule break, not a precedent.
4. **Never do `row["column"]` in a template.** These are SQLAlchemy models, so
   use `row.column` and `row.relationship.attribute`.
5. **Schema changes go through Alembic.** Write a migration; do not use
   `db.create_all()` outside tests.
6. **PostgreSQL needs explicit `ON DELETE CASCADE`.** The old SQLite build lost
   its foreign keys and silently dropped rows from history.
7. **Rate limits belong on credential submission only** (`methods=["POST"]`).
   Limiting GETs locks users out of pages they are allowed to reload.
8. **Always check before making a major push to the github**
9. **Before you move on with the next task have a "review agent" check all of the work that you have done to ensure it works well**

## Design system

`static/styles.css` is the single source of visual truth. Read the token block
before adding any CSS.

- **Use the tokens.** Spacing comes from `--s-1` to `--s-16`, colour from the
  named variables, radius from `--r-*`. A raw hex or a one-off `padding: 13px`
  is a bug.
- **One accent.** `--accent` is reserved for the primary action, the active
  nav item, and focus rings. Never introduce a second brand colour. The
  `--dot-1` to `--dot-5` ramp exists so many subjects can be told apart
  without random colours.
- **Semantic colour means something.** `--danger` is for destructive actions
  and errors, `--success` for genuine success, `--warning` for a state needing
  attention. Not decoration.
- **Reach for the component classes** in section 06 to 15 (`.btn`, `.card`,
  `.field`, `.stat`, `.bars`, `.split-bar`, `.alert`, `.badge`, `.empty`,
  `.subject-dot`, `.chip`) before writing a new one. Repeating a pattern is how
  a design drifts.
- **No inline `style=""` for presentation.** Use a utility or component class
  (`.text-strong`, `.text-nowrap`, `.link-accent`, `.list-row`,
  `.subject-line`). The only acceptable inline styles are a CSS custom
  property set from a template (`style="--bar: 40%"`, `style="--dot: var(--dot-1)"`)
  and a data-driven dimension (`style="width: 33%"`), because no stylesheet can
  know the value. `test_no_inline_style_attributes_for_presentation` enforces
  this.
- **Layout is a grid, not a page.** `.shell`, `.grid--split`, and `.page-aside`
  carry the responsive behaviour. Add a breakpoint only in the 17 section.
- **Touch targets are 40px minimum** (`.btn`), 32px only for secondary row
  actions.
- **Every input has a real `<label>`.** Placeholders are hints, never labels.
- **Empty states are mandatory.** Any list that can be empty uses
  `empty_state()` from `_macros.html` and says what to do next.
- **Motion is short and purposeful.** 120ms for hover, 180ms for state. Every
  animation is disabled under `prefers-reduced-motion`.

## Statistics

`stats.py` may only sum rows the caller already owns. Never store an aggregate,
never invent a value, and never show a number that is not derivable from
`sessions`. Day boundaries are UTC until a user timezone exists.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest
```

- The suite needs `TEST_DATABASE_URL` pointing at a throwaway database. It runs
  migrations once, then `TRUNCATE`s between tests. It must never point at dev
  or production; `config.py` refuses to build the testing config without it.
- `conftest.py` exposes `csrf(path)` to scrape a token from a rendered form and
  `post_json(url, payload)` to send JSON with the CSRF header.
- Use those helpers rather than inventing tokens, so tests exercise the same
  path a browser takes.
- Add a regression test with every security fix. A fix without a test is not
  done.

## Known state

- `gunicorn` is Linux-only; it is for Render, not local runs.
- `RATELIMIT_STORAGE_URI=memory://` is fine for one Render instance. Move to
  Redis before scaling out.
- Statistics bucket days in UTC. A user timezone needs a new column, so treat
  it as a product decision.
- The suite runs green against `TEST_DATABASE_URL`. It needs a real database -
  never a local SQLite file and never `DATABASE_URL` - because it runs the
  migrations once and `TRUNCATE`s between tests.
- `tests/js/timer_harness.js` holds the front-end behaviour checks. Pytest runs
  it through the `js_harness` fixture and skips that test when `node` is absent,
  so a machine without Node still gets the rest of the suite. Run it directly
  with `node tests/js/timer_harness.js` after touching `static/timer.js`.
- The `db_session` fixture shares one connection with the app's scoped session,
  so a view that calls `db.session.rollback()` (the duplicate-category paths in
  `categories.py`) also rolls back the test transaction. A test that needs to
  reach those paths must not rely on rows created by other fixtures.

# study.Now()

A study-time tracker. Register, create subjects, run a timer, and save what you
studied. History keeps every session and shows where the time went.

Originally a CS50x final project. The application has since been rebuilt on
PostgreSQL with a hand-written front end; the original project write-up is kept
in [docs/cs50-original.md](docs/cs50-original.md) for reference.

#### Video demo (original build): https://youtu.be/HFob03URjOE

## Stack

- Flask application factory, blueprints, Jinja2
- PostgreSQL via `psycopg` 3, SQLAlchemy 2, Alembic through Flask-Migrate
- Flask-WTF CSRF, Flask-Limiter, Werkzeug
- Hand-written CSS and two plain JavaScript files. No CSS framework, no build
  step, no front-end dependencies.

## How it works

`/login` and `/register` use hashed passwords. Everything else is behind
`@login_required`, and every category and session query is filtered on the
session's `user_id`, so one account can never read or change another's rows.

The timer lives in `static/timer.js` and talks to two JSON endpoints:

| Request | Payload | Header |
| --- | --- | --- |
| `POST /select-category` | `{"category_id": 3}` | `X-CSRFToken` |
| `POST /finish` | `{"duration": 3725, "category_id": 3}` | `X-CSRFToken` |

`duration` is whole seconds, greater than zero and at most 24 hours. The client
mirrors that limit so an over-long session is refused with a message instead of
a bare `400`.

`category_id` travels with the finish rather than relying on the earlier
`/select-category` call having landed: a browser restoring a `<select>` does not
raise a `change` event, so the server can be owed a subject it was never told
about. Both routes look the subject up with `load_owned`, so an id that does not
exist is `404` and one belonging to someone else is `403`.

`POST /finish` stages the session in the session cookie. `GET /finish` moves it
behind a single-use token and renders the description form, so revisiting the
page or pressing Back cannot save the same session twice or invent one that was
never studied. `POST /desc` consumes the token and writes the row.

The subject is locked for the whole of a run, not just once a second has passed,
so a stray scroll over the select cannot re-file the session under a different
subject. An in-progress timer is kept in `localStorage` under a key scoped to
the signed-in user and is cleared on logout.

### Database

Three tables: `users`, `categories`, `sessions`. Foreign keys cascade, so
deleting a subject deletes its sessions. Subject names are unique per user and
compared case-insensitively, enforced both in `categories.py` and by a
functional unique index.

A real session is only ever written from the caller's own rows; `stats.py` sums
what already exists and never stores an aggregate. Days are bucketed in UTC
until there is a user-timezone column.

## Running it locally

You need a PostgreSQL database. The old SQLite file is not used and there is no
migration path for it.

```powershell
git clone https://github.com/gabriel-gy-tan/study.Now.git
cd study.Now
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Then fill in `.env`:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Session signing. Generate one; never commit it. |
| `DATABASE_URL` | The database the app runs against. |
| `TEST_DATABASE_URL` | A **throwaway** database for the test suite. |
| `RATELIMIT_STORAGE_URI` | `memory://` is fine for a single instance. |
| `APP_ENV` | `development`, `testing`, or `production`. |

`config.py` refuses to build the testing config without `TEST_DATABASE_URL`,
because the suite truncates tables between tests and must never point at real
data.

```powershell
.\.venv\Scripts\python.exe -m flask --app wsgi db upgrade
.\.venv\Scripts\python.exe -m flask --app wsgi run
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The suite needs `TEST_DATABASE_URL` to point at an empty database; it runs the
migrations once and truncates between tests.

`tests/js/timer_harness.js` loads the real `static/timer.js` against a stub DOM
and a fake clock, so timer behaviour is asserted rather than inferred from the
markup - a button with no handler passes every template check. Pytest runs it and
**skips that test if `node` is not on `PATH`**, so a machine without Node still
gets everything else. Run it on its own with:

```powershell
node tests\js\timer_harness.js
```

## Deployment

`render.yaml` is a Render Blueprint: one web service pointed at Neon. The
database is external, so it is not declared in the file.

| Setting | Value | Why |
| --- | --- | --- |
| `DATABASE_URL` | `sync: false` | Pasted into the Render dashboard at Blueprint creation, so the production string never lands in the repository. |
| `SECRET_KEY` | `generateValue: true` | Generated once and held by Render. |
| `APP_ENV` | `production` | Selects `ProductionConfig`: `DEBUG = False`, `SESSION_COOKIE_SECURE = True`. |
| `RATELIMIT_STORAGE_URI` | `memory://` | Correct for a single instance. |
| `PYTHON_VERSION` | `3.14` | Matches the interpreter the suite runs on. |

**Use Neon's pooled endpoint** - the hostname containing `-pooler`. Render keeps
several connections open across a deploy, which is exactly what a direct
endpoint is rate limited against. And **never point `DATABASE_URL` at the test
branch**: the suite truncates it.

Migrations run on every deploy. `flask --app wsgi db upgrade` appears in both
`preDeployCommand` and `startCommand`, and the second one is what actually does
the work: Render only honours `preDeployCommand` on paid compute plans, and this
service sits on the free plan. If the migration fails the boot aborts, so Render
keeps the previous instance serving instead of swapping onto a half-migrated
schema. Alembic is idempotent, so where both run the second reports "already up
to date".

`gunicorn` serves `wsgi:app`. `wsgi.py` wraps the app in `ProxyFix` so that
`X-Forwarded-Proto` is trusted, which is what makes secure cookies and HSTS work
behind Render's TLS terminator. Never run gunicorn on Windows; it is Linux-only.

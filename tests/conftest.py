import os
import pathlib
import re
import shutil
import subprocess

import pytest
from flask_migrate import upgrade
from sqlalchemy.orm import Session as SqlAlchemySession
from werkzeug.security import generate_password_hash

os.environ.setdefault("APP_ENV", "testing")

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models import Category, StudySession, User  # noqa: E402

TABLES = ("sessions", "categories", "users")
TEST_PASSWORD = "correct horse battery staple"

CSRF_META = re.compile(r'name="csrf-token" content="([^"]+)"')
CSRF_FIELD = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')

STATIC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "static"


@pytest.fixture
def static_source():
    """Reads a file from ``static/``.

    For assertions that have to pin behaviour to the stylesheet or a script,
    because a rendered template says nothing about the CSS or JavaScript that
    is supposed to go with it.
    """
    def _read(name):
        return (STATIC_ROOT / name).read_text(encoding="utf-8")

    return _read


@pytest.fixture(scope="session")
def js_harness():
    """Runs ``tests/js/timer_harness.js`` and returns its output.

    The harness loads the real ``static/timer.js`` against a stub DOM and a
    fake clock, so timer behaviour is asserted rather than inferred from the
    presence of a selector in the markup - a button with no handler passes
    every template check. Skipped, not failed, when node is absent: the suite's
    contract is the Flask application, and a missing toolchain for one optional
    front-end check should not hold the rest of it hostage. When node is there
    the harness has to be green.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, str(pathlib.Path(__file__).parent / "js" / "timer_harness.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, "timer harness failed:\n" + output
    return output


@pytest.fixture(scope="session")
def app():
    application = create_app("testing")
    with application.app_context():
        upgrade()
    return application


@pytest.fixture
def app_ctx(app):
    """An application context for tests that call code in-process.

    `db.session` is scoped to the application context, so a test that calls
    something like `stats.summary(user.id)` directly, rather than through a
    request, needs one.

    Opt-in rather than autouse, deliberately. Holding a context open for the
    whole test stops a request made through the test client from getting a
    CSRF token into its own session: the token lands in this outer session,
    which the response never writes back. Every later POST then fails
    validation with "The CSRF session token is missing" and a 400, which is
    what made the ownership and timer-flow tests fail before this was split.
    Only use it in tests that make no requests.
    """
    with app.app_context():
        yield


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(scope="session", autouse=True)
def clear_stale_backends(app):
    """Drop connections left behind by an earlier run that was killed.

    A terminated pytest process can leave a backend `idle in transaction`
    holding locks on the tables, and the first `TRUNCATE` of this run then
    waits forever on them. That is a hazard of a shared, network-attached
    throwaway database rather than of the code under test, so clear it once
    before any test runs.

    Only ever run against the database named by `TEST_DATABASE_URL`, which
    `config.py` refuses to build without, and which the suite treats as
    disposable.
    """
    with app.app_context():
        connection = db.engines[None].connect()
        try:
            connection.execute(
                db.text(
                    "select pg_terminate_backend(pid) from pg_stat_activity "
                    "where datname = current_database() "
                    "and pid <> pg_backend_pid()"
                )
            )
        finally:
            connection.close()


@pytest.fixture(autouse=True)
def db_session(app):
    """One connection, one transaction, shared by the fixture and the app.

    Autouse, so every test is isolated whether or not it asks for this fixture.

    How the sharing works matters. Flask-SQLAlchemy's `Session.get_bind()`
    resolves the bind by looking it up in `db.engines` for the *current
    application*, and `db.engine` is just `db.engines[None]`. `db.engines`
    returns the mutable per-app dict, so replacing the `None` entry for the
    duration of the test is what actually routes every session — the fixture's,
    and the one the test client builds for each request — to the same
    connection. Fixture rows are therefore visible to requests.

    `db.session.configure(bind=connection)` does NOT do this. The
    `sessionmaker`'s bind is ignored because `get_bind()` overrides it, so
    requests silently go to a different connection from the pool; that was the
    cause of the original hang, where a request's `SELECT` blocked on the
    `ACCESS EXCLUSIVE` lock the fixture's `TRUNCATE` was holding.

    Isolation is two things, both on this one connection:
      * the tables are truncated on entry, so a test starts from empty;
      * the transaction is rolled back on exit, undoing the truncate and
        everything the test wrote.

    No application context is held while the test body runs. That is not a
    style preference: with an outer context pushed, a request through the test
    client can no longer get a CSRF token into its own session, so every POST
    after logging in fails with "The CSRF session token is missing" and a 400.
    Because of that, tests that query the database use the `db_session` handle
    this fixture yields rather than `db.session`, which needs a context.

    Sessions opened against a connection that already has a transaction of its
    own use a SAVEPOINT rather than committing it, so a view that calls
    `db.session.commit()` does not commit the outer transaction and its rows
    stay visible to the fixture afterwards.

    Caveat: `db.session.rollback()` is not savepoint-local here. Verified on
    this database: a view that rolls back also discards rows the fixture had
    already flushed, because the fixture's Session began the transaction
    rather than a savepoint of its own. The duplicate-category paths in
    `categories.py` roll back, so a test that needs to reach those paths must
    create its own rows inside the test body, not via another fixture.
    """
    with app.app_context():
        engine = db.engines[None]
        connection = engine.connect()
        transaction = connection.begin()
        db.engines[None] = connection
        session = SqlAlchemySession(bind=connection)
        # Same connection as every request, so this cannot block on a lock
        # held by another session.
        try:
            session.execute(
                db.text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
            )
        except BaseException:
            transaction.rollback()
            connection.close()
            db.engines[None] = engine
            raise

    try:
        yield session
    finally:
        with app.app_context():
            db.session.remove()
            db.engines[None] = engine
            session.close()
            transaction.rollback()
            connection.close()


@pytest.fixture(autouse=True)
def reset_limiter(app):
    """Keep the real limiters active but start every test with a clean
    counter, so one test exhausting a limit cannot fail the next.

    Flask-Limiter registers itself in `app.extensions["limiter"]` as a set
    holding the Limiter, so the extension is unwrapped before use.
    """
    limiter = next(iter(app.extensions["limiter"]))
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def csrf(client):
    """Read the CSRF token the way a browser would.

    Pages expose it in the <meta> tag that app.js and timer.js read; forms
    also carry a hidden field. Prefer the meta tag so this works on any page,
    including ones with no form at all.
    """

    def _token(path="/login"):
        html = client.get(path).get_data(as_text=True)
        match = CSRF_META.search(html) or CSRF_FIELD.search(html)
        assert match is not None, f"no CSRF token rendered on {path}"
        return match.group(1)

    return _token


@pytest.fixture
def post_json(client, csrf):
    """POST JSON with the CSRF header the front end sends."""

    def _post(url, payload, path="/login"):
        return client.post(
            url,
            json=payload,
            headers={"X-CSRFToken": csrf(path)},
        )

    return _post


@pytest.fixture
def user(db_session):
    row = User(username="gabriel", password_hash=generate_password_hash(TEST_PASSWORD))
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def category(db_session, user):
    row = Category(user_id=user.id, category_name="Maths")
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def study_session(db_session, user, category):
    row = StudySession(
        user_id=user.id, category_id=category.id, duration=125, description="notes"
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def other_user(db_session):
    row = User(
        username="mallory", password_hash=generate_password_hash("hunter2hunter2")
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def other_category(db_session, other_user):
    row = Category(user_id=other_user.id, category_name="Chemistry")
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def login(client, user, csrf):
    def _login(username="gabriel", password=TEST_PASSWORD, follow=True):
        return client.post(
            "/login",
            data={
                "username": username,
                "password": password,
                "csrf_token": csrf("/login"),
            },
            follow_redirects=follow,
        )

    return _login

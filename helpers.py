from functools import wraps

from flask import redirect, session
from sqlalchemy import select

from extensions import db


def login_required(f):
    """Require an authenticated user before running the view."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function


def current_user_id() -> int:
    return session["user_id"]


# Widest value a 32-bit integer column holds. Anything larger would be a 500
# from the driver, so it is refused here as a 404 like any other unusable id.
MAX_ID = 2**31 - 1


def read_id(raw):
    """Parse a client-supplied id into the exact form the queries need.

    Returns None for anything that is not a plain positive integer that fits an
    integer column, so a junk value is answered with a 404 instead of reaching
    the driver as a 500.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        text = raw.strip()
        try:
            value = int(text)
        except (TypeError, ValueError):
            return None
        # Reject anything int() was lenient about ("1_0", "+7", "07") so the
        # value that is checked is the value that is used.
        if str(value) != text:
            return None
    else:
        return None
    return value if 0 < value <= MAX_ID else None


def load_owned(model, row_id, user_id):
    """Fetch a row by id under one ownership rule, applied in one place.

    AGENTS.md rule 1: an id that does not exist is a 404; an id that exists but
    belongs to another account is a 403. Returning a distinct code for each
    means the caller has to know whether the row exists at all, so the check is
    centralised here rather than reimplemented per route.

    `row_id` is whatever the client sent. Only the *parsed* integer is used in
    the queries: binding the raw string would make SQLAlchemy infer a VARCHAR
    bind and PostgreSQL would refuse `integer = character varying`.

    Returns (row, None) on success, or (None, code) with code 404 or 403.
    """
    pk = read_id(row_id)
    if pk is None:
        return None, 404
    if db.session.get(model, pk) is None:
        return None, 404
    row = db.session.scalar(
        select(model).where(model.id == pk, model.user_id == user_id)
    )
    if row is None:
        return None, 403
    return row, None

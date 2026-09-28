from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
)
from secrets import token_urlsafe
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from extensions import db
from helpers import current_user_id, load_owned, login_required, read_id
from models import Category, StudySession
from stats import (
    DAYS_IN_SERIES,
    category_breakdown,
    daily_series,
    recent,
    summary,
)

timer_bp = Blueprint("timer", __name__)

MAX_SESSION_SECONDS = 24 * 60 * 60
MAX_DESCRIPTION_LENGTH = 5000


def _read_duration(payload: dict) -> int | None:
    raw = payload.get("duration")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    if raw != raw or raw in (float("inf"), float("-inf")):
        return None
    # The timer sends whole seconds, so anything fractional is a hand-crafted
    # payload. Reject it rather than quietly accepting 1.9 seconds as 1.
    if isinstance(raw, float) and not raw.is_integer():
        return None
    value = int(raw)
    if value <= 0 or value > MAX_SESSION_SECONDS:
        return None
    return value


@timer_bp.route("/")
@login_required
def index():
    user_id = current_user_id()

    categories = list(
        db.session.scalars(
            select(Category)
            .where(Category.user_id == user_id)
            .order_by(Category.category_name)
        )
    )

    subjects, subject_count = category_breakdown(user_id)

    return render_template(
        "index.html",
        categories=categories,
        stats=summary(user_id),
        series=daily_series(user_id),
        subjects=subjects,
        subject_count=subject_count,
        recent_sessions=recent(user_id, limit=4),
    )


@timer_bp.route("/history", methods=["GET"])
@login_required
def history():
    user_id = current_user_id()

    rows = list(
        db.session.scalars(
            select(StudySession)
            .options(joinedload(StudySession.category))
            .where(StudySession.user_id == user_id)
            .order_by(StudySession.created_at.desc(), StudySession.id.desc())
        )
    )

    subjects, subject_count = category_breakdown(user_id, limit=6)

    return render_template(
        "history.html",
        subjects_rows=rows,
        stats=summary(user_id),
        series=daily_series(user_id, days=DAYS_IN_SERIES),
        breakdown=subjects,
        breakdown_count=subject_count,
    )


@timer_bp.route("/delete-session", methods=["POST"])
@login_required
def delete_session():
    row, code = load_owned(
        StudySession, request.form.get("id"), current_user_id()
    )

    if code is not None:
        # abort() so the registered error page renders, rather than handing
        # back an empty body with the right status.
        abort(code)

    db.session.delete(row)
    db.session.commit()
    return redirect("/history")


@timer_bp.route("/select-category", methods=["POST"])
@login_required
def select_category():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(success=False), 400

    # A junk id is a 404 and someone else's is a 403. Answering 400 here made
    # this the one route that treated the same input differently, which is the
    # drift rule 1 exists to stop, so read_id/load_owned answer it like
    # everywhere else. A JSON endpoint, so JSON rather than the HTML page.
    row, code = load_owned(
        Category, payload.get("category_id"), current_user_id()
    )
    if code is not None:
        return jsonify(success=False), code

    session["selected_category"] = row.id
    return jsonify(success=True)


@timer_bp.route("/finish", methods=["GET", "POST"])
@login_required
def finish():
    if request.method == "POST":
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(success=False), 400

        # The duration is read first, so a malformed body is answered as one
        # before any id is interpreted: 400 means the request was wrong, 404
        # means the row it named is not there, and a body that is wrong in both
        # ways should not be told about the second problem.
        duration = _read_duration(payload)
        if duration is None:
            return jsonify(success=False), 400

        # The subject travels with the duration. It used to be read back out of
        # the session, which relied on POST /select-category having happened
        # first; that fires on the dropdown's change event, which a browser
        # does not raise when it restores a select's value on load. The session
        # then had a subject the server had never been told about and the save
        # died with "Start a session before finishing one".
        #
        # It comes from the body only, never from the session: falling back to
        # `session["selected_category"]` would book the session to whatever
        # subject the server last heard about when the client sent no id, which
        # is silent wrong data rather than a visible failure.
        #
        # A junk id is a 404 and someone else's is a 403, as everywhere else.
        category, code = load_owned(
            Category, payload.get("category_id"), current_user_id()
        )
        if code is not None:
            return jsonify(success=False), code

        session["selected_category"] = category.id
        session["finish_duration"] = duration
        return jsonify(success=True)

    duration = session.pop("finish_duration", None)
    category_id = session.pop("selected_category", None)

    if duration is None or category_id is None:
        flash("Start a session before finishing one")
        return redirect("/")

    # The id came from this user's own session, set by /select-category, which
    # already checked ownership. The lookup is repeated through load_owned so
    # there is one implementation of the rule, but a failure here is answered
    # in the flow's own voice rather than an error page: the user is mid-save,
    # and the useful message is that there is nothing to save.
    category, code = load_owned(Category, category_id, current_user_id())

    if code is not None:
        flash("Start a session before finishing one")
        return redirect("/")

    hours, remainder = divmod(duration, 3600)
    minutes, seconds = divmod(remainder, 60)
    final_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    # The pending session is moved behind a single-use token so that revisiting
    # /finish, or walking back into it from history, cannot offer a session
    # that was already abandoned.
    token = token_urlsafe(16)
    session["pending_token"] = token
    session["pending_session"] = {"duration": duration, "category_id": category.id}

    return render_template(
        "finish.html", final_time=final_time, subject=category, token=token
    )


@timer_bp.route("/desc", methods=["GET", "POST"])
@login_required
def desc():
    if request.method == "GET":
        return redirect("/")

    # Consume the token before doing any work, so a double submit cannot
    # insert the same session twice.
    if not session.pop("pending_token", None) == request.form.get("token"):
        session.pop("pending_session", None)
        flash("Start a session before saving one")
        return redirect("/")

    pending = session.pop("pending_session", None)

    if not isinstance(pending, dict):
        flash("Start a session before saving one")
        return redirect("/")

    # Both values came from this session, set by POST /finish and
    # /select-category, so they are already the parsed integers those routes
    # validated. They are re-checked here anyway: the session is the only thing
    # standing between a stale cookie and a row in the database.
    duration = read_id(pending.get("duration"))
    category_id = read_id(pending.get("category_id"))

    if (
        duration is None
        or category_id is None
        or duration <= 0
        or duration > MAX_SESSION_SECONDS
    ):
        flash("Start a session before saving one")
        return redirect("/")

    category, code = load_owned(Category, category_id, current_user_id())

    if code is not None:
        flash("Start a session before saving one")
        return redirect("/")

    text = (request.form.get("description") or "").strip()
    if len(text) > MAX_DESCRIPTION_LENGTH:
        flash("That description is too long")
        return redirect("/")

    db.session.add(
        StudySession(
            user_id=current_user_id(),
            category_id=category.id,
            duration=duration,
            description=text or None,
        )
    )
    db.session.commit()

    current_app.logger.info(
        "saved study session", extra={"user_id": current_user_id(), "seconds": duration}
    )
    return redirect("/")


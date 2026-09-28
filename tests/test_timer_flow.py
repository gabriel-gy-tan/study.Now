import re

from sqlalchemy import select

from helpers import read_id
from models import Category, StudySession


def test_finish_saves_with_a_subject_the_server_was_never_told_about(
    client, csrf, post_json, login, user, category, db_session
):
    """The subject travels with the duration, not in a side-effect request.

    POST /select-category only fires on the dropdown's `change` event, which a
    browser does not raise when it restores the select's value on load. The
    session then had a subject the server had never heard of, and finishing
    answered "Start a session before finishing one" instead of saving.
    """
    login()
    # Deliberately no /select-category first: nothing has told the server which
    # subject this is yet.
    assert post_json(
        "/finish", {"duration": 90, "category_id": category.id}, path="/"
    ).status_code == 200

    finish_page = client.get("/finish")
    assert finish_page.status_code == 200
    assert "00:01:30" in finish_page.get_data(as_text=True)

    token = _pending_token(client, csrf, category, duration=90)
    response = client.post(
        "/desc",
        data={"description": "late", "token": token, "csrf_token": csrf("/")},
        follow_redirects=True,
    )
    assert response.status_code == 200

    saved = db_session.scalars(select(StudySession)).all()
    assert len(saved) == 1
    assert saved[0].duration == 90
    assert saved[0].category_id == category.id


def test_finish_refuses_a_subject_that_is_not_the_callers(
    client, post_json, login, user, other_category
):
    """The id in the body goes through the same ownership rule as every other
    route: 403 for someone else's, not a silent save against the wrong row."""
    login()
    assert post_json(
        "/finish", {"duration": 60, "category_id": other_category.id}, path="/"
    ).status_code == 403
    assert post_json(
        "/finish", {"duration": 60, "category_id": 999_999}, path="/"
    ).status_code == 404


def test_the_timer_can_be_made_full_screen(client, login, js_harness, static_source):
    """A full-screen toggle, so the clock can have the screen to itself.

    The template half only says the control is there. The behaviour comes from
    the harness, which loads the real timer.js, clicks the button, and checks
    that the class, the pressed state, the label, native fullscreen and Escape
    all move together - and that a refused fullscreen API leaves the page
    consistent. The markers below are read off the harness output, so pruning
    those checks turns this into a real failure instead of quietly reducing it
    to a markup assertion.
    """
    login()
    html = client.get("/").get_data(as_text=True)
    assert 'data-timer-fullscreen' in html
    assert 'data-timer-fullscreen-label' in html
    assert 'aria-pressed="false"' in html

    for marker in (
        "the toggle starts unpressed",
        "entering turns the focus view on",
        "native fullscreen follows the class",
        "Escape still leaves the focus view",
        "a native exit takes the focus view with it",
        "another element's fullscreen does not start the focus view",
        "a refused exit still leaves focus mode",
        "no fullscreen refusal escaped as an unhandled rejection",
    ):
        assert marker in js_harness, marker

    styles = static_source("styles.css")
    # Having the screen to itself is a property of the stylesheet, not of the
    # markup: the button only adds a class. Each rule below is one the feature
    # cannot work without, and each names the thing it exists to remove.
    for rule, what in (
        (".is-focusmode .topbar,", "the navigation bar"),
        (".is-focusmode .page-head,", "the page heading above the timer"),
        (
            ":not(.timer-card)",
            "the cards stacked above and below the timer, which are its "
            "siblings and carry no class of their own",
        ),
        (
            ".is-focusmode .grid--split {",
            "the second grid track, which hiding the aside does not remove "
            "and which would leave the clock pinned to a left-hand column",
        ),
        (
            ".is-focusmode .shell {",
            "the shell's max-width and side padding, which are what leave the "
            "clock marooned rather than centred",
        ),
        (".is-focusmode .timer-card", "the card"),
        (".is-focusmode .timer-readout", "the enlarged clock"),
    ):
        assert rule in styles, f"focus mode never hides or reshapes {what}"

    # The toggle sits beside the status pill rather than inside it, so its
    # label changes are not announced as a change of timer state.
    assert 'class="timer-statebar"' in html
    pill = re.search(r'<p class="timer-state".*?</p>', html, re.DOTALL)
    assert pill, "no status pill rendered"
    assert "data-timer-fullscreen" not in pill.group(0)


def test_finish_page_redirects_when_no_session_is_pending(client, login, user):
    login()
    response = client.get("/finish")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_a_finish_with_no_subject_is_refused_rather_than_staged(
    client, post_json, login, user
):
    """The subject travels with the duration, so a body without one has nothing
    to stage. Refused outright rather than leaving a half-formed run behind for
    the finish page to offer for description."""
    login()
    assert post_json("/finish", {"duration": 120}, path="/").status_code == 404
    assert client.get("/finish").status_code == 302


def test_finish_never_reads_the_subject_out_of_the_session(
    client, post_json, login, user, category
):
    """The body is the only source, even when the session already knows.

    /select-category leaves a subject in the session, which is precisely the
    state the original bug produced: a subject the server last heard about
    rather than one this request vouched for. A finish with no category_id
    must still be refused instead of being answered from that stale value.
    """
    login()
    assert post_json(
        "/select-category", {"category_id": category.id}, path="/"
    ).status_code == 200

    assert post_json("/finish", {"duration": 45}, path="/").status_code == 404
    assert client.get("/finish").status_code == 302


def test_a_bad_duration_is_answered_before_the_subject_is_looked_up(
    client, post_json, login, user
):
    """400 for a request that is malformed; 404 for a row that is not there.

    Both are wrong here and the duration is the more fundamental of the two, so
    it is checked first. With the order reversed, a misspelt duration alongside
    a subject id the caller never meant to send would come back as 404 and
    bury the real problem.
    """
    login()
    assert post_json("/finish", {"duration": "abc"}, path="/").status_code == 400
    assert (
        post_json(
            "/finish", {"duration": 0, "category_id": 999_999}, path="/"
        ).status_code
        == 400
    )


def test_desc_redirects_when_nothing_is_pending(client, csrf, login, user, db_session):
    login()
    response = client.post(
        "/desc",
        data={"description": "notes", "csrf_token": csrf("/")},
    )
    assert response.status_code == 302
    assert db_session.scalars(select(StudySession)).all() == []


def test_desc_get_never_crashes(client, login, user):
    login()
    response = client.get("/desc")
    assert response.status_code == 302


def _pending_token(client, csrf, category, duration=3725):
    """Drive the flow up to a rendered /finish page and return its token.

    The subject is repeated in the finish body, which is what static/timer.js
    sends. /select-category is still called first because the real client calls
    it on the change event, but /finish does not depend on it having landed.
    """
    client.post(
        "/select-category",
        json={"category_id": category.id},
        headers={"X-CSRFToken": csrf("/")},
    )
    client.post(
        "/finish",
        json={"duration": duration, "category_id": category.id},
        headers={"X-CSRFToken": csrf("/")},
    )
    page = client.get("/finish")
    match = re.search(r'name="token" type="hidden" value="([^"]+)"', page.get_data(as_text=True))
    assert match, "the finish page must carry a single-use token"
    return match.group(1)


def test_happy_path_records_a_session(client, post_json, csrf, login, user, category, db_session):
    login()

    assert post_json(
        "/select-category", {"category_id": category.id}, path="/"
    ).status_code == 200
    assert post_json(
        "/finish", {"duration": 3725, "category_id": category.id}, path="/"
    ).status_code == 200

    finish_page = client.get("/finish")
    assert finish_page.status_code == 200
    assert "01:02:05" in finish_page.get_data(as_text=True)

    token = _pending_token(client, csrf, category)
    response = client.post(
        "/desc",
        data={
            "description": "integrals",
            "token": token,
            "csrf_token": csrf("/"),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    saved = db_session.scalars(select(StudySession)).all()
    assert len(saved) == 1
    assert saved[0].duration == 3725
    assert saved[0].description == "integrals"
    assert saved[0].user_id == user.id
    assert saved[0].category_id == category.id


def test_a_pending_session_cannot_be_saved_twice(client, csrf, login, user, category, db_session):
    """The finish page is single-use, so a double submit or a back-button
    press must not write the same session twice."""
    login()
    token = _pending_token(client, csrf, category, duration=600)

    first = client.post(
        "/desc",
        data={"description": "", "token": token, "csrf_token": csrf("/")},
        follow_redirects=True,
    )
    assert first.status_code == 200
    assert len(db_session.scalars(select(StudySession)).all()) == 1

    second = client.post(
        "/desc",
        data={"description": "again", "token": token, "csrf_token": csrf("/")},
        follow_redirects=True,
    )
    assert second.status_code == 200
    assert len(db_session.scalars(select(StudySession)).all()) == 1


def test_finish_page_is_not_offered_twice(client, csrf, login, user, category, db_session):
    """Abandoning the page and coming back must not resurrect the old
    session, which would otherwise let time be invented."""
    login()
    _pending_token(client, csrf, category, duration=1500)

    again = client.get("/finish")
    assert again.status_code == 302
    assert db_session.scalars(select(StudySession)).all() == []


def test_history_renders_the_saved_session(client, login, user, category, db_session):
    db_session.add(
        StudySession(
            user_id=user.id,
            category_id=category.id,
            duration=3725,
            description="integrals",
        )
    )
    db_session.commit()

    login()
    html = client.get("/history").get_data(as_text=True)

    assert "01:02:05" in html
    assert "integrals" in html
    assert "Maths" in html


def test_saving_clears_the_pending_session_state(
    client, csrf, login, user, category
):
    login()
    token = _pending_token(client, csrf, category, duration=60)
    client.post(
        "/desc",
        data={"description": "done", "token": token, "csrf_token": csrf("/")},
        follow_redirects=True,
    )

    with client.session_transaction() as session:
        assert "pending_token" not in session
        assert "pending_session" not in session
        assert "finish_duration" not in session
        assert "selected_category" not in session

    assert client.get("/finish").status_code == 302


def test_a_description_is_optional(client, post_json, csrf, login, user, category, db_session):
    login()
    token = _pending_token(client, csrf, category, duration=60)
    client.post(
        "/desc",
        data={"token": token, "csrf_token": csrf("/")},
        follow_redirects=True,
    )

    saved = db_session.scalars(select(StudySession)).one()
    assert saved.description is None


def test_select_category_rejects_a_body_that_is_not_an_object(
    client, post_json, login, user
):
    """A body that is not a JSON object is a malformed request. An object that
    merely lacks a usable id is the same 'no such row' answer every other route
    gives, so that case is covered below rather than treated as a 400."""
    login()
    assert post_json("/select-category", [], path="/").status_code == 400


def test_select_category_separates_a_missing_id_from_a_foreign_one(
    client, post_json, login, user, category, other_category
):
    """A missing row is a 404; a row owned by someone else is a 403.

    The junk id is a 404, not a 400, because /delete-session and /goupdate
    already answer 404 for the same input through load_owned, and rule 1 is
    one policy across routes rather than one route's opinion of a value.
    """
    login()

    assert post_json(
        "/select-category", {"category_id": category.id + 9999}, path="/"
    ).status_code == 404
    assert post_json("/select-category", {"category_id": "abc"}, path="/").status_code == 404
    assert post_json("/select-category", {}, path="/").status_code == 404
    assert post_json(
        "/select-category", {"category_id": other_category.id}, path="/"
    ).status_code == 403


def test_a_non_numeric_id_does_not_become_a_server_error(client, csrf, login, user):
    """A junk id must read as 'no such row' instead of reaching the
    database and coming back as a 500."""
    login()

    for path in ("/delete-session", "/delete-category"):
        response = client.post(
            path, data={"id": "abc", "csrf_token": csrf("/")}, follow_redirects=True
        )
        assert response.status_code == 404, path

    assert client.get("/goupdate?id=abc").status_code == 404


def test_read_id_only_returns_a_usable_integer():
    """Ids are parsed once, and the parsed value is what the queries bind.

    Binding the raw client string instead would make SQLAlchemy infer a VARCHAR
    bind, and PostgreSQL answers `integer = character varying` with a 500.
    So anything that is not already the plain integer a query can use is
    refused here, including the forms int() is lenient about and values too
    large for the column.
    """
    for good in (7, "7", " 7 "):
        assert read_id(good) == 7, good

    for bad in (
        "+7", "07", "1_0", "abc", "", "   ", None, True, False, -1, 0,
        3.5, b"7", [], {}, 2**31, "9999999999",
    ):
        assert read_id(bad) is None, bad


def test_every_owned_route_separates_a_missing_id_from_a_foreign_one(
    client, csrf, post_json, login, db_session, other_user, other_category
):
    """AGENTS.md rule 1: 404 for an id that does not exist, 403 for one that
    exists but belongs to another account, applied the same way everywhere.
    A route that answered 404 for both would hide which of the two mistakes the
    caller made, and would drift from its neighbours."""
    login()
    missing = 999_999

    foreign = StudySession(
        user_id=other_user.id, category_id=other_category.id, duration=60
    )
    db_session.add(foreign)
    db_session.commit()
    foreign_session_id = foreign.id

    for path, row_id, expected in (
        ("/delete-session", missing, 404),
        ("/delete-session", foreign_session_id, 403),
        ("/delete-category", missing, 404),
        ("/delete-category", other_category.id, 403),
    ):
        response = client.post(
            path,
            data={"id": row_id, "csrf_token": csrf("/")},
            follow_redirects=True,
        )
        assert response.status_code == expected, (path, row_id, expected)

    assert client.get(f"/goupdate?id={missing}").status_code == 404
    assert client.get(f"/goupdate?id={other_category.id}").status_code == 403

    for row_id, expected in ((missing, 404), (other_category.id, 403)):
        response = client.post(
            "/goupdate",
            data={"id": row_id, "update": "x", "csrf_token": csrf("/categories")},
            follow_redirects=True,
        )
        assert response.status_code == expected, (row_id, expected)

    for row_id, expected in ((missing, 404), (other_category.id, 403)):
        response = post_json(
            "/select-category", {"category_id": row_id}, path="/"
        )
        assert response.status_code == expected, (row_id, expected)

    # Nothing was deleted or renamed along the way.
    assert db_session.get(StudySession, foreign_session_id) is not None
    assert db_session.get(Category, other_category.id).category_name == "Chemistry"


def test_finish_rejects_a_non_numeric_duration(
    client, post_json, login, user, category
):
    # A valid subject is sent alongside, so the only thing left to answer the
    # request is the duration itself.
    login()
    assert (
        post_json(
            "/finish",
            {"duration": "abc", "category_id": category.id},
            path="/",
        ).status_code
        == 400
    )
    assert post_json("/finish", {"category_id": category.id}, path="/").status_code == 400
    assert (
        post_json(
            "/finish",
            {"duration": True, "category_id": category.id},
            path="/",
        ).status_code
        == 400
    )


def test_finish_rejects_impossible_durations(
    client, post_json, login, user, category
):
    login()
    for bad in (0, -30, 10**12, float("inf"), float("nan")):
        response = post_json(
            "/finish", {"duration": bad, "category_id": category.id}, path="/"
        )
        assert response.status_code == 400, bad


def test_json_endpoints_reject_a_missing_csrf_header(client, login, user):
    login()
    response = client.post("/finish", json={"duration": 60})
    assert response.status_code == 400

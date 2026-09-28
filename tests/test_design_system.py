"""Guards on the design system.

These are not pixel tests. They stop the front end quietly drifting back to a
framework look, to placeholder-only forms, or to unlabelled controls.
"""

import pathlib
import re
from datetime import datetime, timedelta

from app import human_duration
from models import StudySession

PUBLIC_PAGES = ["/login", "/register"]


def test_stylesheet_is_the_only_stylesheet(client):
    html = client.get("/login").get_data(as_text=True)
    assert "styles.css" in html
    assert "bootstrap" not in html.lower()


def test_the_favicon_points_at_a_file_that_exists(client):
    """A missing icon is a 404 on every page the browser opens."""
    html = client.get("/login").get_data(as_text=True)
    match = re.search(r'<link href="(/static/[^"]+)" rel="icon"', html)
    assert match, "no icon link rendered"
    icon = match.group(1)
    assert client.get(icon).status_code == 200, icon


def test_every_page_carries_the_csrf_meta_tag(client):
    for path in PUBLIC_PAGES:
        html = client.get(path).get_data(as_text=True)
        assert 'name="csrf-token"' in html, path


def test_navigation_marks_the_current_page(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'aria-current="page"' in html


def test_login_inputs_have_real_labels(client):
    html = client.get("/login").get_data(as_text=True)
    assert '<label class="field__label" for="username">' in html
    assert '<label class="field__label" for="password">' in html


def test_register_confirms_password_with_a_label(client):
    html = client.get("/register").get_data(as_text=True)
    assert 'for="confirmation"' in html


def test_nav_toggle_is_collapsed_by_default(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'aria-expanded="false"' in html
    assert 'data-open="false"' in html


def test_skip_link_is_first_in_the_body(client, static_source):
    html = client.get("/login").get_data(as_text=True)
    # The tag carries attributes and may be spelled in any case, so find the
    # element rather than splitting on a literal string.
    match = re.search(r"<body\b[^>]*>", html, re.IGNORECASE)
    assert match is not None, "no <body> element found"
    body = html[match.end() :]
    assert body.lstrip().startswith('<a class="skip-link" href="#main">')
    # Being first is not enough: it has to be reachable by Tab and then
    # actually visible, or a sighted keyboard user tabbing past the nav is
    # sent somewhere they cannot see.
    styles = static_source("styles.css")
    assert ".skip-link:focus" in styles
    assert "transform: none" in styles


def test_shared_script_is_loaded(client):
    html = client.get("/login").get_data(as_text=True)
    assert "/static/app.js" in html


def test_no_inline_style_attributes_for_presentation(client):
    """A raw style attribute is how the design system starts drifting.

    Two kinds are legitimate because a stylesheet cannot know the value: a
    custom property set from a template (`--bar: 40%`, `--dot: var(--dot-1)`)
    and a data-driven dimension (`width: 33%`). The allowlist is deliberately
    narrow, because a second brand colour is exactly the drift AGENTS.md
    forbids.
    """

    templates = pathlib.Path(__file__).resolve().parents[1] / "templates"
    # Scan the whole file rather than line by line, or a value broken across
    # lines slips through, and match case-insensitively as HTML does.
    attribute = re.compile(
        r"""style\s*=\s*(?P<q>["'])(?P<body>.*?)(?P=q)""",
        re.DOTALL | re.IGNORECASE,
    )
    allowed = re.compile(
        r"^\s*(?:--bar|--dot|--chart|width|height)\s*:[^;]*;?\s*$",
        re.IGNORECASE,
    )

    checked = 0
    for path in sorted(templates.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for match in attribute.finditer(text):
            checked += 1
            body = match.group("body")
            assert allowed.match(body), (
                f"{path.name}: inline style not allowed: {body.strip()!r}"
            )

    # A guard that finds nothing is not a guard.
    assert checked >= 4, f"expected real inline styles, matched only {checked}"


def test_timer_locks_the_subject_while_a_session_runs(client, login):
    """`elapsed` is the accumulated base and stays 0 while running, so the
    lock has to test `running` as well or the subject stays editable."""

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "static" / "timer.js"
    ).read_text(encoding="utf-8")

    assert "function isLocked()" in source
    assert "return running || elapsed > 0;" in source
    # The change handler must consult the lock, not the raw base.
    handler = source.split("addEventListener(\"change\"", 1)[1].split("});", 1)[0]
    assert "isLocked()" in handler
    # A locked select must be put back rather than silently re-attributed.
    assert "categorySelect.value = confirmedCategory" in handler


def test_timer_clamps_a_session_that_exceeds_the_server_limit(client, login):
    """The server caps a session at 24 hours and answers 400; the client must
    stop it before the request, or the user is stuck with a session that can
    never be saved."""

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "static" / "timer.js"
    ).read_text(encoding="utf-8")
    assert "MAX_SECONDS = 24 * 60 * 60" in source
    assert "seconds > MAX_SECONDS" in source


def test_timer_persists_per_user_not_globally(client, login):
    """A shared browser must not hand one account another's unsaved session."""

    login()
    html = client.get("/").get_data(as_text=True)
    assert "data-user-id=" in html

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "static" / "timer.js"
    ).read_text(encoding="utf-8")
    assert 'card.getAttribute("data-user-id")' in source
    assert "studynow.timer." in source


def test_timer_never_saves_a_finished_session(client, login):
    """beforeunload fires on the redirect to /finish, and an unguarded write
    would restore the session and let it be saved a second time."""

    source = (
        pathlib.Path(__file__).resolve().parents[1] / "static" / "timer.js"
    ).read_text(encoding="utf-8")

    save_body = source.split("function save()", 1)[1].split("function clearSaved()", 1)[0]
    assert "if (finished)" in save_body

    # Guarding the read is only half the fix: the flag must also actually be
    # set, and it must be set before the navigation that triggers the save.
    handler = source.split("controls.finish.addEventListener", 1)[1]
    assert "finished = true" in handler
    assert handler.index("finished = true") < handler.index("location.href")


def test_timer_announces_time_to_screen_readers(client, login):
    login()
    html = client.get("/").get_data(as_text=True)
    assert 'aria-live="polite"' in html
    assert "data-timer-readout-live" in html
    # The visible readout must not itself be a live region, or every tick
    # would be announced.
    assert 'aria-hidden="true" data-timer-readout' in html


def test_history_delete_buttons_have_distinct_names(
    client, login, user, category, db_session
):
    """Identical "Delete session" labels give a screen reader no way to tell
    the buttons apart. The label has to carry the subject *and* the time, so
    the timestamps are set explicitly here: two sessions recorded back to back
    can otherwise share a label purely by accident of the clock."""
    login()

    first = datetime(2024, 5, 4, 9, 15, 30)
    for offset in (0, 90):
        db_session.add(
            StudySession(
                user_id=user.id,
                category_id=category.id,
                duration=600,
                description="",
                created_at=first + timedelta(seconds=offset),
            )
        )
    db_session.commit()

    html = client.get("/history").get_data(as_text=True)
    labels = re.findall(r'aria-label="(Delete session:[^"]+)"', html)

    assert len(labels) == 2, f"expected two labelled delete buttons, got {labels}"
    assert len(set(labels)) == 2, f"delete buttons share a label: {labels}"
    assert all("Maths" in label for label in labels), labels
    # /history is newest first, so the later timestamp comes first.
    assert "09:17:00" in labels[0] and "09:15:30" in labels[1], labels
    assert 'aria-label="Delete session"' not in html


def test_security_headers_include_a_content_security_policy(client):
    policy = client.get("/login").headers["Content-Security-Policy"]
    assert "default-src 'self'" in policy
    assert "script-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy


def test_human_duration_is_compact():
    assert human_duration(0) == "0m"
    assert human_duration(45) == "45s"
    assert human_duration(90) == "1m"
    assert human_duration(3600) == "1h"
    assert human_duration(3725) == "1h 2m"
    assert human_duration(7325) == "2h 2m"
    assert human_duration(-5) == "0m"
    assert human_duration(None) == "0m"

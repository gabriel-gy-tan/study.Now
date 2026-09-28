import re

from sqlalchemy import select

from models import Category, StudySession


def test_cannot_delete_another_users_session(
    client, csrf, login, study_session, other_user, other_category, db_session):
    foreign = StudySession(
        user_id=other_user.id, category_id=other_category.id, duration=60
    )
    db_session.add(foreign)
    db_session.commit()
    foreign_id = foreign.id

    login()
    response = client.post(
        "/delete-session",
        data={"id": foreign_id, "csrf_token": csrf("/history")},
    )

    assert response.status_code == 403
    assert db_session.get(StudySession, foreign_id) is not None


def test_cannot_delete_another_users_category(
    client, csrf, login, other_category, db_session):
    foreign_id = other_category.id
    login()
    response = client.post(
        "/delete-category",
        data={"id": foreign_id, "csrf_token": csrf("/categories")},
    )

    assert response.status_code == 403
    assert db_session.get(Category, foreign_id) is not None


def test_cannot_open_the_update_form_for_another_users_category(
    client, login, other_category
):
    login()
    response = client.get(f"/goupdate?id={other_category.id}")
    assert response.status_code == 403


def test_cannot_rename_another_users_category(
    client, csrf, login, other_category, db_session):
    foreign_id = other_category.id
    login()
    response = client.post(
        "/goupdate",
        data={
            "id": foreign_id,
            "update": "Hijacked",
            "csrf_token": csrf("/categories"),
        },
    )

    assert response.status_code == 403
    assert db_session.get(Category, foreign_id).category_name == "Chemistry"


def test_cannot_select_another_users_category(
    client, post_json, login, other_category
):
    login()
    response = post_json(
        "/select-category", {"category_id": other_category.id}, path="/"
    )
    assert response.status_code == 403
    with client.session_transaction() as session:
        assert session.get("selected_category") is None


def test_cannot_write_a_session_against_another_users_category(
    client, csrf, login, other_category, post_json
):
    login()
    post_json("/select-category", {"category_id": other_category.id}, path="/")

    # The selection is refused, so there is no session state to submit against.
    assert client.get("/finish").status_code == 302


def test_history_only_shows_your_own_sessions(
    client, login, study_session, other_user, other_category, db_session):
    db_session.add(
        StudySession(
            user_id=other_user.id, category_id=other_category.id, duration=60
        )
    )
    db_session.commit()

    login()
    html = client.get("/history").get_data(as_text=True)

    assert "Maths" in html
    assert "Chemistry" not in html


def test_categories_page_only_shows_your_own_categories(
    client, login, category, other_category
):
    login()
    html = client.get("/categories").get_data(as_text=True)

    # Match the rendered row, not the bare name: the new-subject form has a
    # "e.g. Organic Chemistry" placeholder, so a plain substring check would
    # pass on the placeholder and never prove the row was filtered out.
    assert re.search(r'<span class="h3">\s*Maths\s*</span>', html)
    assert not re.search(r'<span class="h3">\s*Chemistry\s*</span>', html)


def test_deleting_a_category_cascades_to_its_sessions(
    client, csrf, login, study_session, db_session):
    session_id = study_session.id
    category_id = study_session.category_id

    login()
    response = client.post(
        "/delete-category",
        data={"id": category_id, "csrf_token": csrf("/categories")},
    )

    assert response.status_code == 302
    # A request mutates rows through its own Session, so this one still holds
    # them in its identity map. Expire before reading, or the assertions pass
    # on stale objects rather than on what is in the database.
    db_session.expire_all()
    assert db_session.get(Category, category_id) is None
    assert db_session.get(StudySession, session_id) is None


def test_orphaned_sessions_cannot_appear_in_history(
    client, login, user, other_user, other_category, db_session):
    """The old SQLite build lost foreign keys, so history silently dropped rows."""
    login()
    html = client.get("/history").get_data(as_text=True)
    assert db_session.scalars(
        select(StudySession).where(StudySession.user_id == user.id)
    ).all() == []
    assert "No sessions yet" in html

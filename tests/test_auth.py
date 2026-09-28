from sqlalchemy import select

from models import Category, User


def test_register_creates_the_user_and_logs_them_in(client, csrf, db_session):
    token = csrf("/register")
    response = client.post(
        "/register",
        data={
            "username": "newcomer",
            "password": "a-long-enough-password",
            "confirmation": "a-long-enough-password",
            "csrf_token": token,
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    row = db_session.scalar(select(User).where(User.username == "newcomer"))
    assert row is not None
    assert row.password_hash != "a-long-enough-password"


def test_register_rejects_a_short_password(client, csrf):
    token = csrf("/register")
    response = client.post(
        "/register",
        data={
            "username": "newcomer",
            "password": "short",
            "confirmation": "short",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert "at least 8 characters" in response.get_data(as_text=True)


def test_register_rejects_a_mismatched_confirmation(client, csrf):
    token = csrf("/register")
    response = client.post(
        "/register",
        data={
            "username": "newcomer",
            "password": "a-long-enough-password",
            "confirmation": "something-else",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert "same password twice" in response.get_data(as_text=True)


def test_register_rejects_a_duplicate_username(client, csrf, user):
    token = csrf("/register")
    response = client.post(
        "/register",
        data={
            "username": "gabriel",
            "password": "a-long-enough-password",
            "confirmation": "a-long-enough-password",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert "different username" in response.get_data(as_text=True)


def test_login_with_correct_credentials_succeeds(client, login, user):
    response = login()
    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session["user_id"] == user.id


def test_login_with_a_wrong_password_is_refused(client, login, user):
    response = login(password="not-the-password")
    assert "valid username or password" in response.get_data(as_text=True)
    with client.session_transaction() as session:
        assert "user_id" not in session


def test_login_for_an_unknown_user_gives_the_same_message(client, csrf):
    response = client.post(
        "/login",
        data={
            "username": "ghost",
            "password": "whatever-password",
            "csrf_token": csrf("/login"),
        },
        follow_redirects=True,
    )
    assert "valid username or password" in response.get_data(as_text=True)


def test_logout_clears_the_session(client, login, user):
    login()
    client.get("/logout")
    with client.session_transaction() as session:
        assert "user_id" not in session


def test_duplicate_category_names_are_rejected_per_user(
    client, csrf, login, user, category, db_session):
    login()
    response = client.post(
        "/categories",
        data={"category": "maths", "csrf_token": csrf("/categories")},
        follow_redirects=True,
    )
    assert "already have a subject" in response.get_data(as_text=True)
    assert db_session.scalar(
        select(Category).where(Category.user_id == user.id)
    ).category_name == "Maths"


def test_renaming_a_subject_to_its_own_name_succeeds(
    client, csrf, login, user, category, db_session):
    """`exclude_id` keeps the row from colliding with itself, in both the
    identical and the differently-cased spelling."""
    login()

    for new_name in ("Maths", "maths", "MATHS"):
        response = client.post(
            "/goupdate",
            data={
                "id": category.id,
                "update": new_name,
                "csrf_token": csrf("/categories"),
            },
            follow_redirects=True,
        )
        assert response.status_code == 200, new_name
        assert "already have a subject" not in response.get_data(as_text=True)
        # The rename was done by the request's own Session, so drop this one's
        # identity map before reading, or it returns the pre-rename value.
        db_session.expire_all()
        assert db_session.get(Category, category.id).category_name == new_name


def test_renaming_onto_an_existing_name_is_rejected(
    client, csrf, login, user, category, db_session):
    db_session.add(Category(user_id=user.id, category_name="Chemistry"))
    db_session.commit()

    login()
    response = client.post(
        "/goupdate",
        data={
            "id": category.id,
            "update": "chemistry",
            "csrf_token": csrf("/categories"),
        },
        follow_redirects=True,
    )

    assert "already have a subject" in response.get_data(as_text=True)
    assert db_session.get(Category, category.id).category_name == "Maths"

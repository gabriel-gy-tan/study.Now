import pytest

EXPECTED_ROUTES = {
    "/",
    "/categories",
    "/delete-category",
    "/delete-session",
    "/desc",
    "/finish",
    "/goupdate",
    "/history",
    "/login",
    "/logout",
    "/register",
    "/select-category",
    "/static/<path:filename>",
}


def test_app_registers_every_original_route(app):
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert EXPECTED_ROUTES <= rules


@pytest.mark.parametrize("path", ["/", "/history", "/categories"])
def test_protected_pages_redirect_anonymous_visitors(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


@pytest.mark.parametrize("path", ["/login", "/register"])
def test_public_pages_render(client, path):
    assert client.get(path).status_code == 200


def test_unknown_page_renders_error_template(client):
    response = client.get("/definitely-not-a-route")
    assert response.status_code == 404


def test_security_headers_are_present(client):
    headers = client.get("/login").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_csrf_rejects_posts_without_a_token(client):
    response = client.post("/login", data={"username": "gabriel", "password": "x"})
    assert response.status_code == 400


def test_duration_filter_still_formats_seconds(app):
    assert app.jinja_env.filters["duration"](3661) == "01:01:01"
    assert app.jinja_env.filters["duration"](0) == "00:00:00"


def test_unknown_environment_is_rejected():
    from config import get_config

    with pytest.raises(RuntimeError):
        get_config("staging")

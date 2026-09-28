"""The limiter is now always enabled, so these tests need no special app."""


def test_login_posts_are_rate_limited(client, csrf):
    token = csrf("/login")

    codes = [
        client.post(
            "/login",
            data={"username": "nobody", "password": "wrong-password", "csrf_token": token},
        ).status_code
        for _ in range(11)
    ]

    assert codes[:10] == [302] * 10, codes
    assert codes[10] == 429, codes


def test_loading_the_login_page_is_never_rate_limited(client):
    assert [client.get("/login").status_code for _ in range(20)] == [200] * 20

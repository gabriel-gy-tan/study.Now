import os

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value


class BaseConfig:
    SECRET_KEY = _required("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = _required("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        # Fail fast on a wrong or unreachable DATABASE_URL instead of letting
        # psycopg retry each address for minutes.
        "connect_args": {"connect_timeout": 10},
    }

    WTF_CSRF_HEADERS = ["X-CSRFToken"]
    WTF_CSRF_TIME_LIMIT = None

    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 14
    MAX_CONTENT_LENGTH = 64 * 1024


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


# Resolved at import, but only ever *required* when the testing config is used.
_TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


class TestingConfig(BaseConfig):
    # Never silently inherited from DATABASE_URL: the suite runs TRUNCATE
    # between tests, so falling back to the dev database would destroy data.
    # get_config() refuses to return this class unless TEST_DATABASE_URL is set.
    SQLALCHEMY_DATABASE_URI = _TEST_DATABASE_URL or BaseConfig.SQLALCHEMY_DATABASE_URI
    TESTING = True
    DEBUG = False
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = True
    # The limiter stays on so tests exercise the real decorators. This matches
    # the Flask-Limiter default, and is stated here so nobody reads it as
    # "testing enables rate limiting while dev does not": it is on everywhere.
    # The counters are reset between tests; see the `reset_limiter` autouse
    # fixture in tests/conftest.py.
    RATELIMIT_ENABLED = True


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str | None = None):
    key = name or os.environ.get("APP_ENV", "development")
    if key not in CONFIGS:
        raise RuntimeError(
            f"Unknown APP_ENV {key!r}. Expected one of: {', '.join(CONFIGS)}"
        )
    if key == "testing" and not _TEST_DATABASE_URL:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. The test suite truncates tables, so it "
            "must point at a dedicated test database (Neon test branch)."
        )
    return CONFIGS[key]

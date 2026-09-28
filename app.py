
from flask import Flask, render_template, request

from auth import auth_bp
from categories import categories_bp
from config import get_config
from extensions import csrf, db, limiter, migrate
from timer import timer_bp

BLUEPRINTS = (auth_bp, categories_bp, timer_bp)


def formatted_time(total_seconds: int) -> str:
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def human_duration(total_seconds: int) -> str:
    """Compact form for stats: '3h 20m', '45m', '0m'."""
    total_seconds = max(int(total_seconds or 0), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60

    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    if minutes:
        return f"{minutes}m"
    if total_seconds:
        return f"{total_seconds}s"
    return "0m"


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    app.jinja_env.filters["duration"] = formatted_time
    app.jinja_env.filters["human"] = human_duration

    register_error_handlers(app)
    register_request_hooks(app)
    return app


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(400)
    def bad_request(error):
        return render_template("error.html", code=400, message="Bad request"), 400

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(403)
    def forbidden(error):
        return (
            render_template("error.html", code=403, message="Not yours to open"),
            403,
        )

    @app.errorhandler(413)
    def too_large(error):
        return render_template("error.html", code=413, message="Request too large"), 413

    @app.errorhandler(429)
    def rate_limited(error):
        return (
            render_template("error.html", code=429, message="Too many requests, slow down"),
            429,
        )

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return (
            render_template("error.html", code=500, message="Something went wrong"),
            500,
        )


CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        # Inline styles are still used for bar heights and a few layout tweaks.
        "style-src 'self' 'unsafe-inline'",
        "script-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "object-src 'none'",
    ]
)


def register_request_hooks(app: Flask) -> None:
    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        if request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

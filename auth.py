from flask import Blueprint, flash, redirect, render_template, request, session
from sqlalchemy import func, select
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, limiter
from models import User

auth_bp = Blueprint("auth", __name__)

MIN_PASSWORD_LENGTH = 8
MAX_USERNAME_LENGTH = 64
# Only credential submissions are capped; reloading the form must stay free.
LOGIN_RATE_LIMIT = "10 per minute"
REGISTER_RATE_LIMIT = "5 per hour"


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit(REGISTER_RATE_LIMIT, methods=["POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        confirmation = request.form.get("confirmation") or ""

        if not username or not password:
            flash("Enter a username and password")
            return redirect("/register")

        if len(username) > MAX_USERNAME_LENGTH:
            flash("Username is too long")
            return redirect("/register")

        if len(password) < MIN_PASSWORD_LENGTH:
            flash(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
            return redirect("/register")

        if password != confirmation:
            flash("Please enter the same password twice")
            return redirect("/register")

        taken = db.session.scalar(select(User.id).where(User.username == username))
        if taken is not None:
            flash("Please choose a different username")
            return redirect("/register")

        user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()

        session.clear()
        session["user_id"] = user.id
        session["username"] = user.username
        return redirect("/")

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(LOGIN_RATE_LIMIT, methods=["POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        if not username:
            flash("Please enter a username")
            return redirect("/login")

        if not password:
            flash("Please enter a password")
            return redirect("/login")

        user = db.session.scalar(
            select(User).where(func.lower(User.username) == username.lower())
        )

        if user is None or not check_password_hash(user.password_hash, password):
            flash("Please enter a valid username or password")
            return redirect("/login")

        session.clear()
        session["user_id"] = user.id
        session["username"] = user.username
        return redirect("/")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

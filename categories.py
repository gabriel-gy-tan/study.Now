from flask import Blueprint, abort, flash, redirect, render_template, request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from extensions import db
from helpers import current_user_id, load_owned, login_required
from models import Category

categories_bp = Blueprint("categories", __name__)

MAX_CATEGORY_NAME = 80


def _clean_name(raw: str | None) -> str:
    return (raw or "").strip()


def _name_taken(user_id: int, name: str, exclude_id: int | None = None) -> bool:
    """Subjects are compared without regard to case, so 'Maths' and 'maths'
    cannot both exist. The unique constraint is a backstop, not the check."""
    conditions = [
        Category.user_id == user_id,
        func.lower(Category.category_name) == name.lower(),
    ]
    if exclude_id is not None:
        conditions.append(Category.id != exclude_id)

    return db.session.scalar(select(Category.id).where(*conditions)) is not None


def _validate(name: str) -> str | None:
    if not name:
        return "Subject name cannot be empty"
    if len(name) > MAX_CATEGORY_NAME:
        return f"Subject name must be {MAX_CATEGORY_NAME} characters or fewer"
    return None


@categories_bp.route("/categories", methods=["GET", "POST"])
@login_required
def categories():
    if request.method == "POST":
        name = _clean_name(request.form.get("category"))

        problem = _validate(name)
        if problem:
            flash(problem)
            return redirect("/categories")

        if _name_taken(current_user_id(), name):
            flash("You already have a subject with that name")
            return redirect("/categories")

        db.session.add(Category(user_id=current_user_id(), category_name=name))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("You already have a subject with that name")
            return redirect("/categories")

    rows = db.session.scalars(
        select(Category)
        .where(Category.user_id == current_user_id())
        .order_by(Category.category_name)
    ).all()

    return render_template("categories.html", categories=rows)


@categories_bp.route("/delete-category", methods=["POST"])
@login_required
def delete_category():
    row, code = load_owned(Category, request.form.get("id"), current_user_id())

    if code is not None:
        # abort() so the registered error page renders, rather than an empty body.
        abort(code)

    db.session.delete(row)
    db.session.commit()
    return redirect("/categories")


@categories_bp.route("/goupdate", methods=["GET", "POST"])
@login_required
def goupdate():
    user_id = current_user_id()

    if request.method == "POST":
        name = _clean_name(request.form.get("update"))

        row, code = load_owned(Category, request.form.get("id"), user_id)
        if code is not None:
            abort(code)

        problem = _validate(name)
        if problem:
            flash(problem)
            return redirect("/categories")

        if _name_taken(user_id, name, exclude_id=row.id):
            flash("You already have a subject with that name")
            return redirect("/categories")

        row.category_name = name
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("You already have a subject with that name")
            return redirect("/categories")

        return redirect("/categories")

    row, code = load_owned(Category, request.args.get("id"), user_id)
    if code is not None:
        abort(code)

    return render_template("goupdate.html", id=row.id, category_name=row.category_name)


from sqlalchemy import func

from extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    categories = db.relationship(
        "Category",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sessions = db.relationship(
        "StudySession",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_name = db.Column(db.String(80), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user = db.relationship("User", back_populates="categories")
    sessions = db.relationship(
        "StudySession",
        back_populates="category",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "category_name", name="uq_category_name_per_user"),
        # The unique constraint above is case-sensitive, so "Maths" and "maths"
        # would both pass it. categories.py checks with func.lower(), but two
        # concurrent requests can both pass that check, so the database has to
        # enforce it as well.
        db.Index(
            "uq_categories_user_lower_name",
            "user_id",
            func.lower(db.text("category_name")),
            unique=True,
        ),
        db.Index("ix_categories_user", "user_id"),
    )


class StudySession(db.Model):
    __tablename__ = "sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    duration = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user = db.relationship("User", back_populates="sessions")
    category = db.relationship("Category", back_populates="sessions")

    __table_args__ = (
        db.CheckConstraint("duration > 0", name="ck_sessions_duration_positive"),
        db.Index("ix_sessions_user_created", "user_id", "created_at"),
    )

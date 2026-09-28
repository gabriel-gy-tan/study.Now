"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-27

"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category_name", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "category_name", name="uq_category_name_per_user"),
    )
    op.create_index("ix_categories_user", "categories", ["user_id"])
    # Subject names are compared case-insensitively in the application, and a
    # unique constraint on the raw column is case-sensitive, so the database
    # needs a functional index to stop two concurrent creates both succeeding.
    op.create_index(
        "uq_categories_user_lower_name",
        "categories",
        ["user_id", sa.text("lower(category_name)")],
        unique=True,
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("duration > 0", name="ck_sessions_duration_positive"),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_user_created", "sessions", ["user_id", "created_at"])


def downgrade():
    op.drop_index("ix_sessions_user_created", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("uq_categories_user_lower_name", table_name="categories")
    op.drop_index("ix_categories_user", table_name="categories")
    op.drop_table("categories")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")

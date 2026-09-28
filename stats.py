"""Read-only aggregates derived from the user's own study sessions.

Nothing here is stored or invented. Every figure is summed from rows in
`sessions`, so a total can never disagree with the history table.

Day boundaries are UTC. A per-user timezone would need a new column and a
setting, which is a product decision rather than a design one.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from extensions import db
from models import Category, StudySession

DAYS_IN_SERIES = 7


def _midnight_utc(days_ago: int = 0) -> datetime:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start - timedelta(days=days_ago)


def _total_seconds(user_id: int, since: datetime | None = None) -> int:
    conditions = [StudySession.user_id == user_id]
    if since is not None:
        conditions.append(StudySession.created_at >= since)

    value = db.session.scalar(
        select(func.coalesce(func.sum(StudySession.duration), 0)).where(*conditions)
    )
    return int(value or 0)


def _session_count(user_id: int, since: datetime | None = None) -> int:
    conditions = [StudySession.user_id == user_id]
    if since is not None:
        conditions.append(StudySession.created_at >= since)

    value = db.session.scalar(
        select(func.count(StudySession.id)).where(*conditions)
    )
    return int(value or 0)


def summary(user_id: int) -> dict:
    """Figures for the stat row. `week` is the last seven days including today."""

    today_start = _midnight_utc()
    week_start = today_start - timedelta(days=6)

    return {
        "today": _total_seconds(user_id, today_start),
        "today_sessions": _session_count(user_id, today_start),
        "week": _total_seconds(user_id, week_start),
        "total": _total_seconds(user_id),
        "sessions": _session_count(user_id),
    }


def daily_series(user_id: int, days: int = DAYS_IN_SERIES) -> list[dict]:
    """One bucket per day for the last `days` days, oldest first, gaps filled."""

    first = _midnight_utc(days - 1)
    day = func.date_trunc("day", StudySession.created_at)

    rows = db.session.execute(
        select(day, func.coalesce(func.sum(StudySession.duration), 0))
        .where(StudySession.user_id == user_id, StudySession.created_at >= first)
        .group_by(day)
        .order_by(day)
    ).all()

    totals = {}
    for bucket, seconds in rows:
        key = bucket.date() if hasattr(bucket, "date") else bucket
        totals[key] = int(seconds or 0)

    series = []
    for offset in range(days):
        moment = first + timedelta(days=offset)
        series.append(
            {
                "date": moment,
                "label": moment.strftime("%a")[0],
                "full_label": moment.strftime("%A"),
                "seconds": totals.get(moment.date(), 0),
                "is_today": offset == days - 1,
            }
        )
    return series


def category_breakdown(user_id: int, limit: int = 5) -> tuple[list[dict], int]:
    """Time per subject, largest first. Also returns the number of distinct
    subjects so the view can say "+3 more" without guessing."""

    rows = db.session.execute(
        select(
            Category.category_name,
            func.coalesce(func.sum(StudySession.duration), 0).label("seconds"),
            func.count(StudySession.id).label("sessions"),
        )
        .select_from(StudySession)
        .join(Category, StudySession.category_id == Category.id)
        .where(StudySession.user_id == user_id)
        .group_by(Category.id, Category.category_name)
        .order_by(func.sum(StudySession.duration).desc())
    ).all()

    total = sum(int(row.seconds) for row in rows) or 0
    subjects = [
        {
            "name": row.category_name,
            "seconds": int(row.seconds),
            "sessions": int(row.sessions),
            "share": (int(row.seconds) / total * 100) if total else 0.0,
        }
        for row in rows
    ]
    return subjects[:limit], len(subjects)


def recent(user_id: int, limit: int = 5) -> list[StudySession]:
    return list(
        db.session.scalars(
            select(StudySession)
            .options(joinedload(StudySession.category))
            .where(StudySession.user_id == user_id)
            .order_by(StudySession.created_at.desc(), StudySession.id.desc())
            .limit(limit)
        )
    )

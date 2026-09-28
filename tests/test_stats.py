"""Tests for the derived statistics.

Every figure must be a sum over the caller's own sessions. These tests exist
mostly to prove that a user never sees another user's time.
"""

from datetime import datetime, timedelta, timezone

from models import StudySession
from stats import DAYS_IN_SERIES, category_breakdown, daily_series, recent, summary


def _session(user_id, category_id, seconds, days_ago=0, hour=12):
    db_time = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return StudySession(
        user_id=user_id,
        category_id=category_id,
        duration=seconds,
        description=None,
        created_at=db_time.replace(hour=hour, minute=0, second=0, microsecond=0),
    )


def test_summary_counts_only_your_own_sessions(db_session, user, other_user, category, app_ctx):
    other_category = StudySession(
        user_id=other_user.id, category_id=category.id, duration=9999
    )
    mine = _session(user.id, category.id, 3600)
    db_session.add_all([other_category, mine])
    db_session.commit()

    result = summary(user.id)

    assert result["total"] == 3600
    assert result["sessions"] == 1


def test_summary_totals_match_a_manual_sum(db_session, user, category, app_ctx):
    db_session.add_all(
        [
            _session(user.id, category.id, 600, days_ago=0),
            _session(user.id, category.id, 900, days_ago=1),
            _session(user.id, category.id, 1200, days_ago=10),
        ]
    )
    db_session.commit()

    result = summary(user.id)

    assert result["total"] == 2700
    assert result["today"] == 600
    assert result["sessions"] == 3
    # A session 10 days ago is outside the trailing seven day window.
    assert result["week"] == 1500


def test_summary_is_all_zero_for_a_new_account(db_session, user, app_ctx):
    result = summary(user.id)

    assert result == {
        "today": 0,
        "today_sessions": 0,
        "week": 0,
        "total": 0,
        "sessions": 0,
    }


def test_daily_series_always_returns_one_bucket_per_day(db_session, user, app_ctx):
    series = daily_series(user.id)

    assert len(series) == DAYS_IN_SERIES
    assert series[0]["is_today"] is False
    assert series[-1]["is_today"] is True
    assert all(len(bucket["label"]) == 1 for bucket in series)


def test_daily_series_fills_gaps_with_zero(db_session, user, category, app_ctx):
    db_session.add(_session(user.id, category.id, 1800, days_ago=3))
    db_session.commit()

    series = daily_series(user.id)

    assert sum(bucket["seconds"] for bucket in series) == 1800
    assert any(bucket["seconds"] == 0 for bucket in series)
    assert sum(1 for bucket in series if bucket["seconds"] == 0) == DAYS_IN_SERIES - 1


def test_daily_series_is_scoped_to_the_user(
    db_session, user, other_user, category, app_ctx):
    db_session.add(_session(other_user.id, category.id, 5000))
    db_session.commit()

    assert sum(b["seconds"] for b in daily_series(user.id)) == 0


def test_category_breakdown_shares_sum_to_one_hundred(
    db_session, user, category, app_ctx):
    second = StudySession(user_id=user.id, category_id=category.id, duration=1000)
    db_session.add_all(
        [
            _session(user.id, category.id, 3000),
            second,
        ]
    )
    db_session.commit()

    subjects, count = category_breakdown(user.id)

    assert count == 1
    assert subjects[0]["seconds"] == 4000
    assert subjects[0]["sessions"] == 2
    assert round(sum(s["share"] for s in subjects), 1) == 100.0


def test_category_breakdown_orders_by_time(db_session, user, category, app_ctx):
    from models import Category

    history = Category(user_id=user.id, category_name="History")
    db_session.add(history)
    db_session.flush()
    db_session.add_all(
        [
            _session(user.id, category.id, 100),
            _session(user.id, history.id, 9000),
        ]
    )
    db_session.commit()

    subjects, _ = category_breakdown(user.id)

    assert subjects[0]["name"] == "History"
    assert subjects[1]["name"] == category.category_name


def test_category_breakdown_respects_the_limit(db_session, user, app_ctx):
    from models import Category

    for index in range(8):
        subject = Category(user_id=user.id, category_name=f"Subject {index}")
        db_session.add(subject)
        db_session.flush()
        db_session.add(_session(user.id, subject.id, 100 * (index + 1)))

    db_session.commit()

    subjects, count = category_breakdown(user.id, limit=3)

    assert count == 8
    assert len(subjects) == 3


def test_recent_returns_newest_first(db_session, user, category, app_ctx):
    db_session.add_all(
        [
            _session(user.id, category.id, 100, days_ago=2),
            _session(user.id, category.id, 200, days_ago=0),
        ]
    )
    db_session.commit()

    rows = recent(user.id, limit=5)

    assert [row.duration for row in rows] == [200, 100]

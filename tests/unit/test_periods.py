from __future__ import annotations

from datetime import datetime, timezone

from dmarc_reporter.reporting.periods import (
    build_period,
    determine_report_build_action,
    period_is_complete,
    periods_for_coverage_window,
    transition_period_status,
)


def test_periods_for_coverage_window_uses_iso_week_month_and_year() -> None:
    periods = periods_for_coverage_window(
        "2024-04-15T00:00:00+00:00",
        "2024-04-15T23:59:59+00:00",
        as_of=datetime(2024, 4, 20, tzinfo=timezone.utc),
    )

    assert {period.period_type for period in periods} == {"weekly", "monthly", "yearly"}
    weekly = next(period for period in periods if period.period_type == "weekly")
    assert weekly.period_id == "weekly-2024-W16"
    assert weekly.period_start.isoformat() == "2024-04-15"
    assert weekly.period_end.isoformat() == "2024-04-21"


def test_period_is_complete_requires_period_end_before_reference_day() -> None:
    assert period_is_complete(
        datetime(2024, 4, 14, tzinfo=timezone.utc).date(),
        as_of=datetime(2024, 4, 15, tzinfo=timezone.utc),
    )
    assert not period_is_complete(
        datetime(2024, 4, 15, tzinfo=timezone.utc).date(),
        as_of=datetime(2024, 4, 15, tzinfo=timezone.utc),
    )


def test_transition_period_status_marks_completed_period_stale_when_new_data_arrives() -> None:
    period = build_period(
        "weekly",
        datetime(2024, 4, 15, tzinfo=timezone.utc),
        as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    assert transition_period_status(
        current_status="current",
        period=period,
        has_existing_artifact=True,
        content_changed=True,
    ) == "stale"


def test_transition_period_status_marks_open_period_complete_when_closed() -> None:
    period = build_period(
        "monthly",
        datetime(2024, 4, 15, tzinfo=timezone.utc),
        as_of=datetime(2024, 5, 1, tzinfo=timezone.utc),
    )

    assert transition_period_status(
        current_status="open",
        period=period,
        has_existing_artifact=False,
        content_changed=True,
    ) == "pending_initial"


def test_transition_period_status_keeps_current_report_current_when_content_is_unchanged() -> None:
    period = build_period(
        "yearly",
        datetime(2024, 4, 15, tzinfo=timezone.utc),
        as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    assert transition_period_status(
        current_status="current",
        period=period,
        has_existing_artifact=True,
        content_changed=False,
    ) == "current"


def test_determine_report_build_action_marks_current_artifact_as_skip_unchanged() -> None:
    assert determine_report_build_action(
        refresh_status="current",
        has_existing_artifact=True,
        artifact_exists=True,
    ) == ("skip_unchanged", "unchanged_data")


def test_determine_report_build_action_marks_stale_artifact_for_refresh() -> None:
    assert determine_report_build_action(
        refresh_status="stale",
        has_existing_artifact=True,
        artifact_exists=True,
    ) == ("refresh", "stale_data")


def test_determine_report_build_action_marks_missing_artifact_for_generate() -> None:
    assert determine_report_build_action(
        refresh_status="current",
        has_existing_artifact=False,
        artifact_exists=False,
    ) == ("generate", "missing_artifact")

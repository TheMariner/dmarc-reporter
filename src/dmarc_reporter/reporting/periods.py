"""Reporting period helpers for weekly, monthly, and yearly rollups."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import calendar


@dataclass(frozen=True)
class ReportingPeriod:
    """Represents a reportable time period."""

    period_id: str
    period_type: str
    period_start: date
    period_end: date
    calendar_rule: str
    completeness_status: str
    refresh_status: str = "pending_initial"
    latest_source_date: str | None = None
    last_data_change_at: str | None = None
    last_built_at: str | None = None
    last_built_run_id: str | None = None
    last_change_reason: str | None = None


def build_period(
    period_type: str,
    anchor_dt: datetime,
    *,
    as_of: datetime | None = None,
) -> ReportingPeriod:
    """Build a single reporting period from a coverage anchor."""
    reference = as_of or datetime.now(timezone.utc)
    anchor = anchor_dt.date()
    builders = {
        "weekly": _weekly_period,
        "monthly": _monthly_period,
        "yearly": _yearly_period,
    }
    try:
        return builders[period_type](anchor, reference)
    except KeyError as exc:
        raise ValueError(f"Unsupported period type: {period_type}") from exc


def periods_for_coverage_window(
    coverage_begin: str,
    coverage_end: str,
    *,
    as_of: datetime | None = None,
) -> list[ReportingPeriod]:
    """Build weekly, monthly, and yearly reporting periods from coverage dates."""
    begin_dt = datetime.fromisoformat(coverage_begin)
    end_dt = datetime.fromisoformat(coverage_end)
    reference = as_of or datetime.now(timezone.utc)

    periods = [
        build_period("weekly", end_dt, as_of=reference),
        build_period("monthly", begin_dt, as_of=reference),
        build_period("yearly", begin_dt, as_of=reference),
    ]

    latest_source = end_dt.isoformat()
    return [
        ReportingPeriod(
            period_id=period.period_id,
            period_type=period.period_type,
            period_start=period.period_start,
            period_end=period.period_end,
            calendar_rule=period.calendar_rule,
            completeness_status=period.completeness_status,
            latest_source_date=latest_source,
        )
        for period in periods
    ]


def period_is_complete(period_end: date, *, as_of: datetime | None = None) -> bool:
    """Return whether a period ending date is complete relative to the current date."""
    reference = (as_of or datetime.now(timezone.utc)).date()
    return period_end < reference


def transition_period_status(
    *,
    current_status: str | None,
    period: ReportingPeriod,
    has_existing_artifact: bool,
    content_changed: bool,
) -> str:
    """Return the next refresh status for a reporting period."""
    if period.completeness_status != "complete":
        return "pending_initial"
    if current_status == "failed":
        return "failed"
    if not has_existing_artifact:
        return "pending_initial"
    if content_changed:
        return "stale"
    return "current"


def determine_report_build_action(
    *,
    refresh_status: str,
    has_existing_artifact: bool,
    artifact_exists: bool,
) -> tuple[str, str]:
    """Return the next report build action and decision reason."""
    if not has_existing_artifact or not artifact_exists:
        return ("generate", "missing_artifact")
    if refresh_status == "stale":
        return ("refresh", "stale_data")
    if refresh_status == "failed":
        return ("refresh", "previous_failure")
    if refresh_status == "pending_initial":
        return ("generate", "missing_artifact")
    return ("skip_unchanged", "unchanged_data")


def _weekly_period(anchor: date, reference: datetime) -> ReportingPeriod:
    iso_year, iso_week, iso_weekday = anchor.isocalendar()
    start = anchor - timedelta(days=iso_weekday - 1)
    end = start + timedelta(days=6)
    return ReportingPeriod(
        period_id=f"weekly-{iso_year}-W{iso_week:02d}",
        period_type="weekly",
        period_start=start,
        period_end=end,
        calendar_rule="iso_week",
        completeness_status="complete" if period_is_complete(end, as_of=reference) else "open",
    )


def _monthly_period(anchor: date, reference: datetime) -> ReportingPeriod:
    start = anchor.replace(day=1)
    end = anchor.replace(day=calendar.monthrange(anchor.year, anchor.month)[1])
    return ReportingPeriod(
        period_id=f"monthly-{anchor.year}-{anchor.month:02d}",
        period_type="monthly",
        period_start=start,
        period_end=end,
        calendar_rule="calendar_month",
        completeness_status="complete" if period_is_complete(end, as_of=reference) else "open",
    )


def _yearly_period(anchor: date, reference: datetime) -> ReportingPeriod:
    start = anchor.replace(month=1, day=1)
    end = anchor.replace(month=12, day=31)
    return ReportingPeriod(
        period_id=f"yearly-{anchor.year}",
        period_type="yearly",
        period_start=start,
        period_end=end,
        calendar_rule="calendar_year",
        completeness_status="complete" if period_is_complete(end, as_of=reference) else "open",
    )

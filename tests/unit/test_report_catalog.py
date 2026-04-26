from __future__ import annotations

from datetime import date
from pathlib import Path

from dmarc_reporter.reporting.builder import (
    build_report_library_catalog,
    build_report_library_entry,
    build_report_shell,
    build_report_sidebar_state,
)
from dmarc_reporter.reporting.periods import ReportingPeriod


def test_build_report_sidebar_state_includes_scroll_preservation_metadata() -> None:
    state = build_report_sidebar_state(
        filters={
            "reporters": ["Example Mail", "Spoof Watch"],
            "compliance_categories": ["compliant", "non_compliant"],
            "dispositions": ["none", "reject"],
        }
    )

    assert state["layout"]["sidebar_position"] == "left"
    assert state["layout"]["sidebar_scroll"] == "independent"
    assert state["scroll_preservation"]["strategy"] == "restore-main-scroll"
    assert state["sidebar"]["filter_groups"][0]["label"] == "Reporters"


def test_build_report_shell_uses_fallback_when_logo_asset_is_missing() -> None:
    shell = build_report_shell(
        page_kind="report",
        title="Weekly DMARC Report",
        subtitle="2024-04-15 to 2024-04-21",
        logo_path=Path("src/dmarc_reporter/web/assets/does-not-exist.svg"),
    )

    assert shell["theme_name"] == "dark"
    assert shell["brand_name"] == "Logo"
    assert shell["logo_mode"] == "fallback-mark"
    assert "Logo" in shell["logo_markup"]


def test_build_report_library_entry_derives_calendar_dimensions() -> None:
    period = ReportingPeriod(
        period_id="weekly-2024-W16",
        period_type="weekly",
        period_start=date(2024, 4, 15),
        period_end=date(2024, 4, 21),
        calendar_rule="iso_week",
        completeness_status="complete",
    )

    entry = build_report_library_entry(
        period=period,
        output_path=Path("/tmp/reports/weekly/weekly-2024-W16.html"),
        reports_dir=Path("/tmp/reports"),
        content_hash="abc123",
        build_status="generated",
        generated_at="2026-04-18T00:00:00+00:00",
    )

    assert entry["cadence"] == "weekly"
    assert entry["report_year"] == 2024
    assert entry["report_month"] == 4
    assert entry["report_week"] == 16
    assert entry["relative_path"] == "weekly/weekly-2024-W16.html"
    assert entry["period_label"] == "Week 16, 2024"


def test_build_report_library_catalog_only_surfaces_available_filters() -> None:
    catalog = build_report_library_catalog(
        [
            {
                "period_id": "weekly-2024-W16",
                "cadence": "weekly",
                "report_year": 2024,
                "report_month": 4,
                "report_week": 16,
                "period_start": "2024-04-15",
                "period_end": "2024-04-21",
                "period_label": "Week 16, 2024",
                "display_title": "Weekly DMARC Report",
                "relative_path": "weekly/weekly-2024-W16.html",
                "build_status": "generated",
            },
            {
                "period_id": "monthly-2024-04",
                "cadence": "monthly",
                "report_year": 2024,
                "report_month": 4,
                "report_week": None,
                "period_start": "2024-04-01",
                "period_end": "2024-04-30",
                "period_label": "April 2024",
                "display_title": "Monthly DMARC Report",
                "relative_path": "monthly/monthly-2024-04.html",
                "build_status": "generated",
            },
        ]
    )

    assert catalog["filters"]["cadence"] == ["weekly", "monthly"]
    assert catalog["filters"]["years"] == [2024]
    assert catalog["filters"]["months"] == [4]
    assert catalog["filters"]["weeks"] == [16]
    assert catalog["entries"][0]["relative_path"] == "monthly/monthly-2024-04.html"


def test_build_report_library_catalog_orders_entries_by_period_date_not_derived_month() -> None:
    catalog = build_report_library_catalog(
        [
            {
                "period_id": "weekly-2026-W01",
                "cadence": "weekly",
                "report_year": 2026,
                "report_month": 12,
                "report_week": 1,
                "period_start": "2025-12-29",
                "period_end": "2026-01-04",
                "period_label": "Week 1, 2026",
                "display_title": "Weekly DMARC Report",
                "relative_path": "weekly/weekly-2026-W01.html",
                "build_status": "generated",
            },
            {
                "period_id": "monthly-2026-03",
                "cadence": "monthly",
                "report_year": 2026,
                "report_month": 3,
                "report_week": None,
                "period_start": "2026-03-01",
                "period_end": "2026-03-31",
                "period_label": "March 2026",
                "display_title": "Monthly DMARC Report",
                "relative_path": "monthly/monthly-2026-03.html",
                "build_status": "generated",
            },
        ]
    )

    assert catalog["entries"][0]["relative_path"] == "monthly/monthly-2026-03.html"
    assert catalog["entries"][1]["relative_path"] == "weekly/weekly-2026-W01.html"

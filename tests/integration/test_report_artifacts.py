from __future__ import annotations

import json
from pathlib import Path
import re

from dmarc_reporter.reporting.builder import (
    build_report_library_catalog,
    build_static_index,
    build_static_report,
)
from dmarc_reporter.reporting.periods import ReportingPeriod


def sample_report_summary() -> dict[str, object]:
    return {
        "total_messages": 67,
        "record_count": 3,
        "disposition_counts": {"none": 42, "reject": 20, "quarantine": 5},
        "compliance_counts": {"compliant": 42, "non_compliant": 25},
        "dkim_alignment_counts": {"pass": 42, "fail": 25},
        "spf_alignment_counts": {"pass": 42, "fail": 25},
        "top_source_ips": [("203.0.113.20", 20), ("203.0.113.10", 42), ("203.0.113.30", 5)],
        "top_domains": [("example.com", 62), ("example.net", 5)],
        "top_reporters": [("Example Mail", 42), ("Spoof Watch", 20), ("Mailbox Filter", 5)],
        "top_reporters_non_compliant": [("Spoof Watch", 20), ("Mailbox Filter", 5)],
        "top_sources_compliant": [("203.0.113.10", 42)],
        "top_sources_non_compliant": [("203.0.113.20", 20), ("203.0.113.30", 5)],
        "top_results": {
            "reporters": {
                "collection_name": "top_reporters",
                "segment_type": "reporter",
                "items": [
                    {
                        "segment_type": "reporter",
                        "segment_key": "Spoof Watch",
                        "display_label": "Spoof Watch",
                        "message_count": 20,
                        "record_count": 1,
                        "risk_weight": 20,
                    },
                    {
                        "segment_type": "reporter",
                        "segment_key": "Example Mail",
                        "display_label": "Example Mail",
                        "message_count": 42,
                        "record_count": 1,
                        "risk_weight": 42,
                    },
                ],
                "total_available": 3,
                "default_visible_count": 2,
            },
            "sources": {
                "collection_name": "top_sources",
                "segment_type": "source",
                "items": [
                    {
                        "segment_type": "source",
                        "segment_key": "203.0.113.20",
                        "display_label": "203.0.113.20",
                        "message_count": 20,
                        "record_count": 1,
                        "risk_weight": 20,
                    }
                ],
                "total_available": 3,
                "default_visible_count": 2,
            },
            "compliance": {
                "collection_name": "top_compliance",
                "segment_type": "compliance",
                "items": [
                    {
                        "segment_type": "compliance",
                        "segment_key": "non_compliant",
                        "display_label": "Non-Compliant",
                        "message_count": 25,
                        "record_count": 2,
                        "risk_weight": 25,
                    }
                ],
                "total_available": 2,
                "default_visible_count": 2,
            },
            "disposition": {
                "collection_name": "top_disposition",
                "segment_type": "disposition",
                "items": [
                    {
                        "segment_type": "disposition",
                        "segment_key": "reject",
                        "display_label": "Reject",
                        "message_count": 20,
                        "record_count": 1,
                        "risk_weight": 20,
                    }
                ],
                "total_available": 3,
                "default_visible_count": 2,
            },
        },
        "insight_sections": [
            {"id": "overview", "title": "Overview", "kind": "summary"},
            {"id": "reporters", "title": "Reporter View", "kind": "reporter"},
            {"id": "sources", "title": "Source View", "kind": "source"},
            {"id": "compliance", "title": "Compliance View", "kind": "compliance"},
        ],
        "records": [
            {
                "source_ip": "203.0.113.10",
                "reporter": "Example Mail",
                "header_from": "example.com",
                "count": 42,
                "disposition": "none",
                "compliance_category": "compliant",
                "dkim_result": "pass",
                "spf_result": "pass",
            },
            {
                "source_ip": "203.0.113.20",
                "reporter": "Spoof Watch",
                "header_from": "example.com",
                "count": 20,
                "disposition": "reject",
                "compliance_category": "non_compliant",
                "dkim_result": "fail",
                "spf_result": "fail",
            },
            {
                "source_ip": "203.0.113.30",
                "reporter": "Mailbox Filter",
                "header_from": "example.net",
                "count": 5,
                "disposition": "quarantine",
                "compliance_category": "non_compliant",
                "dkim_result": "fail",
                "spf_result": "fail",
            },
        ],
        "partial_data": True,
        "partial_data_reasons": ["1 source report was skipped after validation failure"],
    }


def sample_catalog() -> dict[str, object]:
    return build_report_library_catalog(
        [
            {
                "period_id": "weekly-2024-W16",
                "cadence": "weekly",
                "report_year": 2024,
                "report_month": 4,
                "report_week": 16,
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
                "period_label": "April 2024",
                "display_title": "Monthly DMARC Report",
                "relative_path": "monthly/monthly-2024-04.html",
                "build_status": "generated",
            },
        ]
    )


def extract_payload(html: str, *, script_id: str) -> dict[str, object]:
    match = re.search(
        rf'<script id="{script_id}" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def assert_self_contained_report(html: str, content_hash: str) -> None:
    assert "<style>" in html
    assert "<script>" in html
    assert "Weekly DMARC Report" in html
    assert "report-shell" in html
    assert "filters-sidebar" in html
    assert "main-pane" in html
    assert "scroll-preserver" in html
    assert "Logo" in html
    assert "How To Use This Report" in html
    assert "Filter this period from the" in html
    assert "keeps its own scroll state" not in html
    assert "1 source report was skipped after validation failure" in html
    assert len(content_hash) == 64


def test_generated_report_artifact_is_self_contained() -> None:
    period = ReportingPeriod(
        period_id="weekly-2024-W16",
        period_type="weekly",
        period_start=__import__("datetime").date(2024, 4, 15),
        period_end=__import__("datetime").date(2024, 4, 21),
        calendar_rule="iso_week",
        completeness_status="complete",
    )
    html, content_hash = build_static_report(
        period=period,
        summary=sample_report_summary(),
        template_path=Path("src/dmarc_reporter/web/template.html.j2"),
        styles_path=Path("src/dmarc_reporter/web/styles.css"),
        script_path=Path("src/dmarc_reporter/web/app.js"),
    )

    assert_self_contained_report(html, content_hash)


def test_generated_report_artifact_embeds_sidebar_and_scroll_state() -> None:
    period = ReportingPeriod(
        period_id="weekly-2024-W16",
        period_type="weekly",
        period_start=__import__("datetime").date(2024, 4, 15),
        period_end=__import__("datetime").date(2024, 4, 21),
        calendar_rule="iso_week",
        completeness_status="complete",
    )
    html, _content_hash = build_static_report(
        period=period,
        summary=sample_report_summary(),
        template_path=Path("src/dmarc_reporter/web/template.html.j2"),
        styles_path=Path("src/dmarc_reporter/web/styles.css"),
        script_path=Path("src/dmarc_reporter/web/app.js"),
    )
    payload = extract_payload(html, script_id="report-data")

    report_experience = payload["report_experience"]
    assert report_experience["default_view"] == "overview"
    assert report_experience["initial_state"]["active_view"] == "overview"
    assert report_experience["layout"]["sidebar_position"] == "left"
    assert report_experience["layout"]["sidebar_scroll"] == "independent"
    assert report_experience["scroll_preservation"]["strategy"] == "restore-main-scroll"
    assert report_experience["scroll_preservation"]["target_container"] == "main-pane-scroll"
    assert report_experience["sidebar"]["filter_groups"][0]["id"] == "reporters"
    assert report_experience["filterable_views"]["reporters"]["top_results"][0]["segment_key"] == "Spoof Watch"
    assert report_experience["filterable_views"]["compliance"]["detail_rows"][0]["compliance_category"] == "non_compliant"


def test_generated_report_artifact_embeds_branded_shell_metadata() -> None:
    period = ReportingPeriod(
        period_id="weekly-2024-W16",
        period_type="weekly",
        period_start=__import__("datetime").date(2024, 4, 15),
        period_end=__import__("datetime").date(2024, 4, 21),
        calendar_rule="iso_week",
        completeness_status="complete",
    )
    html, _content_hash = build_static_report(
        period=period,
        summary=sample_report_summary(),
        template_path=Path("src/dmarc_reporter/web/template.html.j2"),
        styles_path=Path("src/dmarc_reporter/web/styles.css"),
        script_path=Path("src/dmarc_reporter/web/app.js"),
    )
    payload = extract_payload(html, script_id="report-data")

    assert payload["shell"]["theme_name"] == "dark"
    assert payload["shell"]["brand_name"] == "Logo"
    assert payload["shell"]["logo_mode"] in {"embedded-image", "fallback-mark"}
    assert payload["shell"]["page_kind"] == "report"
    assert "brand-image" in html or "brand-mark-fallback" in html
    assert "shell-header" in html


def test_generated_report_artifact_remains_self_contained_with_no_backend_dependencies() -> None:
    period = ReportingPeriod(
        period_id="weekly-2024-W16",
        period_type="weekly",
        period_start=__import__("datetime").date(2024, 4, 15),
        period_end=__import__("datetime").date(2024, 4, 21),
        calendar_rule="iso_week",
        completeness_status="complete",
    )
    html, _content_hash = build_static_report(
        period=period,
        summary=sample_report_summary(),
        template_path=Path("src/dmarc_reporter/web/template.html.j2"),
        styles_path=Path("src/dmarc_reporter/web/styles.css"),
        script_path=Path("src/dmarc_reporter/web/app.js"),
    )

    assert '<script src=' not in html
    assert '<link rel="stylesheet"' not in html
    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html


def test_generated_index_artifact_is_self_contained_and_filter_first() -> None:
    html, content_hash = build_static_index(
        catalog=sample_catalog(),
        template_path=Path("src/dmarc_reporter/web/index.html.j2"),
        styles_path=Path("src/dmarc_reporter/web/styles.css"),
        script_path=Path("src/dmarc_reporter/web/index.js"),
    )
    payload = extract_payload(html, script_id="index-data")

    assert "<style>" in html
    assert "<script>" in html
    assert "filters-sidebar" in html
    assert "report-library" in html
    assert "weekly/weekly-2024-W16.html" in html
    assert "cadence-chips" in html
    assert payload["catalog"]["filters"]["cadence"] == ["weekly", "monthly"]
    assert payload["shell"]["theme_name"] == "dark"
    assert len(content_hash) == 64

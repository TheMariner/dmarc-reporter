from __future__ import annotations

import json
import re
from pathlib import Path

from dmarc_reporter.reporting.builder import build_report_library_catalog, build_static_index


def extract_index_payload(html: str) -> dict[str, object]:
    match = re.search(
        r'<script id="index-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


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
                "period_id": "yearly-2024",
                "cadence": "yearly",
                "report_year": 2024,
                "report_month": None,
                "report_week": None,
                "period_label": "Calendar Year 2024",
                "display_title": "Yearly DMARC Report",
                "relative_path": "yearly/yearly-2024.html",
                "build_status": "generated",
            },
        ]
    )


def test_generated_index_artifact_embeds_available_filter_options() -> None:
    html, _content_hash = build_static_index(
        catalog=sample_catalog(),
        template_path=Path("src/dmarc_reporter/web/index.html.j2"),
        styles_path=Path("src/dmarc_reporter/web/styles.css"),
        script_path=Path("src/dmarc_reporter/web/index.js"),
    )
    payload = extract_index_payload(html)

    assert payload["catalog"]["filters"]["cadence"] == ["weekly", "yearly"]
    assert payload["catalog"]["filters"]["years"] == [2024]
    assert payload["catalog"]["filters"]["weeks"] == [16]
    assert payload["catalog"]["filters"]["months"] == []


def test_generated_index_artifact_preserves_calendar_month_order_in_payload() -> None:
    html, _content_hash = build_static_index(
        catalog=build_report_library_catalog(
            [
                {
                    "period_id": "monthly-2024-12",
                    "cadence": "monthly",
                    "report_year": 2024,
                    "report_month": 12,
                    "report_week": None,
                    "period_label": "December 2024",
                    "display_title": "Monthly DMARC Report",
                    "relative_path": "monthly/monthly-2024-12.html",
                    "build_status": "generated",
                },
                {
                    "period_id": "monthly-2024-02",
                    "cadence": "monthly",
                    "report_year": 2024,
                    "report_month": 2,
                    "report_week": None,
                    "period_label": "February 2024",
                    "display_title": "Monthly DMARC Report",
                    "relative_path": "monthly/monthly-2024-02.html",
                    "build_status": "generated",
                },
            ]
        ),
        template_path=Path("src/dmarc_reporter/web/index.html.j2"),
        styles_path=Path("src/dmarc_reporter/web/styles.css"),
        script_path=Path("src/dmarc_reporter/web/index.js"),
    )
    payload = extract_index_payload(html)

    assert payload["catalog"]["filters"]["months"] == [2, 12]


def test_generated_index_artifact_has_empty_state_for_missing_cadence() -> None:
    html, _content_hash = build_static_index(
        catalog=build_report_library_catalog([]),
        template_path=Path("src/dmarc_reporter/web/index.html.j2"),
        styles_path=Path("src/dmarc_reporter/web/styles.css"),
        script_path=Path("src/dmarc_reporter/web/index.js"),
    )
    payload = extract_index_payload(html)

    assert "No generated reports match this slice" in html
    assert payload["catalog"]["entries"] == []
    assert payload["catalog"]["filters"]["cadence"] == []
    assert '<script src=' not in html
    assert '<link rel="stylesheet"' not in html

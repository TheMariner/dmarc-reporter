"""Static SPA report and index builders."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from dmarc_reporter.reporting.periods import ReportingPeriod


DEFAULT_LOGO_PATH = Path("images/logo.png")
CADENCE_FILTER_ORDER = ["weekly", "monthly", "yearly"]
ENTRY_SORT_ORDER = {"monthly": 0, "weekly": 1, "yearly": 2}


def build_static_report(
    *,
    period: ReportingPeriod,
    summary: dict[str, Any],
    template_path: str | Path,
    styles_path: str | Path,
    script_path: str | Path,
    logo_path: str | Path = DEFAULT_LOGO_PATH,
) -> tuple[str, str]:
    """Build a self-contained HTML report and return the HTML plus content hash."""
    payload = build_report_payload(period=period, summary=summary, logo_path=logo_path)
    html = Path(template_path).read_text(encoding="utf-8")
    html = html.replace("__REPORT_TITLE__", payload["shell"]["title"])
    html = html.replace("__REPORT_PERIOD__", payload["shell"]["subtitle"])
    html = html.replace("__BRAND_LOGO__", str(payload["shell"]["logo_markup"]))
    html = html.replace("__REPORT_DATA__", json.dumps(payload, sort_keys=True))
    html = html.replace("__REPORT_STYLES__", Path(styles_path).read_text(encoding="utf-8"))
    html = html.replace("__REPORT_SCRIPT__", Path(script_path).read_text(encoding="utf-8"))
    content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
    return html, content_hash


def build_static_index(
    *,
    catalog: dict[str, Any],
    template_path: str | Path,
    styles_path: str | Path,
    script_path: str | Path,
    logo_path: str | Path = DEFAULT_LOGO_PATH,
) -> tuple[str, str]:
    """Build the self-contained report index."""
    shell = build_report_shell(
        page_kind="index",
        title="DMARC Report Library",
        subtitle="Filter the available report set by cadence and calendar slice.",
        logo_path=logo_path,
    )
    payload = {
        "shell": shell,
        "catalog": catalog,
    }
    html = Path(template_path).read_text(encoding="utf-8")
    html = html.replace("__INDEX_TITLE__", shell["title"])
    html = html.replace("__INDEX_SUBTITLE__", shell["subtitle"])
    html = html.replace("__BRAND_LOGO__", str(shell["logo_markup"]))
    html = html.replace("__INDEX_DATA__", json.dumps(payload, sort_keys=True))
    html = html.replace("__REPORT_STYLES__", Path(styles_path).read_text(encoding="utf-8"))
    html = html.replace("__INDEX_SCRIPT__", Path(script_path).read_text(encoding="utf-8"))
    content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
    return html, content_hash


def build_report_payload(
    *,
    period: ReportingPeriod,
    summary: dict[str, Any],
    logo_path: str | Path = DEFAULT_LOGO_PATH,
) -> dict[str, Any]:
    title = _display_title(period)
    subtitle = f"{period.period_start.isoformat()} to {period.period_end.isoformat()}"
    filters = {
        "reporters": _filter_options(summary.get("top_reporters", [])),
        "compliance_categories": _ordered_options(
            _filter_options(summary.get("compliance_counts", {}).keys()),
            ["compliant", "non_compliant"],
        ),
        "dispositions": _ordered_options(
            _filter_options(summary.get("disposition_counts", {}).keys()),
            ["none", "quarantine", "reject"],
        ),
    }
    return {
        "shell": build_report_shell(
            page_kind="report",
            title=title,
            subtitle=subtitle,
            logo_path=logo_path,
        ),
        "period": {
            "period_id": period.period_id,
            "period_type": period.period_type,
            "period_start": period.period_start.isoformat(),
            "period_end": period.period_end.isoformat(),
            "calendar_rule": period.calendar_rule,
            "completeness_status": period.completeness_status,
            "refresh_status": period.refresh_status,
            "last_change_reason": period.last_change_reason,
        },
        "summary": summary,
        "report_experience": _build_report_experience(summary, filters=filters),
    }


def build_report_shell(
    *,
    page_kind: str,
    title: str,
    subtitle: str,
    logo_path: str | Path = DEFAULT_LOGO_PATH,
) -> dict[str, str]:
    logo_markup, logo_mode = _load_logo_markup(logo_path)
    return {
        "page_kind": page_kind,
        "theme_name": "dark",
        "brand_name": "Logo",
        "title": title,
        "subtitle": subtitle,
        "logo_markup": logo_markup,
        "logo_mode": logo_mode,
    }


def build_report_sidebar_state(*, filters: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "layout": {
            "sidebar_position": "left",
            "sidebar_scroll": "independent",
            "main_scroll": "independent",
        },
        "sidebar": {
            "title": "Interactive Filters",
            "filter_groups": [
                _filter_group("reporters", "Reporters", filters.get("reporters", [])),
                _filter_group(
                    "compliance",
                    "Compliance",
                    filters.get("compliance_categories", []),
                ),
                _filter_group("dispositions", "Disposition", filters.get("dispositions", [])),
            ],
        },
        "scroll_preservation": {
            "strategy": "restore-main-scroll",
            "target_container": "main-pane-scroll",
            "threshold_px": 96,
        },
    }


def build_report_library_entry(
    *,
    period: ReportingPeriod,
    output_path: str | Path,
    reports_dir: str | Path,
    content_hash: str,
    build_status: str,
    generated_at: str,
) -> dict[str, Any]:
    output = Path(output_path)
    relative_path = output.relative_to(Path(reports_dir)).as_posix()
    report_year, report_month, report_week = _calendar_dimensions(period)
    return {
        "period_id": period.period_id,
        "cadence": period.period_type,
        "report_year": report_year,
        "report_month": report_month,
        "report_week": report_week,
        "period_start": period.period_start.isoformat(),
        "period_end": period.period_end.isoformat(),
        "display_title": _display_title(period),
        "period_label": _period_label(period),
        "relative_path": relative_path,
        "output_path": str(output),
        "build_status": build_status,
        "content_hash": content_hash,
        "generated_at": generated_at,
    }


def build_report_library_catalog(entries: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_entries = [dict(entry) for entry in entries if entry.get("relative_path")]
    normalized_entries.sort(key=_catalog_entry_sort_key, reverse=True)
    return {
        "entries": normalized_entries,
        "filters": {
            "cadence": _ordered_available_cadences(normalized_entries),
            "years": _sorted_unique(normalized_entries, "report_year"),
            "months": _sorted_unique(
                [entry for entry in normalized_entries if entry.get("cadence") == "monthly"],
                "report_month",
            ),
            "weeks": _sorted_unique(
                [entry for entry in normalized_entries if entry.get("cadence") == "weekly"],
                "report_week",
            ),
        },
        "initial_state": {
            "selected_cadence": [],
            "selected_years": [],
            "selected_months": [],
            "selected_weeks": [],
            "search_query": "",
        },
    }


def _display_title(period: ReportingPeriod) -> str:
    label = {
        "weekly": "Weekly",
        "monthly": "Monthly",
        "yearly": "Yearly",
    }.get(period.period_type, period.period_type.title())
    return f"{label} DMARC Report"


def _period_label(period: ReportingPeriod) -> str:
    if period.period_type == "weekly":
        iso_year, iso_week, _ = period.period_start.isocalendar()
        return f"Week {iso_week}, {iso_year}"
    if period.period_type == "monthly":
        return period.period_start.strftime("%B %Y")
    return f"Calendar Year {period.period_start.year}"


def _calendar_dimensions(period: ReportingPeriod) -> tuple[int, int | None, int | None]:
    if period.period_type == "weekly":
        iso_year, iso_week, _ = period.period_start.isocalendar()
        return iso_year, period.period_start.month, iso_week
    if period.period_type == "monthly":
        return period.period_start.year, period.period_start.month, None
    return period.period_start.year, None, None


def _filter_options(values: list[tuple[str, int]] | Iterable[str]) -> list[str]:
    if isinstance(values, list):
        return [str(item[0]) for item in values]
    return [str(value) for value in values]


def _build_report_experience(summary: dict[str, Any], *, filters: dict[str, list[str]]) -> dict[str, Any]:
    records = [dict(record) for record in summary.get("records", [])]
    detail_rows = sorted(
        records,
        key=lambda record: (
            0 if record.get("compliance_category") == "non_compliant" else 1,
            -int(record.get("count", 0)),
            str(record.get("reporter", "")),
            str(record.get("source_ip", "")),
        ),
    )
    sidebar_state = build_report_sidebar_state(filters=filters)
    return {
        "version": "navigation-v3",
        "default_view": "overview",
        "available_views": ["overview", "reporters", "sources", "compliance", "details"],
        "detail_mode": "collapsed",
        "top_results_visible_limit": 5,
        "filters": filters,
        "layout": sidebar_state["layout"],
        "sidebar": sidebar_state["sidebar"],
        "scroll_preservation": sidebar_state["scroll_preservation"],
        "initial_state": {
            "active_view": "overview",
            "selected_reporters": [],
            "selected_compliance_categories": [],
            "selected_dispositions": [],
            "search_query": "",
            "detail_expanded": False,
        },
        "detail_visibility": {
            "initial_row_limit": 10,
            "expand_label": "Show full detail table",
            "collapse_label": "Show fewer detail rows",
        },
        "filterable_views": {
            "overview": {
                "top_results": _top_results_for(summary, "reporters") + _top_results_for(summary, "sources"),
                "detail_rows": detail_rows,
            },
            "reporters": {
                "options": filters["reporters"],
                "top_results": _top_results_for(summary, "reporters"),
                "detail_rows": _ordered_rows(detail_rows, filters["reporters"], key="reporter"),
            },
            "sources": {
                "options": _filter_options(summary.get("top_source_ips", [])),
                "top_results": _top_results_for(summary, "sources"),
                "detail_rows": _ordered_rows(
                    detail_rows,
                    _filter_options(summary.get("top_source_ips", [])),
                    key="source_ip",
                ),
            },
            "compliance": {
                "options": filters["compliance_categories"],
                "top_results": _top_results_for(summary, "compliance"),
                "detail_rows": [
                    row for row in detail_rows if row.get("compliance_category") == "non_compliant"
                ]
                + [row for row in detail_rows if row.get("compliance_category") == "compliant"],
            },
            "disposition": {
                "options": filters["dispositions"],
                "top_results": _top_results_for(summary, "disposition"),
                "detail_rows": _ordered_rows(detail_rows, filters["dispositions"], key="disposition"),
            },
        },
        "status_indicators": {
            "partial_data": bool(summary.get("partial_data")),
            "partial_data_reasons": list(summary.get("partial_data_reasons", [])),
        },
    }


def _load_logo_markup(logo_path: str | Path) -> tuple[str, str]:
    path = Path(logo_path)
    if path.exists():
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        mime_type = _mime_type_for_logo(path)
        return (
            (
                '<img class="brand-image" '
                f'src="data:{mime_type};base64,{encoded}" '
                'alt="Logo">'
            ),
            "embedded-image",
        )
    return (
        (
            '<div class="brand-mark brand-mark-fallback" role="img" aria-label="Logo">'
            '<span class="brand-mark-fallback__mark">Logo</span>'
            "</div>"
        ),
        "fallback-mark",
    )


def _mime_type_for_logo(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".svg":
        return "image/svg+xml"
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "application/octet-stream"


def _filter_group(group_id: str, label: str, options: list[str]) -> dict[str, Any]:
    return {
        "id": group_id,
        "label": label,
        "options": list(options),
    }


def _top_results_for(summary: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return list(summary.get("top_results", {}).get(key, {}).get("items", []))


def _ordered_rows(rows: list[dict[str, Any]], options: list[str], *, key: str) -> list[dict[str, Any]]:
    option_order = {value: index for index, value in enumerate(options)}
    return sorted(
        rows,
        key=lambda row: (
            option_order.get(str(row.get(key)), len(option_order)),
            -int(row.get("count", 0)),
            str(row.get("source_ip", "")),
        ),
    )


def _ordered_options(values: list[str], preferred_order: list[str]) -> list[str]:
    order = {value: index for index, value in enumerate(preferred_order)}
    return sorted(values, key=lambda value: (order.get(value, len(order)), value))


def _ordered_available_cadences(entries: list[dict[str, Any]]) -> list[str]:
    available = {str(entry["cadence"]) for entry in entries if entry.get("cadence")}
    return [cadence for cadence in CADENCE_FILTER_ORDER if cadence in available]


def _sorted_unique(entries: list[dict[str, Any]], key: str) -> list[int]:
    values = {int(entry[key]) for entry in entries if entry.get(key) is not None}
    return sorted(values)


def _catalog_entry_sort_key(entry: dict[str, Any]) -> tuple[int, int, int, int, str]:
    return (
        str(entry.get("period_end") or ""),
        str(entry.get("period_start") or ""),
        str(entry.get("period_label") or ""),
    )

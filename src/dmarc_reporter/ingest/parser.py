"""Aggregate DMARC XML parsing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    from defusedxml import ElementTree
except ModuleNotFoundError:  # pragma: no cover - exercised only in lean local envs
    from xml.etree import ElementTree  # type: ignore[no-redef]


@dataclass
class ParsedAggregateReport:
    """Structured aggregate DMARC report data."""

    report_id: str
    org_name: str
    date_begin: str
    date_end: str
    records: list[dict[str, Any]]
    policy: dict[str, Any]


def parse_aggregate_report(xml_payload: bytes) -> ParsedAggregateReport:
    """Parse an aggregate DMARC report XML payload."""
    root = ElementTree.fromstring(xml_payload)

    report_metadata = root.find("report_metadata")
    date_range = report_metadata.find("date_range") if report_metadata is not None else None
    policy_published = root.find("policy_published")

    if report_metadata is None or date_range is None or policy_published is None:
        raise ValueError("DMARC report is missing required metadata sections")

    records: list[dict[str, Any]] = []
    for index, record in enumerate(root.findall("record")):
        row = record.find("row")
        identifiers = record.find("identifiers")
        auth_results = record.find("auth_results")
        policy_evaluated = row.find("policy_evaluated") if row is not None else None
        dkim_auth = auth_results.find("dkim") if auth_results is not None else None
        spf_auth = auth_results.find("spf") if auth_results is not None else None

        if row is None or identifiers is None or policy_evaluated is None:
            raise ValueError(f"DMARC record {index} is incomplete")

        records.append(
            {
                "source_ip": _text(row, "source_ip"),
                "count": int(_text(row, "count")),
                "header_from": _text(identifiers, "header_from"),
                "envelope_from": _optional_text(identifiers, "envelope_from"),
                "envelope_to": _optional_text(identifiers, "envelope_to"),
                "dkim_result": _optional_text(dkim_auth, "result") or _text(policy_evaluated, "dkim"),
                "spf_result": _optional_text(spf_auth, "result") or _text(policy_evaluated, "spf"),
                "disposition": _text(policy_evaluated, "disposition"),
                "alignment_dkim": _text(policy_evaluated, "dkim") == "pass",
                "alignment_spf": _text(policy_evaluated, "spf") == "pass",
            }
        )

    return ParsedAggregateReport(
        report_id=_text(report_metadata, "report_id"),
        org_name=_text(report_metadata, "org_name"),
        date_begin=_epoch_to_iso(_text(date_range, "begin")),
        date_end=_epoch_to_iso(_text(date_range, "end")),
        records=records,
        policy={
            "p": _text(policy_published, "p"),
            "sp": _optional_text(policy_published, "sp"),
            "pct": int(_optional_text(policy_published, "pct") or 100),
            "domain": _text(policy_published, "domain"),
        },
    )


def _text(parent: ElementTree.Element | None, tag: str) -> str:
    if parent is None:
        raise ValueError(f"Missing required parent for tag {tag}")
    child = parent.find(tag)
    if child is None or child.text is None:
        raise ValueError(f"Missing required tag {tag}")
    return child.text.strip()


def _optional_text(parent: ElementTree.Element | None, tag: str) -> str | None:
    if parent is None:
        return None
    child = parent.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _epoch_to_iso(value: str) -> str:
    return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()

"""Aggregate reporting queries and summaries."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from dmarc_reporter.storage.repository import Repository


def fetch_period_records(
    repository: Repository,
    *,
    period_start: datetime,
    period_end: datetime,
) -> list[dict[str, Any]]:
    """Fetch normalized records for a reporting period."""
    rows = repository.connection.execute(
        """
        WITH filtered_records AS (
            SELECT
                record_id,
                artifact_id,
                source_ip,
                count,
                header_from,
                envelope_from,
                envelope_to,
                dkim_result,
                spf_result,
                disposition,
                alignment_dkim,
                alignment_spf,
                policy_p,
                policy_sp,
                policy_pct,
                coverage_date_begin,
                coverage_date_end
            FROM normalized_records INDEXED BY idx_records_coverage
            WHERE coverage_date_begin >= ?
              AND coverage_date_end <= ?
        )
        SELECT
            nr.record_id,
            nr.source_ip,
            nr.count,
            nr.header_from,
            nr.envelope_from,
            nr.envelope_to,
            nr.dkim_result,
            nr.spf_result,
            nr.disposition,
            nr.alignment_dkim,
            nr.alignment_spf,
            nr.policy_p,
            nr.policy_sp,
            nr.policy_pct,
            nr.coverage_date_begin,
            nr.coverage_date_end,
            sra.org_name,
            sra.report_id
        FROM filtered_records nr
        JOIN source_report_artifacts sra ON sra.artifact_id = nr.artifact_id
        ORDER BY nr.coverage_date_begin, nr.record_id
        """,
        (period_start.isoformat(), period_end.isoformat()),
    ).fetchall()
    return [dict(row) for row in rows]


def summarize_period(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a period's normalized records for report rendering."""
    total_messages = sum(int(record["count"]) for record in records)
    disposition_counts = Counter()
    compliance_counts = Counter()
    dkim_alignment_counts = Counter()
    spf_alignment_counts = Counter()
    source_ip_counts = Counter()
    reporter_counts = Counter()
    reporter_non_compliant_counts = Counter()
    source_compliant_counts = Counter()
    source_non_compliant_counts = Counter()
    domain_counts = Counter()
    reporter_record_counts = Counter()
    source_record_counts = Counter()
    compliance_record_counts = Counter()
    disposition_record_counts = Counter()
    enriched_records: list[dict[str, Any]] = []
    partial_data_reasons = sorted(
        {
            str(record["partial_reason"])
            for record in records
            if record.get("partial_reason")
        }
    )

    for record in records:
        enriched = _enrich_record(record)
        enriched_records.append(enriched)
        count = int(enriched["count"])
        reporter = str(enriched["reporter"])
        source_ip = str(enriched["source_ip"])
        compliance = str(enriched["compliance_category"])
        disposition = str(enriched["disposition"])
        disposition_counts[disposition] += count
        compliance_counts[compliance] += count
        dkim_alignment_counts["pass" if enriched["alignment_dkim"] else "fail"] += count
        spf_alignment_counts["pass" if enriched["alignment_spf"] else "fail"] += count
        source_ip_counts[source_ip] += count
        reporter_counts[reporter] += count
        domain_counts[str(enriched["header_from"])] += count
        reporter_record_counts[reporter] += 1
        source_record_counts[source_ip] += 1
        compliance_record_counts[compliance] += 1
        disposition_record_counts[disposition] += 1
        if compliance == "compliant":
            source_compliant_counts[source_ip] += count
        else:
            reporter_non_compliant_counts[reporter] += count
            source_non_compliant_counts[source_ip] += count

    enriched_records.sort(
        key=lambda record: (
            0 if record["compliance_category"] == "non_compliant" else 1,
            -int(record["count"]),
            str(record["reporter"]),
            str(record["source_ip"]),
        )
    )

    return {
        "total_messages": total_messages,
        "record_count": len(records),
        "disposition_counts": dict(disposition_counts),
        "compliance_counts": dict(compliance_counts),
        "dkim_alignment_counts": dict(dkim_alignment_counts),
        "spf_alignment_counts": dict(spf_alignment_counts),
        "top_source_ips": source_ip_counts.most_common(10),
        "top_domains": domain_counts.most_common(10),
        "top_reporters": reporter_counts.most_common(10),
        "top_reporters_non_compliant": reporter_non_compliant_counts.most_common(10),
        "top_sources_compliant": source_compliant_counts.most_common(10),
        "top_sources_non_compliant": source_non_compliant_counts.most_common(10),
        "top_results": {
            "reporters": _top_results(
                reporter_counts,
                record_counts=reporter_record_counts,
                secondary_counts=reporter_non_compliant_counts,
                segment_type="reporter",
            ),
            "sources": _top_results(
                source_ip_counts,
                record_counts=source_record_counts,
                secondary_counts=source_non_compliant_counts,
                segment_type="source",
            ),
            "compliance": _top_results(
                compliance_counts,
                record_counts=compliance_record_counts,
                secondary_counts=Counter({"non_compliant": compliance_counts.get("non_compliant", 0)}),
                segment_type="compliance",
            ),
            "disposition": _top_results(
                disposition_counts,
                record_counts=disposition_record_counts,
                secondary_counts=Counter(
                    {
                        "reject": disposition_counts.get("reject", 0),
                        "quarantine": disposition_counts.get("quarantine", 0),
                    }
                ),
                segment_type="disposition",
            ),
        },
        "insight_sections": [
            {"id": "overview", "title": "Overview", "kind": "summary"},
            {"id": "reporters", "title": "Reporter View", "kind": "reporter"},
            {"id": "sources", "title": "Source View", "kind": "source"},
            {"id": "compliance", "title": "Compliance View", "kind": "compliance"},
            {"id": "details", "title": "Detail View", "kind": "detail"},
        ],
        "records": enriched_records,
        "partial_data": bool(partial_data_reasons),
        "partial_data_reasons": partial_data_reasons,
    }


def _compliance_category(record: dict[str, Any]) -> str:
    return "compliant" if record.get("alignment_dkim") or record.get("alignment_spf") else "non_compliant"


def _enrich_record(record: dict[str, Any]) -> dict[str, Any]:
    compliance = _compliance_category(record)
    return {
        **record,
        "reporter": str(record.get("org_name") or "Unknown Reporter"),
        "compliance_category": compliance,
        "disposition_label": _display_label(str(record["disposition"]), segment_type="disposition"),
    }


def _top_results(
    counts: Counter[str],
    *,
    record_counts: Counter[str],
    segment_type: str,
    secondary_counts: Counter[str] | None = None,
    default_visible_count: int = 5,
) -> dict[str, Any]:
    secondary = secondary_counts or Counter()
    ordered = sorted(
        counts.items(),
        key=lambda item: (-secondary.get(item[0], 0), -item[1], item[0]),
    )
    items = [
        {
            "segment_type": segment_type,
            "segment_key": key,
            "display_label": _display_label(key, segment_type=segment_type),
            "message_count": message_count,
            "record_count": int(record_counts.get(key, 0)),
            "risk_weight": secondary.get(key, message_count),
        }
        for key, message_count in ordered[:10]
    ]
    return {
        "collection_name": f"top_{segment_type}",
        "segment_type": segment_type,
        "items": items,
        "total_available": len(counts),
        "default_visible_count": min(default_visible_count, len(items)),
    }


def _display_label(value: str, *, segment_type: str) -> str:
    if segment_type in {"compliance", "disposition"}:
        return value.replace("_", " ").title()
    return value

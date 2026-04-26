from __future__ import annotations

from dmarc_reporter.reporting.aggregations import summarize_period


def test_summarize_period_rolls_up_key_metrics() -> None:
    records = [
        {
            "source_ip": "203.0.113.10",
            "count": 40,
            "header_from": "example.com",
            "disposition": "none",
            "alignment_dkim": 1,
            "alignment_spf": 1,
        },
        {
            "source_ip": "203.0.113.11",
            "count": 5,
            "header_from": "example.net",
            "disposition": "quarantine",
            "alignment_dkim": 0,
            "alignment_spf": 1,
        },
    ]

    summary = summarize_period(records)

    assert summary["total_messages"] == 45
    assert summary["record_count"] == 2
    assert summary["compliance_counts"]["compliant"] == 45
    assert summary["disposition_counts"]["none"] == 40
    assert summary["disposition_counts"]["quarantine"] == 5
    assert summary["dkim_alignment_counts"]["pass"] == 40
    assert summary["dkim_alignment_counts"]["fail"] == 5
    assert summary["top_source_ips"][0] == ("203.0.113.10", 40)


def test_summarize_period_preserves_partial_data_reasons_for_reporting_retries() -> None:
    records = [
        {
            "source_ip": "203.0.113.10",
            "count": 10,
            "header_from": "example.com",
            "disposition": "none",
            "alignment_dkim": 1,
            "alignment_spf": 1,
            "partial_reason": "1 malformed source report was skipped",
        },
        {
            "source_ip": "203.0.113.10",
            "count": 5,
            "header_from": "example.com",
            "disposition": "none",
            "alignment_dkim": 1,
            "alignment_spf": 1,
            "partial_reason": "1 malformed source report was skipped",
        },
    ]

    summary = summarize_period(records)

    assert summary["partial_data"] is True
    assert summary["partial_data_reasons"] == ["1 malformed source report was skipped"]


def test_summarize_period_ranks_top_results_by_non_compliant_risk() -> None:
    records = [
        {
            "org_name": "High Risk Reporter",
            "source_ip": "203.0.113.20",
            "count": 20,
            "header_from": "example.com",
            "disposition": "reject",
            "alignment_dkim": 0,
            "alignment_spf": 0,
        },
        {
            "org_name": "Lower Risk Reporter",
            "source_ip": "203.0.113.30",
            "count": 50,
            "header_from": "example.com",
            "disposition": "none",
            "alignment_dkim": 1,
            "alignment_spf": 1,
        },
        {
            "org_name": "Lower Risk Reporter",
            "source_ip": "203.0.113.30",
            "count": 5,
            "header_from": "example.net",
            "disposition": "quarantine",
            "alignment_dkim": 0,
            "alignment_spf": 0,
        },
    ]

    summary = summarize_period(records)

    assert summary["compliance_counts"] == {"non_compliant": 25, "compliant": 50}
    assert summary["top_results"]["reporters"]["items"][0]["display_label"] == "High Risk Reporter"
    assert summary["top_results"]["reporters"]["items"][0]["risk_weight"] == 20
    assert summary["top_results"]["sources"]["items"][0]["segment_key"] == "203.0.113.20"
    assert summary["top_results"]["compliance"]["items"][0]["segment_key"] == "non_compliant"


def test_summarize_period_limits_default_visible_top_results_and_retains_detail_records() -> None:
    records = [
        {
            "org_name": f"Reporter {index}",
            "source_ip": f"203.0.113.{index}",
            "count": 10 + index,
            "header_from": f"example{index}.com",
            "disposition": "none" if index % 2 == 0 else "reject",
            "alignment_dkim": 1 if index % 2 == 0 else 0,
            "alignment_spf": 1 if index % 2 == 0 else 0,
        }
        for index in range(1, 9)
    ]

    summary = summarize_period(records)

    assert summary["top_results"]["reporters"]["default_visible_count"] == 5
    assert summary["top_results"]["reporters"]["total_available"] == 8
    assert len(summary["top_results"]["reporters"]["items"]) == 8
    assert len(summary["records"]) == 8

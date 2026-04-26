from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import json
import re

from dmarc_reporter.config import AppConfig
from dmarc_reporter.reporting.manifest import generate_reports
from dmarc_reporter.storage.repository import ProcessingRun, Repository


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        gmail_client_secret=tmp_path / "client.json",
        gmail_token_path=tmp_path / "token.json",
        data_dir=tmp_path,
        reports_dir=tmp_path / "reports",
        database_path=tmp_path / "dmarc.sqlite",
    )


def _extract_payload(html: str) -> dict[str, object]:
    match = re.search(
        r'<script id="report-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def _seed_period_record(
    repo: Repository,
    *,
    artifact_id: str,
    record_id: str,
    count: int,
    org_name: str = "Example Mail",
    source_ip: str = "203.0.113.10",
    header_from: str = "example.com",
    disposition: str = "none",
    alignment_dkim: int = 1,
    alignment_spf: int = 1,
) -> None:
    repo.insert_source_report_artifact(
        {
            "artifact_id": artifact_id,
            "gmail_message_id": f"msg-{artifact_id}",
            "attachment_id": f"att-{artifact_id}",
            "filename": "aggregate.xml",
            "media_type": "application/xml",
            "content_encoding": "xml",
            "sha256": artifact_id * 4,
            "report_id": f"report-{artifact_id}",
            "org_name": org_name,
            "date_begin": "2024-04-15T00:00:00+00:00",
            "date_end": "2024-04-15T23:59:59+00:00",
            "parse_status": "parsed",
            "parse_error": None,
            "ingested_run_id": "run-1",
        }
    )
    repo.insert_normalized_records(
        [
            {
                "record_id": record_id,
                "artifact_id": artifact_id,
                "source_ip": source_ip,
                "count": count,
                "header_from": header_from,
                "envelope_from": "mail.example.com",
                "envelope_to": None,
                "dkim_result": "pass" if alignment_dkim else "fail",
                "spf_result": "pass" if alignment_spf else "fail",
                "disposition": disposition,
                "alignment_dkim": alignment_dkim,
                "alignment_spf": alignment_spf,
                "policy_p": "quarantine",
                "policy_sp": "quarantine",
                "policy_pct": 100,
                "coverage_date_begin": "2024-04-15T00:00:00+00:00",
                "coverage_date_end": "2024-04-15T23:59:59+00:00",
                "dedupe_key": f"dedupe-{record_id}",
            }
        ]
    )


def test_report_generation_and_regeneration(tmp_path: Path, capsys) -> None:
    repo = Repository(tmp_path / "dmarc.sqlite")
    repo.create_processing_run(
        ProcessingRun(
            run_id="run-1",
            started_at=datetime(2024, 4, 22, tzinfo=timezone.utc).isoformat(),
            mode="normal",
        )
    )
    repo.upsert_mailbox_message(
        gmail_message_id="msg-artifact-a",
        thread_id="thread-a",
        label_snapshot='["Label_42"]',
        received_at="2024-04-16T00:00:00+00:00",
        is_unread_at_fetch=False,
    )
    _seed_period_record(repo, artifact_id="artifact-a", record_id="record-a", count=40)

    result = generate_reports(
        config=_config(tmp_path),
        repository=repo,
        run_id="run-1",
        as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    first_output = capsys.readouterr().out

    assert result["generated"] == 3
    assert "writing_new_report period_id=weekly-2024-W16" in first_output
    assert "wrote_report period_id=weekly-2024-W16" in first_output
    weekly_report = tmp_path / "reports" / "weekly" / "weekly-2024-W16.html"
    assert weekly_report.exists()
    first_html = weekly_report.read_text(encoding="utf-8")
    assert "Weekly DMARC Report" in first_html
    first_period = repo.connection.execute(
        "SELECT refresh_status FROM reporting_periods WHERE period_id = ?",
        ("weekly-2024-W16",),
    ).fetchone()
    assert first_period["refresh_status"] == "current"

    repo.upsert_mailbox_message(
        gmail_message_id="msg-artifact-b",
        thread_id="thread-b",
        label_snapshot='["Label_42"]',
        received_at="2024-04-16T01:00:00+00:00",
        is_unread_at_fetch=False,
    )
    repo.create_processing_run(
        ProcessingRun(
            run_id="run-2",
            started_at=datetime(2024, 4, 22, 1, tzinfo=timezone.utc).isoformat(),
            mode="normal",
        )
    )
    _seed_period_record(repo, artifact_id="artifact-b", record_id="record-b", count=10)

    rerun = generate_reports(
        config=_config(tmp_path),
        repository=repo,
        run_id="run-2",
        as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    rerun_output = capsys.readouterr().out
    second_html = weekly_report.read_text(encoding="utf-8")
    assert rerun["regenerated"] >= 1
    assert "rewriting_report period_id=weekly-2024-W16" in rerun_output
    assert "wrote_report period_id=weekly-2024-W16" in rerun_output
    assert first_html != second_html
    weekly_period = repo.connection.execute(
        "SELECT completeness_status, refresh_status, last_change_reason FROM reporting_periods WHERE period_id = ?",
        ("weekly-2024-W16",),
    ).fetchone()
    assert weekly_period["completeness_status"] == "complete"
    assert weekly_period["refresh_status"] == "current"
    assert weekly_period["last_change_reason"] == "late_data"
    regeneration_event = repo.connection.execute(
        "SELECT event_type, period_ref FROM processing_run_events WHERE event_type = 'report_regenerated'"
    ).fetchone()
    assert regeneration_event["period_ref"] == "weekly-2024-W16"
    repo.close()


def test_report_generation_surfaces_richer_first_load_content(tmp_path: Path, capsys) -> None:
    repo = Repository(tmp_path / "dmarc.sqlite")
    repo.create_processing_run(
        ProcessingRun(
            run_id="run-1",
            started_at=datetime(2024, 4, 22, tzinfo=timezone.utc).isoformat(),
            mode="normal",
        )
    )
    repo.upsert_mailbox_message(
        gmail_message_id="msg-artifact-a",
        thread_id="thread-a",
        label_snapshot='["Label_42"]',
        received_at="2024-04-16T00:00:00+00:00",
        is_unread_at_fetch=False,
    )
    repo.upsert_mailbox_message(
        gmail_message_id="msg-artifact-b",
        thread_id="thread-b",
        label_snapshot='["Label_42"]',
        received_at="2024-04-16T01:00:00+00:00",
        is_unread_at_fetch=False,
    )
    _seed_period_record(repo, artifact_id="artifact-a", record_id="record-a", count=40, org_name="Example Mail")
    _seed_period_record(
        repo,
        artifact_id="artifact-b",
        record_id="record-b",
        count=12,
        org_name="Spoof Watch",
        source_ip="203.0.113.20",
        disposition="reject",
        alignment_dkim=0,
        alignment_spf=0,
    )

    result = generate_reports(
        config=_config(tmp_path),
        repository=repo,
        run_id="run-1",
        as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    assert result["generated"] == 3
    weekly_html = (tmp_path / "reports" / "weekly" / "weekly-2024-W16.html").read_text(encoding="utf-8")
    payload = _extract_payload(weekly_html)

    assert "Top Reporters" in weekly_html
    assert "Compliance Categories" in weekly_html
    assert "Show full detail table" in weekly_html
    assert payload["summary"]["top_results"]["reporters"]["items"][0]["segment_key"] == "Spoof Watch"
    assert payload["summary"]["compliance_counts"]["non_compliant"] == 12
    assert payload["report_experience"]["detail_visibility"]["initial_row_limit"] == 10
    assert payload["shell"]["theme_name"] == "dark"
    assert payload["report_experience"]["layout"]["sidebar_position"] == "left"
    assert "filters-sidebar" in weekly_html
    assert "Logo" in weekly_html
    repo.close()


def test_report_generation_embeds_filterable_report_slices(tmp_path: Path, capsys) -> None:
    repo = Repository(tmp_path / "dmarc.sqlite")
    repo.create_processing_run(
        ProcessingRun(
            run_id="run-1",
            started_at=datetime(2024, 4, 22, tzinfo=timezone.utc).isoformat(),
            mode="normal",
        )
    )
    for artifact_id, org_name, source_ip, disposition, alignment in [
        ("artifact-a", "Example Mail", "203.0.113.10", "none", 1),
        ("artifact-b", "Spoof Watch", "203.0.113.20", "reject", 0),
        ("artifact-c", "Mailbox Filter", "203.0.113.30", "quarantine", 0),
    ]:
        repo.upsert_mailbox_message(
            gmail_message_id=f"msg-{artifact_id}",
            thread_id=f"thread-{artifact_id}",
            label_snapshot='["Label_42"]',
            received_at="2024-04-16T00:00:00+00:00",
            is_unread_at_fetch=False,
        )
        _seed_period_record(
            repo,
            artifact_id=artifact_id,
            record_id=f"record-{artifact_id}",
            count=15,
            org_name=org_name,
            source_ip=source_ip,
            disposition=disposition,
            alignment_dkim=alignment,
            alignment_spf=alignment,
        )

    generate_reports(
        config=_config(tmp_path),
        repository=repo,
        run_id="run-1",
        as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    weekly_html = (tmp_path / "reports" / "weekly" / "weekly-2024-W16.html").read_text(encoding="utf-8")
    payload = _extract_payload(weekly_html)

    assert payload["report_experience"]["filters"]["reporters"] == [
        "Example Mail",
        "Spoof Watch",
        "Mailbox Filter",
    ]
    assert payload["report_experience"]["filterable_views"]["reporters"]["detail_rows"][0]["reporter"] == "Example Mail"
    assert payload["report_experience"]["filterable_views"]["compliance"]["options"] == [
        "compliant",
        "non_compliant",
    ]
    assert payload["report_experience"]["filterable_views"]["disposition"]["options"] == [
        "none",
        "quarantine",
        "reject",
    ]
    assert payload["report_experience"]["detail_visibility"]["expand_label"] == "Show full detail table"
    assert payload["report_experience"]["scroll_preservation"]["target_container"] == "main-pane-scroll"
    repo.close()


def test_report_generation_publishes_index_and_catalog_entries(tmp_path: Path, capsys) -> None:
    repo = Repository(tmp_path / "dmarc.sqlite")
    repo.create_processing_run(
        ProcessingRun(
            run_id="run-1",
            started_at=datetime(2024, 4, 22, tzinfo=timezone.utc).isoformat(),
            mode="build-reports",
        )
    )
    repo.upsert_mailbox_message(
        gmail_message_id="msg-artifact-a",
        thread_id="thread-a",
        label_snapshot='["Label_42"]',
        received_at="2024-04-16T00:00:00+00:00",
        is_unread_at_fetch=False,
    )
    _seed_period_record(repo, artifact_id="artifact-a", record_id="record-a", count=40)

    result = generate_reports(
        config=_config(tmp_path),
        repository=repo,
        run_id="run-1",
        as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    assert result["generated"] == 3
    index_path = tmp_path / "reports" / "index.html"
    assert index_path.exists()
    index_html = index_path.read_text(encoding="utf-8")
    assert "DMARC Report Library" in index_html
    assert "weekly/weekly-2024-W16.html" in index_html
    assert (tmp_path / "reports" / "images" / "logo.png").exists()
    catalog_rows = repo.list_report_library_entries()
    assert len(catalog_rows) == 3
    assert any(row["relative_path"] == "weekly/weekly-2024-W16.html" for row in catalog_rows)
    repo.close()


def test_report_generation_skips_unchanged_current_artifacts(tmp_path: Path, capsys) -> None:
    repo = Repository(tmp_path / "dmarc.sqlite")
    repo.create_processing_run(
        ProcessingRun(
            run_id="run-1",
            started_at=datetime(2024, 4, 22, tzinfo=timezone.utc).isoformat(),
            mode="sync",
        )
    )
    repo.upsert_mailbox_message(
        gmail_message_id="msg-artifact-a",
        thread_id="thread-a",
        label_snapshot='["Label_42"]',
        received_at="2024-04-16T00:00:00+00:00",
        is_unread_at_fetch=False,
    )
    _seed_period_record(repo, artifact_id="artifact-a", record_id="record-a", count=40)

    first = generate_reports(
        config=_config(tmp_path),
        repository=repo,
        run_id="run-1",
        as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    assert first["generated"] == 3
    capsys.readouterr()
    weekly_report = tmp_path / "reports" / "weekly" / "weekly-2024-W16.html"
    first_html = weekly_report.read_text(encoding="utf-8")
    first_mtime = weekly_report.stat().st_mtime_ns

    repo.create_processing_run(
        ProcessingRun(
            run_id="run-2",
            started_at=datetime(2024, 4, 23, tzinfo=timezone.utc).isoformat(),
            mode="build-reports",
        )
    )
    second = generate_reports(
        config=_config(tmp_path),
        repository=repo,
        run_id="run-2",
        as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    second_output = capsys.readouterr().out

    assert second["generated"] == 0
    assert second["regenerated"] == 0
    assert second["skipped"] == 3
    assert second["skipped_unchanged"] == 3
    assert "skipped_unchanged period_id=weekly-2024-W16" in second_output
    assert weekly_report.read_text(encoding="utf-8") == first_html
    assert weekly_report.stat().st_mtime_ns == first_mtime
    artifact = repo.get_generated_report_artifact("weekly-2024-W16")
    assert artifact is not None
    assert artifact["build_status"] == "skipped"
    assert second["decisions"][0]["decision"] == "skip_unchanged"
    index_path = tmp_path / "reports" / "index.html"
    assert index_path.exists()
    assert "weekly/weekly-2024-W16.html" in index_path.read_text(encoding="utf-8")
    repo.close()

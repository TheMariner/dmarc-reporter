"""Repository helpers for the DMARC reporter persistence layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any

from dmarc_reporter.storage.schema import initialize_database


def utc_now() -> str:
    """Return a UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProcessingRun:
    run_id: str
    started_at: str
    mode: str
    status: str = "running"
    finished_at: str | None = None
    messages_seen: int = 0
    messages_ingested: int = 0
    messages_restored_unread: int = 0
    artifacts_parsed: int = 0
    duplicates_detected: int = 0
    periods_marked_stale: int = 0
    periods_considered: int = 0
    reports_skipped: int = 0
    follow_up_reporting_needed: int = 0
    reports_generated: int = 0
    reports_regenerated: int = 0
    failures_count: int = 0
    summary_message: str | None = None


class Repository:
    """High-level SQLite repository wrapper."""

    def __init__(self, database_path: str | Path) -> None:
        self._connection = initialize_database(database_path)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        self._connection.close()

    def create_processing_run(self, run: ProcessingRun) -> None:
        payload = asdict(run)
        columns = ", ".join(payload.keys())
        placeholders = ", ".join(f":{key}" for key in payload)
        query = f"INSERT INTO processing_runs ({columns}) VALUES ({placeholders})"
        with self._connection:
            self._connection.execute(query, payload)

    def finish_processing_run(
        self,
        run_id: str,
        *,
        status: str,
        summary_message: str | None = None,
        counters: dict[str, Any] | None = None,
    ) -> None:
        updates: dict[str, Any] = {
            "run_id": run_id,
            "status": status,
            "finished_at": utc_now(),
            "summary_message": summary_message,
        }
        if counters:
            updates.update(counters)

        assignments = ", ".join(f"{key} = :{key}" for key in updates if key != "run_id")
        with self._connection:
            self._connection.execute(
                f"UPDATE processing_runs SET {assignments} WHERE run_id = :run_id",
                updates,
            )

    def upsert_mailbox_message(
        self,
        *,
        gmail_message_id: str,
        thread_id: str,
        label_snapshot: str,
        received_at: str,
        is_unread_at_fetch: bool,
        last_processed_run_id: str | None = None,
        mark_read_status: str = "pending",
        mark_read_error: str | None = None,
        reset_unread_status: str = "not_requested",
        reset_unread_error: str | None = None,
    ) -> None:
        now = utc_now()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO mailbox_messages (
                    gmail_message_id, thread_id, label_snapshot, received_at,
                    is_unread_at_fetch, mark_read_status, mark_read_error,
                    reset_unread_status, reset_unread_error,
                    last_processed_run_id, created_at, updated_at
                ) VALUES (
                    :gmail_message_id, :thread_id, :label_snapshot, :received_at,
                    :is_unread_at_fetch, :mark_read_status, :mark_read_error,
                    :reset_unread_status, :reset_unread_error,
                    :last_processed_run_id, :created_at, :updated_at
                )
                ON CONFLICT(gmail_message_id) DO UPDATE SET
                    thread_id = excluded.thread_id,
                    label_snapshot = excluded.label_snapshot,
                    received_at = excluded.received_at,
                    is_unread_at_fetch = excluded.is_unread_at_fetch,
                    mark_read_status = excluded.mark_read_status,
                    mark_read_error = excluded.mark_read_error,
                    reset_unread_status = excluded.reset_unread_status,
                    reset_unread_error = excluded.reset_unread_error,
                    last_processed_run_id = excluded.last_processed_run_id,
                    updated_at = excluded.updated_at
                """,
                {
                    "gmail_message_id": gmail_message_id,
                    "thread_id": thread_id,
                    "label_snapshot": label_snapshot,
                    "received_at": received_at,
                    "is_unread_at_fetch": int(is_unread_at_fetch),
                    "mark_read_status": mark_read_status,
                    "mark_read_error": mark_read_error,
                    "reset_unread_status": reset_unread_status,
                    "reset_unread_error": reset_unread_error,
                    "last_processed_run_id": last_processed_run_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    def insert_source_report_artifact(self, payload: dict[str, Any]) -> None:
        record = {"created_at": utc_now(), "updated_at": utc_now(), **payload}
        columns = ", ".join(record.keys())
        placeholders = ", ".join(f":{key}" for key in record)
        with self._connection:
            self._connection.execute(
                f"INSERT INTO source_report_artifacts ({columns}) VALUES ({placeholders})",
                record,
            )

    def source_report_exists(self, sha256: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM source_report_artifacts WHERE sha256 = ? LIMIT 1",
            (sha256,),
        ).fetchone()
        return row is not None

    def insert_normalized_records(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        prepared = [{**row, "created_at": utc_now()} for row in rows]
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO normalized_records (
                    record_id, artifact_id, source_ip, count, header_from,
                    envelope_from, envelope_to, dkim_result, spf_result,
                    disposition, alignment_dkim, alignment_spf, policy_p,
                    policy_sp, policy_pct, coverage_date_begin, coverage_date_end,
                    dedupe_key, created_at
                ) VALUES (
                    :record_id, :artifact_id, :source_ip, :count, :header_from,
                    :envelope_from, :envelope_to, :dkim_result, :spf_result,
                    :disposition, :alignment_dkim, :alignment_spf, :policy_p,
                    :policy_sp, :policy_pct, :coverage_date_begin, :coverage_date_end,
                    :dedupe_key, :created_at
                )
                """,
                prepared,
            )

    def upsert_reporting_period(self, payload: dict[str, Any]) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO reporting_periods (
                    period_id, period_type, period_start, period_end,
                    calendar_rule, completeness_status, refresh_status,
                    latest_source_date, last_data_change_at, last_built_at,
                    last_built_run_id, last_change_reason
                ) VALUES (
                    :period_id, :period_type, :period_start, :period_end,
                    :calendar_rule, :completeness_status, :refresh_status,
                    :latest_source_date, :last_data_change_at, :last_built_at,
                    :last_built_run_id, :last_change_reason
                )
                ON CONFLICT(period_id) DO UPDATE SET
                    period_type = excluded.period_type,
                    period_start = excluded.period_start,
                    period_end = excluded.period_end,
                    calendar_rule = excluded.calendar_rule,
                    completeness_status = excluded.completeness_status,
                    refresh_status = excluded.refresh_status,
                    latest_source_date = excluded.latest_source_date,
                    last_data_change_at = excluded.last_data_change_at,
                    last_built_at = excluded.last_built_at,
                    last_built_run_id = excluded.last_built_run_id,
                    last_change_reason = excluded.last_change_reason
                """,
                payload,
            )

    def upsert_generated_report_artifact(self, payload: dict[str, Any]) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO generated_report_artifacts (
                    generated_report_id, period_id, output_path, content_hash,
                    record_count, build_status, partial_data_flag, generated_at,
                    generated_by_run_id, failure_reason
                ) VALUES (
                    :generated_report_id, :period_id, :output_path, :content_hash,
                    :record_count, :build_status, :partial_data_flag, :generated_at,
                    :generated_by_run_id, :failure_reason
                )
                ON CONFLICT(generated_report_id) DO UPDATE SET
                    period_id = excluded.period_id,
                    output_path = excluded.output_path,
                    content_hash = excluded.content_hash,
                    record_count = excluded.record_count,
                    build_status = excluded.build_status,
                    partial_data_flag = excluded.partial_data_flag,
                    generated_at = excluded.generated_at,
                    generated_by_run_id = excluded.generated_by_run_id,
                    failure_reason = excluded.failure_reason
                """,
                payload,
            )

    def get_generated_report_artifact(self, generated_report_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM generated_report_artifacts WHERE generated_report_id = ?",
            (generated_report_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def upsert_report_library_entry(self, payload: dict[str, Any]) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO report_library_entries (
                    period_id, cadence, report_year, report_month, report_week,
                    period_start, period_end, display_title, period_label,
                    relative_path, output_path, build_status, content_hash, generated_at
                ) VALUES (
                    :period_id, :cadence, :report_year, :report_month, :report_week,
                    :period_start, :period_end, :display_title, :period_label,
                    :relative_path, :output_path, :build_status, :content_hash, :generated_at
                )
                ON CONFLICT(period_id) DO UPDATE SET
                    cadence = excluded.cadence,
                    report_year = excluded.report_year,
                    report_month = excluded.report_month,
                    report_week = excluded.report_week,
                    period_start = excluded.period_start,
                    period_end = excluded.period_end,
                    display_title = excluded.display_title,
                    period_label = excluded.period_label,
                    relative_path = excluded.relative_path,
                    output_path = excluded.output_path,
                    build_status = excluded.build_status,
                    content_hash = excluded.content_hash,
                    generated_at = excluded.generated_at
                """,
                payload,
            )

    def list_report_library_entries(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM report_library_entries
            WHERE build_status != 'failed'
            ORDER BY report_year DESC, COALESCE(report_month, 0) DESC, COALESCE(report_week, 0) DESC, cadence
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_reporting_periods_needing_reports(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM reporting_periods
            WHERE completeness_status = 'complete'
              AND refresh_status IN ('pending_initial', 'stale', 'failed')
            ORDER BY period_end, period_id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_complete_reporting_periods(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT *
            FROM reporting_periods
            WHERE completeness_status = 'complete'
            ORDER BY period_end, period_id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def count_reporting_periods_needing_reports(self) -> int:
        row = self._connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM reporting_periods
            WHERE completeness_status = 'complete'
              AND refresh_status IN ('pending_initial', 'stale', 'failed')
            """
        ).fetchone()
        return int(row["count"])

    def get_reporting_period(self, period_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM reporting_periods WHERE period_id = ?",
            (period_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_reporting_period_build_state(self, period_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            """
            SELECT
                rp.period_id,
                rp.refresh_status,
                rp.last_data_change_at,
                rp.last_built_at,
                rp.last_change_reason,
                gra.content_hash,
                gra.build_status,
                gra.generated_at
            FROM reporting_periods rp
            LEFT JOIN generated_report_artifacts gra
              ON gra.period_id = rp.period_id
            WHERE rp.period_id = ?
            """,
            (period_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_processing_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM processing_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def record_event(
        self,
        *,
        event_id: str,
        run_id: str,
        severity: str,
        event_type: str,
        detail: str,
        message_ref: str | None = None,
        artifact_ref: str | None = None,
        period_ref: str | None = None,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO processing_run_events (
                    event_id, run_id, severity, event_type, message_ref,
                    artifact_ref, period_ref, detail, created_at
                ) VALUES (
                    :event_id, :run_id, :severity, :event_type, :message_ref,
                    :artifact_ref, :period_ref, :detail, :created_at
                )
                """,
                {
                    "event_id": event_id,
                    "run_id": run_id,
                    "severity": severity,
                    "event_type": event_type,
                    "message_ref": message_ref,
                    "artifact_ref": artifact_ref,
                    "period_ref": period_ref,
                    "detail": detail,
                    "created_at": utc_now(),
                },
            )

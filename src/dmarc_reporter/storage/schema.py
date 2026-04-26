"""SQLite schema management for the DMARC reporter."""

from __future__ import annotations

from pathlib import Path
import sqlite3


DDL_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS processing_runs (
        run_id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        mode TEXT NOT NULL,
        status TEXT NOT NULL,
        messages_seen INTEGER NOT NULL DEFAULT 0,
        messages_ingested INTEGER NOT NULL DEFAULT 0,
        messages_restored_unread INTEGER NOT NULL DEFAULT 0,
        artifacts_parsed INTEGER NOT NULL DEFAULT 0,
        duplicates_detected INTEGER NOT NULL DEFAULT 0,
        periods_marked_stale INTEGER NOT NULL DEFAULT 0,
        periods_considered INTEGER NOT NULL DEFAULT 0,
        reports_skipped INTEGER NOT NULL DEFAULT 0,
        follow_up_reporting_needed INTEGER NOT NULL DEFAULT 0,
        reports_generated INTEGER NOT NULL DEFAULT 0,
        reports_regenerated INTEGER NOT NULL DEFAULT 0,
        failures_count INTEGER NOT NULL DEFAULT 0,
        summary_message TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS processing_run_events (
        event_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES processing_runs(run_id) ON DELETE CASCADE,
        severity TEXT NOT NULL,
        event_type TEXT NOT NULL,
        message_ref TEXT,
        artifact_ref TEXT,
        period_ref TEXT,
        detail TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mailbox_messages (
        gmail_message_id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL,
        label_snapshot TEXT NOT NULL,
        received_at TEXT NOT NULL,
        is_unread_at_fetch INTEGER NOT NULL,
        mark_read_status TEXT NOT NULL DEFAULT 'pending',
        mark_read_error TEXT,
        reset_unread_status TEXT NOT NULL DEFAULT 'not_requested',
        reset_unread_error TEXT,
        last_processed_run_id TEXT REFERENCES processing_runs(run_id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_report_artifacts (
        artifact_id TEXT PRIMARY KEY,
        gmail_message_id TEXT NOT NULL REFERENCES mailbox_messages(gmail_message_id) ON DELETE CASCADE,
        attachment_id TEXT,
        filename TEXT NOT NULL,
        media_type TEXT NOT NULL,
        content_encoding TEXT NOT NULL,
        sha256 TEXT NOT NULL UNIQUE,
        report_id TEXT,
        org_name TEXT,
        date_begin TEXT,
        date_end TEXT,
        parse_status TEXT NOT NULL,
        parse_error TEXT,
        ingested_run_id TEXT REFERENCES processing_runs(run_id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS normalized_records (
        record_id TEXT PRIMARY KEY,
        artifact_id TEXT NOT NULL REFERENCES source_report_artifacts(artifact_id) ON DELETE CASCADE,
        source_ip TEXT NOT NULL,
        count INTEGER NOT NULL,
        header_from TEXT NOT NULL,
        envelope_from TEXT,
        envelope_to TEXT,
        dkim_result TEXT NOT NULL,
        spf_result TEXT NOT NULL,
        disposition TEXT NOT NULL,
        alignment_dkim INTEGER NOT NULL,
        alignment_spf INTEGER NOT NULL,
        policy_p TEXT NOT NULL,
        policy_sp TEXT,
        policy_pct INTEGER,
        coverage_date_begin TEXT NOT NULL,
        coverage_date_end TEXT NOT NULL,
        dedupe_key TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reporting_periods (
        period_id TEXT PRIMARY KEY,
        period_type TEXT NOT NULL,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        calendar_rule TEXT NOT NULL,
        completeness_status TEXT NOT NULL,
        refresh_status TEXT NOT NULL DEFAULT 'pending_initial',
        latest_source_date TEXT,
        last_data_change_at TEXT,
        last_built_at TEXT,
        last_built_run_id TEXT REFERENCES processing_runs(run_id),
        last_change_reason TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS generated_report_artifacts (
        generated_report_id TEXT PRIMARY KEY,
        period_id TEXT NOT NULL REFERENCES reporting_periods(period_id) ON DELETE CASCADE,
        output_path TEXT NOT NULL UNIQUE,
        content_hash TEXT NOT NULL,
        record_count INTEGER NOT NULL DEFAULT 0,
        build_status TEXT NOT NULL,
        partial_data_flag INTEGER NOT NULL DEFAULT 0,
        generated_at TEXT NOT NULL,
        generated_by_run_id TEXT REFERENCES processing_runs(run_id),
        failure_reason TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS report_library_entries (
        period_id TEXT PRIMARY KEY REFERENCES reporting_periods(period_id) ON DELETE CASCADE,
        cadence TEXT NOT NULL,
        report_year INTEGER NOT NULL,
        report_month INTEGER,
        report_week INTEGER,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        display_title TEXT NOT NULL,
        period_label TEXT NOT NULL,
        relative_path TEXT NOT NULL UNIQUE,
        output_path TEXT NOT NULL UNIQUE,
        build_status TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        generated_at TEXT NOT NULL
    )
    """,
)

INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_artifacts_message ON source_report_artifacts(gmail_message_id)",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_sha256 ON source_report_artifacts(sha256)",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_coverage ON source_report_artifacts(date_begin, date_end)",
    "CREATE INDEX IF NOT EXISTS idx_messages_last_run ON mailbox_messages(last_processed_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_records_artifact ON normalized_records(artifact_id)",
    "CREATE INDEX IF NOT EXISTS idx_records_coverage ON normalized_records(coverage_date_begin, coverage_date_end)",
    "CREATE INDEX IF NOT EXISTS idx_events_run ON processing_run_events(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_reporting_periods_status ON reporting_periods(completeness_status, period_end)",
    "CREATE INDEX IF NOT EXISTS idx_generated_reports_period ON generated_report_artifacts(period_id, generated_at)",
    "CREATE INDEX IF NOT EXISTS idx_report_library_cadence ON report_library_entries(cadence, report_year, report_month, report_week)",
)


def connect_database(database_path: str | Path) -> sqlite3.Connection:
    """Create a SQLite connection with row access by column name."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: str | Path) -> sqlite3.Connection:
    """Initialize all schema objects and return an open connection."""
    connection = connect_database(database_path)
    with connection:
        for statement in DDL_STATEMENTS:
            connection.execute(statement)
        _ensure_compatible_schema(connection)
        for statement in INDEX_STATEMENTS:
            connection.execute(statement)
    return connection


def _ensure_compatible_schema(connection: sqlite3.Connection) -> None:
    _ensure_columns(
        connection,
        "processing_runs",
        {
            "periods_marked_stale": "INTEGER NOT NULL DEFAULT 0",
            "periods_considered": "INTEGER NOT NULL DEFAULT 0",
            "reports_skipped": "INTEGER NOT NULL DEFAULT 0",
            "follow_up_reporting_needed": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    _ensure_columns(
        connection,
        "reporting_periods",
        {
            "refresh_status": "TEXT NOT NULL DEFAULT 'pending_initial'",
            "last_data_change_at": "TEXT",
        },
    )


def _ensure_columns(
    connection: sqlite3.Connection,
    table_name: str,
    columns: dict[str, str],
) -> None:
    existing = {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column_name, ddl in columns.items():
        if column_name in existing:
            continue
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")

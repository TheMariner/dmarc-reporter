"""Reset helpers for local state and Gmail unread restoration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import shutil
import uuid

from dmarc_reporter.config import AppConfig
from dmarc_reporter.gmail.client import GmailClient
from dmarc_reporter.gmail.queries import add_unread_label_ids, find_label_id, labeled_messages_query
from dmarc_reporter.logging import get_logger
from dmarc_reporter.storage.repository import ProcessingRun, Repository, utc_now


@dataclass
class ResetResult:
    messages_restored_unread: int
    repository: Repository


def perform_reset(
    *,
    config: AppConfig,
    repository: Repository,
    gmail_client: GmailClient,
) -> ResetResult:
    """Clear local state and restore labeled Gmail messages to unread."""
    logger = get_logger(__name__)
    reset_rows: list[dict[str, str | bool | None]] = []
    messages_restored_unread = 0

    label_id = _resolve_label_id(gmail_client, config.gmail_label)
    messages = gmail_client.list_messages(
        label_ids=[label_id] if label_id else None,
        query=labeled_messages_query(config.gmail_label),
    )

    for listed in messages:
        message = gmail_client.get_message(listed["id"], format="metadata")
        reset_row: dict[str, str | bool | None] = {
            "gmail_message_id": str(message["id"]),
            "thread_id": str(message.get("threadId", "")),
            "label_snapshot": str(message.get("labelIds", [])),
            "received_at": _gmail_received_at(message),
            "is_unread_at_fetch": "UNREAD" in message.get("labelIds", []),
            "reset_unread_status": "restored",
            "reset_unread_error": None,
        }
        try:
            gmail_client.modify_message_labels(
                message_id=str(message["id"]),
                add_label_ids=add_unread_label_ids(),
            )
            messages_restored_unread += 1
        except Exception as exc:  # pragma: no cover - integration/CLI surface
            logger.warning("Failed to restore unread state for Gmail message %s: %s", message["id"], exc)
            reset_row["reset_unread_status"] = "failed"
            reset_row["reset_unread_error"] = str(exc)
        reset_rows.append(reset_row)

    repository.close()
    _clear_local_state(config)
    replacement_repo = Repository(config.database_path)
    reset_run_id = str(uuid.uuid4())
    replacement_repo.create_processing_run(
        ProcessingRun(
            run_id=reset_run_id,
            started_at=utc_now(),
            mode="reset",
            status="completed_with_warnings" if any(row["reset_unread_status"] == "failed" for row in reset_rows) else "completed",
            finished_at=utc_now(),
            messages_restored_unread=messages_restored_unread,
            failures_count=sum(1 for row in reset_rows if row["reset_unread_status"] == "failed"),
            summary_message="reset prepared mailbox and local state",
        )
    )

    for row in reset_rows:
        replacement_repo.upsert_mailbox_message(
            gmail_message_id=str(row["gmail_message_id"]),
            thread_id=str(row["thread_id"]),
            label_snapshot=str(row["label_snapshot"]),
            received_at=str(row["received_at"]),
            is_unread_at_fetch=bool(row["is_unread_at_fetch"]),
            last_processed_run_id=reset_run_id,
            reset_unread_status=str(row["reset_unread_status"]),
            reset_unread_error=None if row["reset_unread_error"] is None else str(row["reset_unread_error"]),
        )
        if row["reset_unread_status"] == "failed":
            replacement_repo.record_event(
                event_id=str(uuid.uuid4()),
                run_id=reset_run_id,
                severity="warning",
                event_type="reset_marked_unread_failed",
                detail=f"Failed to restore unread state for {row['gmail_message_id']}: {row['reset_unread_error']}",
                message_ref=str(row["gmail_message_id"]),
            )

    return ResetResult(
        messages_restored_unread=messages_restored_unread,
        repository=replacement_repo,
    )


def _clear_local_state(config: AppConfig) -> None:
    if config.database_path.exists():
        config.database_path.unlink()
    if config.reports_dir.exists():
        shutil.rmtree(config.reports_dir)
    config.ensure_directories()


def _gmail_received_at(message: dict[str, object]) -> str:
    epoch_ms = int(str(message.get("internalDate", "0")))
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat()


def _resolve_label_id(gmail_client: GmailClient, label_name: str) -> str | None:
    return find_label_id(gmail_client.list_labels(), label_name)

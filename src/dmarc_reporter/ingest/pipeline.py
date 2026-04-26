"""Ingestion pipeline orchestration for aggregate DMARC mail."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import uuid
from typing import Any

from dmarc_reporter.config import AppConfig
from dmarc_reporter.gmail.client import GmailClient
from dmarc_reporter.gmail.queries import find_label_id, remove_unread_label_ids, unread_label_query
from dmarc_reporter.ingest.attachments import extract_report_attachments
from dmarc_reporter.ingest.dedupe import build_record_dedupe_key, compute_file_hash
from dmarc_reporter.ingest.parser import parse_aggregate_report
from dmarc_reporter.logging import get_logger
from dmarc_reporter.reporting.manifest import sync_reporting_period_states
from dmarc_reporter.storage.repository import ProcessingRun, Repository


@dataclass
class RunSummary:
    run_id: str
    mode: str
    status: str
    messages_seen: int = 0
    messages_ingested: int = 0
    messages_restored_unread: int = 0
    duplicates_detected: int = 0
    artifacts_parsed: int = 0
    periods_marked_stale: int = 0
    follow_up_reporting_needed: bool = False
    reports_generated: int = 0
    reports_regenerated: int = 0
    warnings: int = 0


def run_ingestion(
    *,
    config: AppConfig,
    repository: Repository,
    gmail_client: GmailClient,
    reset: bool = False,
) -> RunSummary:
    """Run one ingest cycle against unread Gmail DMARC messages."""
    logger = get_logger(__name__)
    run_id = str(uuid.uuid4())
    summary = RunSummary(run_id=run_id, mode="reset" if reset else "normal", status="running")

    repository.create_processing_run(
        ProcessingRun(
            run_id=run_id,
            started_at=_utc_now(),
            mode=summary.mode,
        )
    )

    try:
        label_id = _resolve_label_id(gmail_client, config.gmail_label)
        messages = gmail_client.list_messages(
            label_ids=[label_id] if label_id else None,
            query=unread_label_query(config.gmail_label),
        )
        summary.messages_seen = len(messages)

        for listed in messages:
            message = gmail_client.get_message(listed["id"], format="full")
            label_snapshot = json.dumps(message.get("labelIds", []))
            is_unread = "UNREAD" in message.get("labelIds", [])
            repository.upsert_mailbox_message(
                gmail_message_id=message["id"],
                thread_id=message.get("threadId", ""),
                label_snapshot=label_snapshot,
                received_at=_gmail_received_at(message),
                is_unread_at_fetch=is_unread,
                last_processed_run_id=run_id,
            )

            attachments = extract_report_attachments(
                message.get("payload", {}),
                lambda attachment_id: gmail_client.get_attachment(
                    message_id=message["id"],
                    attachment_id=attachment_id,
                ),
            )

            if not attachments:
                _record_warning(
                    repository,
                    run_id=run_id,
                    event_type="no_supported_attachment",
                    detail=f"No DMARC attachment found for message {message['id']}",
                    message_ref=message["id"],
                )
                summary.warnings += 1
                continue

            ingested_any = False
            duplicate_any = False
            parse_failed_any = False
            for attachment in attachments:
                artifact_hash = compute_file_hash(attachment.payload)
                if repository.source_report_exists(artifact_hash):
                    summary.duplicates_detected += 1
                    duplicate_any = True
                    _record_warning(
                        repository,
                        run_id=run_id,
                        event_type="duplicate_report",
                        detail=f"Duplicate report skipped for message {message['id']}",
                        message_ref=message["id"],
                    )
                    summary.warnings += 1
                    continue

                artifact_id = str(uuid.uuid4())
                try:
                    parsed = parse_aggregate_report(attachment.payload)
                except Exception as exc:
                    repository.insert_source_report_artifact(
                        {
                            "artifact_id": artifact_id,
                            "gmail_message_id": message["id"],
                            "attachment_id": attachment.attachment_id,
                            "filename": attachment.filename,
                            "media_type": attachment.media_type,
                            "content_encoding": attachment.content_encoding,
                            "sha256": artifact_hash,
                            "report_id": None,
                            "org_name": None,
                            "date_begin": None,
                            "date_end": None,
                            "parse_status": "failed",
                            "parse_error": str(exc),
                            "ingested_run_id": run_id,
                        }
                    )
                    _record_warning(
                        repository,
                        run_id=run_id,
                        event_type="attachment_parse_failed",
                        detail=(
                            f"Failed to parse attachment {attachment.filename or attachment.attachment_id or 'unknown'} "
                            f"from message {message['id']}: {exc}"
                        ),
                        message_ref=message["id"],
                        artifact_ref=artifact_id,
                    )
                    summary.warnings += 1
                    parse_failed_any = True
                    continue

                repository.insert_source_report_artifact(
                    {
                        "artifact_id": artifact_id,
                        "gmail_message_id": message["id"],
                        "attachment_id": attachment.attachment_id,
                        "filename": attachment.filename,
                        "media_type": attachment.media_type,
                        "content_encoding": attachment.content_encoding,
                        "sha256": artifact_hash,
                        "report_id": parsed.report_id,
                        "org_name": parsed.org_name,
                        "date_begin": parsed.date_begin,
                        "date_end": parsed.date_end,
                        "parse_status": "parsed",
                        "parse_error": None,
                        "ingested_run_id": run_id,
                    }
                )

                normalized_rows: list[dict[str, Any]] = []
                for index, record in enumerate(parsed.records):
                    normalized_rows.append(
                        {
                            "record_id": str(uuid.uuid4()),
                            "artifact_id": artifact_id,
                            "source_ip": record["source_ip"],
                            "count": record["count"],
                            "header_from": record["header_from"],
                            "envelope_from": record["envelope_from"],
                            "envelope_to": record["envelope_to"],
                            "dkim_result": record["dkim_result"],
                            "spf_result": record["spf_result"],
                            "disposition": record["disposition"],
                            "alignment_dkim": int(record["alignment_dkim"]),
                            "alignment_spf": int(record["alignment_spf"]),
                            "policy_p": parsed.policy["p"],
                            "policy_sp": parsed.policy["sp"],
                            "policy_pct": parsed.policy["pct"],
                            "coverage_date_begin": parsed.date_begin,
                            "coverage_date_end": parsed.date_end,
                            "dedupe_key": build_record_dedupe_key(
                                artifact_hash=artifact_hash,
                                record=record,
                                index=index,
                            ),
                        }
                    )
                repository.insert_normalized_records(normalized_rows)
                summary.artifacts_parsed += 1
                ingested_any = True
                print(
                    (
                        "ingested_report "
                        f"message_id={message['id']} "
                        f"attachment={attachment.filename or attachment.attachment_id or 'unknown'} "
                        f"report_id={parsed.report_id} "
                        f"org_name={parsed.org_name} "
                        f"records={len(parsed.records)}"
                    ),
                    flush=True,
                )

            if ingested_any or duplicate_any or parse_failed_any:
                try:
                    gmail_client.modify_message_labels(
                        message_id=message["id"],
                        remove_label_ids=remove_unread_label_ids(),
                    )
                    repository.upsert_mailbox_message(
                        gmail_message_id=message["id"],
                        thread_id=message.get("threadId", ""),
                        label_snapshot=label_snapshot,
                        received_at=_gmail_received_at(message),
                        is_unread_at_fetch=is_unread,
                        last_processed_run_id=run_id,
                        mark_read_status="succeeded",
                    )
                except Exception as exc:  # pragma: no cover - exercised via integration tests
                    repository.upsert_mailbox_message(
                        gmail_message_id=message["id"],
                        thread_id=message.get("threadId", ""),
                        label_snapshot=label_snapshot,
                        received_at=_gmail_received_at(message),
                        is_unread_at_fetch=is_unread,
                        last_processed_run_id=run_id,
                        mark_read_status="failed",
                        mark_read_error=str(exc),
                    )
                    _record_warning(
                        repository,
                        run_id=run_id,
                        event_type="mark_read_failed",
                        detail=f"Failed to mark message {message['id']} as read: {exc}",
                        message_ref=message["id"],
                    )
                    summary.warnings += 1
                if ingested_any:
                    summary.messages_ingested += 1

        summary.periods_marked_stale = sync_reporting_period_states(repository=repository)
        summary.follow_up_reporting_needed = repository.count_reporting_periods_needing_reports() > 0
        summary.status = "completed_with_warnings" if summary.warnings else "completed"
        repository.finish_processing_run(
            run_id,
            status=summary.status,
            summary_message="ingestion complete",
            counters={
                "messages_seen": summary.messages_seen,
                "messages_ingested": summary.messages_ingested,
                "artifacts_parsed": summary.artifacts_parsed,
                "duplicates_detected": summary.duplicates_detected,
                "periods_marked_stale": summary.periods_marked_stale,
                "follow_up_reporting_needed": int(summary.follow_up_reporting_needed),
                "failures_count": summary.warnings,
            },
        )
        logger.info(
            "Run %s complete: seen=%s ingested=%s duplicates=%s warnings=%s",
            summary.run_id,
            summary.messages_seen,
            summary.messages_ingested,
            summary.duplicates_detected,
            summary.warnings,
        )
        return summary
    except Exception:
        repository.finish_processing_run(
            run_id,
            status="failed",
            summary_message="ingestion failed",
            counters={"failures_count": summary.warnings + 1},
        )
        raise


def _record_warning(
    repository: Repository,
    *,
    run_id: str,
    event_type: str,
    detail: str,
    message_ref: str | None = None,
    artifact_ref: str | None = None,
) -> None:
    repository.record_event(
        event_id=str(uuid.uuid4()),
        run_id=run_id,
        severity="warning",
        event_type=event_type,
        detail=detail,
        message_ref=message_ref,
        artifact_ref=artifact_ref,
    )


def _gmail_received_at(message: dict[str, Any]) -> str:
    epoch_ms = int(message.get("internalDate", "0"))
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat()


def _resolve_label_id(gmail_client: GmailClient, label_name: str) -> str | None:
    labels = gmail_client.list_labels()
    return find_label_id(labels, label_name)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

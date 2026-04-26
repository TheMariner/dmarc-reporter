from __future__ import annotations

import base64
import json
from pathlib import Path

from dmarc_reporter.config import AppConfig
from dmarc_reporter.ingest.pipeline import run_ingestion
from dmarc_reporter.storage.repository import Repository


def _encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


class FakeGmailClient:
    def __init__(self, xml_payload: bytes) -> None:
        self._xml_payload = xml_payload
        self.modified_messages: list[str] = []

    def list_labels(self) -> list[dict[str, str]]:
        return [{"id": "Label_42", "name": "DMARC"}]

    def list_messages(self, **_: object) -> list[dict[str, str]]:
        return [{"id": "msg-1", "threadId": "thread-1"}]

    def get_message(self, message_id: str, *, format: str = "full") -> dict[str, object]:
        assert message_id == "msg-1"
        assert format == "full"
        return {
            "id": "msg-1",
            "threadId": "thread-1",
            "labelIds": ["Label_42", "UNREAD"],
            "internalDate": "1713225600000",
            "payload": {
                "parts": [
                    {
                        "filename": "aggregate.xml",
                        "mimeType": "application/xml",
                        "body": {"attachmentId": "att-1"},
                    }
                ]
            },
        }

    def get_attachment(self, *, message_id: str, attachment_id: str) -> dict[str, str]:
        assert message_id == "msg-1"
        assert attachment_id == "att-1"
        return {"data": _encode(self._xml_payload)}

    def modify_message_labels(self, *, message_id: str, add_label_ids=None, remove_label_ids=None, user_id: str = "me") -> dict[str, object]:
        self.modified_messages.append(message_id)
        return {"id": message_id, "labelIds": ["Label_42"]}


def test_ingest_run_persists_records_and_marks_message_read(tmp_path: Path, capsys) -> None:
    repo = Repository(tmp_path / "dmarc.sqlite")
    xml_payload = Path("tests/fixtures/dmarc/aggregate-report.xml").read_bytes()
    gmail_client = FakeGmailClient(xml_payload)
    config = AppConfig(
        gmail_client_secret=tmp_path / "client.json",
        gmail_token_path=tmp_path / "token.json",
        data_dir=tmp_path,
        reports_dir=tmp_path / "reports",
        database_path=tmp_path / "dmarc.sqlite",
    )

    summary = run_ingestion(config=config, repository=repo, gmail_client=gmail_client)
    output = capsys.readouterr().out

    assert summary.status == "completed"
    assert summary.messages_seen == 1
    assert summary.messages_ingested == 1
    assert summary.follow_up_reporting_needed
    assert gmail_client.modified_messages == ["msg-1"]
    assert "ingested_report message_id=msg-1" in output
    assert "report_id=example-com!1713139200!1713225599" in output
    assert not (config.reports_dir / "weekly" / "weekly-2024-W16.html").exists()

    stored_message = repo.connection.execute(
        "SELECT mark_read_status FROM mailbox_messages WHERE gmail_message_id = 'msg-1'"
    ).fetchone()
    assert stored_message["mark_read_status"] == "succeeded"

    stored_artifact = repo.connection.execute(
        "SELECT sha256, report_id FROM source_report_artifacts"
    ).fetchone()
    assert stored_artifact["sha256"]
    assert stored_artifact["report_id"] == "example-com!1713139200!1713225599"

    record_count = repo.connection.execute(
        "SELECT COUNT(*) AS count FROM normalized_records"
    ).fetchone()["count"]
    assert record_count == 1
    reporting_periods = repo.connection.execute(
        """
        SELECT period_id, refresh_status
        FROM reporting_periods
        WHERE completeness_status = 'complete'
        ORDER BY period_id
        """
    ).fetchall()
    assert [row["refresh_status"] for row in reporting_periods] == [
        "pending_initial",
        "pending_initial",
        "pending_initial",
    ]
    repo.close()


def test_ingest_run_records_malformed_attachment_and_continues(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "dmarc.sqlite")
    gmail_client = FakeGmailClient(b"not xml")
    config = AppConfig(
        gmail_client_secret=tmp_path / "client.json",
        gmail_token_path=tmp_path / "token.json",
        data_dir=tmp_path,
        reports_dir=tmp_path / "reports",
        database_path=tmp_path / "dmarc.sqlite",
    )

    summary = run_ingestion(config=config, repository=repo, gmail_client=gmail_client)

    assert summary.status == "completed_with_warnings"
    assert summary.messages_seen == 1
    assert summary.messages_ingested == 0
    assert summary.artifacts_parsed == 0
    assert summary.warnings == 1
    assert gmail_client.modified_messages == ["msg-1"]

    artifact = repo.connection.execute(
        "SELECT parse_status, parse_error FROM source_report_artifacts"
    ).fetchone()
    assert artifact["parse_status"] == "failed"
    assert "line 1, column 0" in artifact["parse_error"]

    event = repo.connection.execute(
        "SELECT event_type FROM processing_run_events WHERE event_type = 'attachment_parse_failed'"
    ).fetchone()
    assert event["event_type"] == "attachment_parse_failed"
    repo.close()

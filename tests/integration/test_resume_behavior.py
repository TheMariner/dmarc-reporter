from __future__ import annotations

import base64
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


def test_resume_behavior_skips_duplicate_payloads(tmp_path: Path) -> None:
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

    first = run_ingestion(config=config, repository=repo, gmail_client=gmail_client)
    second = run_ingestion(config=config, repository=repo, gmail_client=gmail_client)

    assert first.messages_ingested == 1
    assert second.messages_ingested == 0
    assert second.duplicates_detected == 1
    assert second.periods_marked_stale == 0
    assert gmail_client.modified_messages == ["msg-1", "msg-1"]

    artifact_count = repo.connection.execute(
        "SELECT COUNT(*) AS count FROM source_report_artifacts"
    ).fetchone()["count"]
    assert artifact_count == 1
    artifact_row = repo.connection.execute(
        "SELECT gmail_message_id, filename, sha256 FROM source_report_artifacts"
    ).fetchone()
    assert artifact_row["gmail_message_id"] == "msg-1"
    assert artifact_row["filename"] == "aggregate.xml"
    message_row = repo.connection.execute(
        "SELECT mark_read_status FROM mailbox_messages WHERE gmail_message_id = 'msg-1'"
    ).fetchone()
    assert message_row["mark_read_status"] == "succeeded"

    events = repo.connection.execute(
        "SELECT event_type FROM processing_run_events WHERE event_type = 'duplicate_report'"
    ).fetchall()
    assert len(events) == 1
    pending_count = repo.count_reporting_periods_needing_reports()
    assert pending_count == 3
    repo.close()

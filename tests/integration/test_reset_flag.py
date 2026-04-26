from __future__ import annotations

from pathlib import Path

from dmarc_reporter.config import AppConfig
from dmarc_reporter.storage.repository import Repository
from dmarc_reporter.storage.reset import perform_reset


class FakeGmailClient:
    def __init__(self) -> None:
        self.modified_messages: list[str] = []

    def list_labels(self) -> list[dict[str, str]]:
        return [{"id": "Label_42", "name": "DMARC"}]

    def list_messages(self, **_: object) -> list[dict[str, str]]:
        return [
            {"id": "msg-1", "threadId": "thread-1"},
            {"id": "msg-2", "threadId": "thread-2"},
        ]

    def get_message(self, message_id: str, *, format: str = "full") -> dict[str, object]:
        assert format == "metadata"
        return {
            "id": message_id,
            "threadId": f"thread-{message_id}",
            "labelIds": ["Label_42"],
            "internalDate": "1713225600000",
        }

    def modify_message_labels(
        self,
        *,
        message_id: str,
        add_label_ids=None,
        remove_label_ids=None,
        user_id: str = "me",
    ) -> dict[str, object]:
        self.modified_messages.append(message_id)
        return {"id": message_id, "labelIds": ["Label_42", "UNREAD"]}


def test_reset_clears_local_state_and_restores_unread(tmp_path: Path) -> None:
    config = AppConfig(
        gmail_client_secret=tmp_path / "client.json",
        gmail_token_path=tmp_path / "token.json",
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        database_path=tmp_path / "data" / "dmarc.sqlite",
    )
    config.ensure_directories()

    repo = Repository(config.database_path)
    repo.connection.execute(
        """
        INSERT INTO mailbox_messages (
            gmail_message_id, thread_id, label_snapshot, received_at,
            is_unread_at_fetch, mark_read_status, mark_read_error,
            reset_unread_status, reset_unread_error, last_processed_run_id,
            created_at, updated_at
        ) VALUES (
            'persisted-msg', 'thread-old', '["Label_42"]', '2024-04-16T00:00:00+00:00',
            0, 'succeeded', NULL, 'not_requested', NULL, NULL,
            '2024-04-16T00:00:00+00:00', '2024-04-16T00:00:00+00:00'
        )
        """
    )
    repo.connection.commit()
    (config.reports_dir / "weekly").mkdir(parents=True, exist_ok=True)
    (config.reports_dir / "weekly" / "weekly-2024-W16.html").write_text("stale", encoding="utf-8")

    gmail_client = FakeGmailClient()
    reset_result = perform_reset(
        config=config,
        repository=repo,
        gmail_client=gmail_client,
    )

    assert reset_result.messages_restored_unread == 2
    assert sorted(gmail_client.modified_messages) == ["msg-1", "msg-2"]
    assert not (config.reports_dir / "weekly" / "weekly-2024-W16.html").exists()

    replacement_repo = Repository(config.database_path)
    run_row = replacement_repo.connection.execute(
        "SELECT mode, status, messages_restored_unread FROM processing_runs WHERE mode = 'reset'"
    ).fetchone()
    assert run_row["mode"] == "reset"
    assert run_row["messages_restored_unread"] == 2
    rows = replacement_repo.connection.execute(
        "SELECT gmail_message_id, reset_unread_status FROM mailbox_messages ORDER BY gmail_message_id"
    ).fetchall()
    assert [(row["gmail_message_id"], row["reset_unread_status"]) for row in rows] == [
        ("msg-1", "restored"),
        ("msg-2", "restored"),
    ]
    replacement_repo.close()

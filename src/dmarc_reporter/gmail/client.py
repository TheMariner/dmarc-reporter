"""Thin Gmail API client wrapper."""

from __future__ import annotations

from typing import Any


class GmailClient:
    """Wrapper around the Gmail API service object."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def close(self) -> None:
        return None

    def list_messages(self, *, user_id: str = "me", label_ids: list[str] | None = None, query: str | None = None) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            request = self._service.users().messages().list(
                userId=user_id,
                labelIds=label_ids or None,
                q=query,
                pageToken=page_token,
            )
            response = request.execute()
            messages.extend(response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return messages

    def get_message(self, message_id: str, *, user_id: str = "me", format: str = "full") -> dict[str, Any]:
        return (
            self._service.users()
            .messages()
            .get(userId=user_id, id=message_id, format=format)
            .execute()
        )

    def get_attachment(
        self,
        *,
        message_id: str,
        attachment_id: str,
        user_id: str = "me",
    ) -> dict[str, Any]:
        return (
            self._service.users()
            .messages()
            .attachments()
            .get(userId=user_id, messageId=message_id, id=attachment_id)
            .execute()
        )

    def modify_message_labels(
        self,
        *,
        message_id: str,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
        user_id: str = "me",
    ) -> dict[str, Any]:
        body = {
            "addLabelIds": add_label_ids or [],
            "removeLabelIds": remove_label_ids or [],
        }
        return (
            self._service.users()
            .messages()
            .modify(userId=user_id, id=message_id, body=body)
            .execute()
        )

    def list_labels(self, *, user_id: str = "me") -> list[dict[str, Any]]:
        response = self._service.users().labels().list(userId=user_id).execute()
        return list(response.get("labels", []))


def build_gmail_service(credentials: Any) -> Any:
    """Build the underlying Gmail service object."""
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=credentials, cache_discovery=False)

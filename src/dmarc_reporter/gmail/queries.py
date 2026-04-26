"""Query helpers for Gmail label and unread state handling."""

from __future__ import annotations


def unread_label_query(label_name: str) -> str:
    """Return the Gmail search query for unread messages under a label."""
    return f"label:{label_name} is:unread"


def labeled_messages_query(label_name: str) -> str:
    """Return the Gmail search query for all messages under a label."""
    return f"label:{label_name}"


def find_label_id(labels: list[dict[str, str]], label_name: str) -> str | None:
    """Resolve a Gmail label ID by its display name."""
    target = label_name.casefold()
    for label in labels:
        if label.get("name", "").casefold() == target:
            return label.get("id")
    return None


def remove_unread_label_ids() -> list[str]:
    """Return Gmail system label IDs to remove when marking a message read."""
    return ["UNREAD"]


def add_unread_label_ids() -> list[str]:
    """Return Gmail system label IDs to add when marking a message unread."""
    return ["UNREAD"]

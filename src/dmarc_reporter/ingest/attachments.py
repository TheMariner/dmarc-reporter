"""Attachment extraction and payload normalization for DMARC reports."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import gzip
from io import BytesIO
import zipfile
from typing import Any, Callable


AttachmentFetcher = Callable[[str], dict[str, Any]]
SUPPORTED_INLINE_TYPES = {
    "application/xml",
    "text/xml",
    "application/gzip",
    "application/x-gzip",
    "application/zip",
}
SUPPORTED_EXTENSIONS = (".xml", ".xml.gz", ".gz", ".zip")


@dataclass
class ExtractedAttachment:
    """Normalized representation of an extracted report attachment."""

    attachment_id: str | None
    filename: str
    media_type: str
    content_encoding: str
    payload: bytes


def extract_report_attachments(
    message_payload: dict[str, Any],
    attachment_fetcher: AttachmentFetcher,
) -> list[ExtractedAttachment]:
    """Extract supported report attachments from a Gmail message payload."""
    extracted: list[ExtractedAttachment] = []
    for part in _iter_parts(message_payload):
        filename = part.get("filename") or ""
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")
        media_type = part.get("mimeType", "application/octet-stream")
        inline_data = body.get("data")

        if not _is_supported_candidate(filename=filename, media_type=media_type):
            continue

        if attachment_id:
            attachment = attachment_fetcher(attachment_id)
            inline_data = attachment.get("data")

        if not inline_data:
            continue

        raw_payload = decode_gmail_attachment_data(inline_data)
        payload, content_encoding = normalize_attachment_payload(
            filename=filename or "attachment.xml",
            media_type=media_type,
            raw_payload=raw_payload,
        )
        extracted.append(
            ExtractedAttachment(
                attachment_id=attachment_id,
                filename=filename,
                media_type=media_type,
                content_encoding=content_encoding,
                payload=payload,
            )
        )

    return extracted


def decode_gmail_attachment_data(encoded_data: str) -> bytes:
    """Decode Gmail's URL-safe base64 attachment encoding."""
    padding = "=" * (-len(encoded_data) % 4)
    return base64.urlsafe_b64decode(encoded_data + padding)


def normalize_attachment_payload(
    *,
    filename: str,
    media_type: str,
    raw_payload: bytes,
) -> tuple[bytes, str]:
    """Normalize attachment bytes to plain XML payload."""
    lowered_name = filename.lower()
    lowered_type = media_type.lower()

    if lowered_name.endswith(".gz") or lowered_type in {"application/gzip", "application/x-gzip"}:
        return gzip.decompress(raw_payload), "gzip"

    if lowered_name.endswith(".zip") or lowered_type == "application/zip":
        with zipfile.ZipFile(BytesIO(raw_payload)) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                with archive.open(member) as handle:
                    return handle.read(), "zip"
        raise ValueError("ZIP attachment contained no file payloads")

    return raw_payload, "xml"


def _iter_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    children = payload.get("parts", [])
    if not children:
        return [payload]
    for child in children:
        parts.extend(_iter_parts(child))
    return parts


def _is_supported_candidate(*, filename: str, media_type: str) -> bool:
    lowered_name = filename.lower()
    lowered_type = media_type.lower()
    return lowered_type in SUPPORTED_INLINE_TYPES or lowered_name.endswith(SUPPORTED_EXTENSIONS)

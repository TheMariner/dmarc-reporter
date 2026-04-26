from __future__ import annotations

import base64
import gzip
from io import BytesIO
from pathlib import Path
import zipfile

from dmarc_reporter.ingest.attachments import (
    decode_gmail_attachment_data,
    extract_report_attachments,
    normalize_attachment_payload,
)
from dmarc_reporter.ingest.parser import parse_aggregate_report


def _fixture_xml() -> bytes:
    return Path("tests/fixtures/dmarc/aggregate-report.xml").read_bytes()


def _encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def test_decode_and_normalize_gzip_payload() -> None:
    xml_payload = _fixture_xml()
    gz_payload = gzip.compress(xml_payload)
    decoded = decode_gmail_attachment_data(_encode(gz_payload))
    normalized, encoding = normalize_attachment_payload(
        filename="aggregate.xml.gz",
        media_type="application/gzip",
        raw_payload=decoded,
    )
    assert normalized == xml_payload
    assert encoding == "gzip"


def test_extract_zip_attachment_from_message_payload() -> None:
    xml_payload = _fixture_xml()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("aggregate.xml", xml_payload)
    payload = buffer.getvalue()

    message_payload = {
        "parts": [
            {
                "filename": "aggregate.zip",
                "mimeType": "application/zip",
                "body": {"attachmentId": "ATTACH-1"},
            }
        ]
    }

    attachments = extract_report_attachments(
        message_payload,
        lambda attachment_id: {"data": _encode(payload)},
    )

    assert len(attachments) == 1
    assert attachments[0].payload == xml_payload
    assert attachments[0].content_encoding == "zip"


def test_parse_aggregate_report_extracts_metadata_and_records() -> None:
    parsed = parse_aggregate_report(_fixture_xml())

    assert parsed.report_id == "example-com!1713139200!1713225599"
    assert parsed.org_name == "Example Mail"
    assert parsed.policy["p"] == "quarantine"
    assert len(parsed.records) == 1
    assert parsed.records[0]["source_ip"] == "203.0.113.10"
    assert parsed.records[0]["count"] == 42
    assert parsed.records[0]["alignment_dkim"] is True
    assert parsed.records[0]["alignment_spf"] is True


def test_extract_report_attachments_ignores_non_report_inline_parts() -> None:
    message_payload = {
        "parts": [
            {
                "filename": "",
                "mimeType": "text/plain",
                "body": {"data": _encode(b"hello")},
            }
        ]
    }

    attachments = extract_report_attachments(message_payload, lambda _: {})

    assert attachments == []

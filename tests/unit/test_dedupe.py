from __future__ import annotations

from pathlib import Path

from dmarc_reporter.ingest.dedupe import build_record_dedupe_key, compute_file_hash


def test_compute_file_hash_is_deterministic() -> None:
    payload = Path("tests/fixtures/dmarc/aggregate-report.xml").read_bytes()
    first = compute_file_hash(payload)
    second = compute_file_hash(payload)
    assert first == second
    assert len(first) == 64


def test_build_record_dedupe_key_changes_with_index_or_record_values() -> None:
    record = {
        "source_ip": "203.0.113.10",
        "header_from": "example.com",
        "count": 42,
        "disposition": "none",
    }
    key_one = build_record_dedupe_key(artifact_hash="abc", record=record, index=0)
    key_two = build_record_dedupe_key(artifact_hash="abc", record=record, index=1)
    key_three = build_record_dedupe_key(
        artifact_hash="def",
        record=record,
        index=0,
    )

    assert key_one != key_two
    assert key_one != key_three

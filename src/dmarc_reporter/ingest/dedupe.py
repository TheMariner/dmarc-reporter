"""Deduplication helpers for source reports and normalized rows."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_file_hash(payload: bytes) -> str:
    """Compute a deterministic SHA-256 digest for a payload."""
    return hashlib.sha256(payload).hexdigest()


def build_record_dedupe_key(
    *,
    artifact_hash: str,
    record: dict[str, Any],
    index: int,
) -> str:
    """Build a stable dedupe key for a normalized DMARC record."""
    raw = json.dumps(
        {
            "artifact_hash": artifact_hash,
            "index": index,
            "source_ip": record["source_ip"],
            "header_from": record["header_from"],
            "count": record["count"],
            "disposition": record["disposition"],
        },
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

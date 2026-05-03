"""Thread-safe in-memory claim store (swap for Redis / DynamoDB in production)."""

from threading import Lock
from typing import Dict, Optional

from app.models import ClaimRecord

_lock = Lock()
_store: Dict[str, ClaimRecord] = {}


def save_claim(record: ClaimRecord) -> None:
    with _lock:
        _store[record.claim_id] = record


def get_claim(claim_id: str) -> Optional[ClaimRecord]:
    with _lock:
        return _store.get(claim_id)


def list_claims() -> list[ClaimRecord]:
    with _lock:
        return list(_store.values())

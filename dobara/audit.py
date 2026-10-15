"""Append-only, hash-chained audit log.

Audit fix F18: payloads are deep-copied when logged (later edits to a live object cannot
alter or falsely "tamper" an entry), the real clock is used by default, and verify() can
check an EXTERNAL head anchor (entry count + last hash, printed on the daily report or
sent to the administrator) so that deleting the newest entries is also detected.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _h(body: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class AuditLog:
    def __init__(self):
        self.entries: List[Dict[str, Any]] = []

    def append(self, record_id: str, action: str, actor: str, role: str, payload: Dict[str, Any],
               at: datetime | None = None) -> Dict[str, Any]:
        prev = self.entries[-1]["hash"] if self.entries else "GENESIS"
        body = {
            "seq": len(self.entries), "record_id": record_id, "action": action, "actor": actor, "role": role,
            "at": (at or datetime.now()).isoformat(),
            "payload": json.loads(json.dumps(payload, default=str)),   # deep copy
            "prev": prev,
        }
        body["hash"] = _h(body)
        self.entries.append(body)
        return body

    def head(self) -> Tuple[int, str]:
        """External anchor: store this outside the system (daily report / administrator)."""
        return len(self.entries), (self.entries[-1]["hash"] if self.entries else "GENESIS")

    def verify(self, expected_head: Optional[Tuple[int, str]] = None) -> bool:
        prev = "GENESIS"
        for i, e in enumerate(self.entries):
            body = {k: v for k, v in e.items() if k != "hash"}
            if body.get("seq") != i or body["prev"] != prev or _h(body) != e["hash"]:
                return False
            prev = e["hash"]
        if expected_head is not None:
            n, last = expected_head
            if n > len(self.entries) or (n > 0 and self.entries[n - 1]["hash"] != last):
                return False
        return True

    def for_record(self, record_id: str) -> List[Dict[str, Any]]:
        return [e for e in self.entries if e["record_id"] == record_id]

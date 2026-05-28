"""Audit logger — append-only JSON Lines log for all memory operations."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    def __init__(self, log_path: Path | str) -> None:
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        action: str,
        *,
        role: str = "default",
        category: str = "",
        scope: str = "",
        target: str = "",
        outcome: str = "allowed",
        detail: str = "",
        pii_detections: list[str] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "timestamp": _now_iso(),
            "action": action,
            "role": role,
            "category": category,
            "scope": scope,
            "target": target,
            "outcome": outcome,
            "detail": detail,
            "pii_detections": pii_detections or [],
            "pid": os.getpid(),
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def query(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        action: str | None = None,
        role: str | None = None,
        category: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        results: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = entry.get("timestamp", "")
                if start_date and ts < start_date:
                    continue
                if end_date and ts > end_date:
                    continue
                if action and entry.get("action") != action:
                    continue
                if role and entry.get("role") != role:
                    continue
                if category and entry.get("category") != category:
                    continue
                results.append(entry)
        return results[-limit:]

    @property
    def path(self) -> Path:
        return self._path


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

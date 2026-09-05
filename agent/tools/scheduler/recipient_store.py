"""Persistent directory of trusted scheduler delivery targets."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional


class RecipientStore:
    """Remember recipient identities learned from accepted inbound messages.

    The store deliberately contains no access tokens or channel credentials.
    Channel implementations remain responsible for authentication and their
    normal outbound readiness checks.
    """

    def __init__(self, store_path: str) -> None:
        self.store_path = Path(store_path)
        self._lock = threading.RLock()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(channel_type: str, receiver: str) -> str:
        return f"{channel_type}\0{receiver}"

    def _load_unlocked(self) -> Dict[str, dict]:
        if not self.store_path.exists():
            return {}
        try:
            with self.store_path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            recipients = value.get("recipients", {})
            return recipients if isinstance(recipients, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _save_unlocked(self, recipients: Dict[str, dict]) -> None:
        payload = {"version": 1, "recipients": recipients}
        temporary = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.store_path)

    def remember(
        self,
        channel_type: str,
        receiver: str,
        *,
        name: str = "",
        is_group: bool = False,
        session_id: str = "",
    ) -> Optional[dict]:
        channel_type = str(channel_type or "").strip()
        receiver = str(receiver or "").strip()
        if not channel_type or not receiver or channel_type in {"unknown", "web"}:
            return None
        entry = {
            "channel_type": channel_type,
            "receiver": receiver,
            "name": str(name or receiver),
            "is_group": bool(is_group),
            "session_id": str(session_id or receiver),
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            recipients = self._load_unlocked()
            key = self._key(channel_type, receiver)
            previous = recipients.get(key)
            stable_fields = ("channel_type", "receiver", "name", "is_group", "session_id")
            if previous and all(previous.get(field) == entry[field] for field in stable_fields):
                try:
                    last_seen = datetime.fromisoformat(previous["last_seen_at"])
                    if datetime.now(timezone.utc) - last_seen < timedelta(hours=1):
                        return dict(previous)
                except (KeyError, TypeError, ValueError):
                    pass
            recipients[key] = entry
            self._save_unlocked(recipients)
        return dict(entry)

    def get(self, channel_type: str, receiver: str) -> Optional[dict]:
        with self._lock:
            entry = self._load_unlocked().get(self._key(channel_type, receiver))
        return dict(entry) if entry else None

    def list(self) -> List[dict]:
        with self._lock:
            entries = [dict(item) for item in self._load_unlocked().values()]
        return sorted(entries, key=lambda item: (item["channel_type"], item["name"], item["receiver"]))

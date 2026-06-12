# -*- coding=utf-8 -*-
"""
Local-file based persistence for WeCom customer-service `next_cursor`.

Why we need this:
    The WeCom customer-service (微信客服) callback only notifies us that
    "new messages exist". To actually fetch them we must call the
    `cgi-bin/kf/sync_msg` endpoint with a `cursor` so that we only get
    messages newer than the previously processed one. If we lose this
    cursor (e.g. on process restart) WeCom will replay up to ~14 days of
    history, which would cause the bot to flood users with duplicate
    replies.

This implementation deliberately avoids any external dependency
(no Redis / no DB) — a single JSON file under the project's tmp dir is
enough for a CoW-style single-process deployment.
"""
import json
import os
import threading
from typing import Optional

from common.log import logger


class CursorStore:
    """Thread-safe per-`open_kfid` cursor store backed by a JSON file."""

    def __init__(self, file_path: str):
        self._file_path = file_path
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        try:
            if os.path.exists(self._file_path):
                with open(self._file_path, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception as e:
            logger.warning(f"[wechat_kf] failed to load cursor file {self._file_path}: {e}")
        return {}

    def _flush_locked(self):
        # Atomic write: write to *.tmp first then rename, avoid corruption on crash.
        tmp_path = self._file_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self._file_path) or ".", exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False)
            os.replace(tmp_path, self._file_path)
            # Tighten permissions: cursor file lives in $HOME, restrict to owner.
            # No-op on Windows.
            try:
                os.chmod(self._file_path, 0o600)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"[wechat_kf] failed to flush cursor file {self._file_path}: {e}")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def get(self, open_kfid: str) -> Optional[str]:
        with self._lock:
            return self._data.get(open_kfid)

    def set(self, open_kfid: str, cursor: str):
        if not cursor:
            return
        with self._lock:
            if self._data.get(open_kfid) == cursor:
                return
            self._data[open_kfid] = cursor
            self._flush_locked()

    def has(self, open_kfid: str) -> bool:
        with self._lock:
            return open_kfid in self._data

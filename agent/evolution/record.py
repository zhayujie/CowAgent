"""Self-evolution record log.

Session-level evolutions are appended to their OWN per-day file under
``memory/evolution/YYYY-MM-DD.md`` (separate from the nightly Deep Dream diary
in ``memory/dreams/``). Each day's file accumulates one short section per
evolution pass — tagged with a timestamp and a backup id for undo — so the
memory UI can surface "what the agent learned/changed today" on one timeline
without ever mixing into the dream diary or the main conversation memory.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from common.log import logger


def _evolution_dir(workspace_dir: Path, user_id: Optional[str] = None) -> Path:
    base = Path(workspace_dir) / "memory"
    if user_id:
        return base / "users" / user_id / "evolution"
    return base / "evolution"


def append_session_evolution(
    workspace_dir: Path,
    summary: str,
    backup_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Append a session-evolution entry to today's evolution log."""
    if not summary or not summary.strip():
        return
    try:
        evo_dir = _evolution_dir(workspace_dir, user_id)
        evo_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = evo_dir / f"{today}.md"

        ts = datetime.now().strftime("%H:%M")
        header = f"## {ts}"
        body = summary.strip()
        if backup_id:
            body += f"\n\n_backup_id: {backup_id}_"

        # Create with a title if the file is new, otherwise append a section.
        if not log_file.exists():
            log_file.write_text(f"# Self-Evolution: {today}\n\n", encoding="utf-8")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{header}\n\n{body}\n")
        logger.info(f"[Evolution] Recorded session evolution to {log_file.name}")
    except Exception as e:
        logger.warning(f"[Evolution] Failed to record session evolution: {e}")

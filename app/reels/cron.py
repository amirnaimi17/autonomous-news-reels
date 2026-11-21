"""Ubuntu cron lines for four Berlin generation attempts.

Installation writes a crontab fragment. It does not start a catch-up of
missed hours. ``flock`` stops a second run while the first still holds the lock.
"""

from __future__ import annotations

import fcntl
from pathlib import Path

from app.reels.config import ReelConfig

BEGIN = "# BEGIN autonomous-news-reels"
END = "# END autonomous-news-reels"


class RunLock:
    """Non-blocking exclusive lock. A second process gets False."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._handle.close()
            self._handle = None
            return False
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


def cron_block(config: ReelConfig) -> str:
    """The marked crontab block. Hours are interpreted with CRON_TZ."""

    hours = ",".join(str(hour) for hour in config.generation_hours)
    python = Path(config.python_executable)
    if not python.is_absolute():
        python = config.working_directory / python
    python = python.absolute()
    work = config.working_directory.resolve()
    lock = config.lock_path.resolve()
    log = config.log_path.resolve()
    command = (
        f"cd {work} && flock -n {lock} {python} -m app.cli generate-reel "
        f"--target {config.target_page} --scheduled >> {log} 2>&1"
    )
    line = f"0 {hours} * * * {command}"
    return "\n".join([BEGIN, "CRON_TZ=Europe/Berlin", line, END, ""])


def install_cron_text(existing: str, config: ReelConfig) -> str:
    """Replace a previous block and leave every other crontab line alone."""

    kept: list[str] = []
    skipping = False
    for line in existing.splitlines():
        if line.strip() == BEGIN:
            skipping = True
            continue
        if line.strip() == END:
            skipping = False
            continue
        if not skipping:
            kept.append(line)
    body = "\n".join(kept).strip()
    if body:
        body += "\n"
    return body + cron_block(config)


def remove_cron_text(existing: str) -> str:
    """Drop the marked block and leave the rest of the crontab."""

    kept: list[str] = []
    skipping = False
    for line in existing.splitlines():
        if line.strip() == BEGIN:
            skipping = True
            continue
        if line.strip() == END:
            skipping = False
            continue
        if not skipping:
            kept.append(line)
    body = "\n".join(kept).strip()
    return f"{body}\n" if body else ""

"""SQLite connection setup.

Foreign keys and the busy timeout are per connection in SQLite, so every
connection applies them. WAL lets a status reader run during a write.
"""

import sqlite3
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection that manages its own transactions."""

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection

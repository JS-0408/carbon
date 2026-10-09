"""SQLite audit store: write-through log of jobs, alerts and benchmark runs.

The live simulation state is in memory (simulated clock); this store keeps an audit trail and the latest
benchmark so results survive restarts. It does not restore a running simulation.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS bench(id INTEGER PRIMARY KEY, ts TEXT, name TEXT, payload TEXT);
        """)

    def log(self, kind: str, payload: dict) -> None:
        with self.lock:
            self.db.execute("INSERT INTO events(ts,kind,payload) VALUES(?,?,?)",
                            (datetime.now(timezone.utc).isoformat(), kind, json.dumps(payload, default=str)))
            self.db.commit()

    def events(self, kind: str | None = None, limit: int = 200) -> list:
        with self.lock:
            q, a = "SELECT ts,kind,payload FROM events", ()
            if kind:
                q, a = q + " WHERE kind=?", (kind,)
            rows = self.db.execute(q + " ORDER BY id DESC LIMIT ?", a + (limit,)).fetchall()
        return [{"ts": r[0], "kind": r[1], "payload": json.loads(r[2])} for r in rows]

    def save_bench(self, name: str, payload: dict) -> None:
        with self.lock:
            self.db.execute("INSERT INTO bench(ts,name,payload) VALUES(?,?,?)",
                            (datetime.now(timezone.utc).isoformat(), name, json.dumps(payload)))
            self.db.commit()

    def latest_bench(self, name: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT payload FROM bench WHERE name=? ORDER BY id DESC LIMIT 1", (name,)).fetchone()
        return json.loads(r[0]) if r else None

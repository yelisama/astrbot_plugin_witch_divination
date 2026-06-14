from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class DivinationRecord:
    user_id: str
    day: str
    type_id: str
    result_id: str
    background_id: str
    free_used: int
    coin_cost: int
    created_at: int


class RecordStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    user_id TEXT NOT NULL,
                    day TEXT NOT NULL,
                    type_id TEXT NOT NULL,
                    result_id TEXT NOT NULL,
                    background_id TEXT NOT NULL DEFAULT '',
                    free_used INTEGER NOT NULL DEFAULT 0,
                    coin_cost INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (user_id, day, type_id)
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(records)").fetchall()}
            if "background_id" not in columns:
                db.execute("ALTER TABLE records ADD COLUMN background_id TEXT NOT NULL DEFAULT ''")
            db.commit()

    def get_record(self, user_id: str, day: str, type_id: str) -> DivinationRecord | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM records WHERE user_id=? AND day=? AND type_id=?",
                (user_id, day, type_id),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def count_daily_generated(self, user_id: str, day: str) -> int:
        with self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS n FROM records WHERE user_id=? AND day=?",
                (user_id, day),
            ).fetchone()
        return int(row["n"] if row else 0)

    def create_record(
        self,
        user_id: str,
        day: str,
        type_id: str,
        result_id: str | None = None,
        background_id: str | None = None,
        free_used: int = 0,
        coin_cost: int = 0,
    ) -> DivinationRecord:
        rid = result_id or uuid.uuid4().hex
        bgid = background_id or uuid.uuid4().hex
        created_at = int(time.time())
        with self._connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO records
                (user_id, day, type_id, result_id, background_id, free_used, coin_cost, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, day, type_id, rid, bgid, int(free_used), int(coin_cost), created_at),
            )
            db.commit()
        return DivinationRecord(user_id, day, type_id, rid, bgid, int(free_used), int(coin_cost), created_at)

    def maybe_cleanup(self, interval_days: int, keep_days: int) -> int:
        now = int(time.time())
        interval = max(int(interval_days), 1) * SECONDS_PER_DAY
        last = int(self.get_meta("last_cleanup_at", "0") or "0")
        if now - last < interval:
            return 0
        removed = self.cleanup(keep_days)
        self.set_meta("last_cleanup_at", str(now))
        return removed

    def cleanup(self, keep_days: int) -> int:
        cutoff = int(time.time()) - max(int(keep_days), 1) * SECONDS_PER_DAY
        with self._connect() as db:
            cur = db.execute("DELETE FROM records WHERE created_at < ?", (cutoff,))
            db.commit()
            return int(cur.rowcount or 0)

    def stats(self) -> dict[str, int]:
        with self._connect() as db:
            records = db.execute("SELECT COUNT(*) AS n FROM records").fetchone()["n"]
            users = db.execute("SELECT COUNT(DISTINCT user_id) AS n FROM records").fetchone()["n"]
        return {"records": int(records), "users": int(users)}

    def get_meta(self, key: str, default: str = "") -> str:
        with self._connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (key, value),
            )
            db.commit()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> DivinationRecord:
        return DivinationRecord(
            user_id=str(row["user_id"]),
            day=str(row["day"]),
            type_id=str(row["type_id"]),
            result_id=str(row["result_id"]),
            background_id=str(row["background_id"] if "background_id" in row.keys() else ""),
            free_used=int(row["free_used"]),
            coin_cost=int(row["coin_cost"]),
            created_at=int(row["created_at"]),
        )

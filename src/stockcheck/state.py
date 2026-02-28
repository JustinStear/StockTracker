from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from stockcheck.models import StockStatus


@dataclass(slots=True)
class TransitionResult:
    changed: bool
    should_alert: bool
    previous_status: StockStatus | None
    current_status: StockStatus


class StateStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_state (
                    retailer TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    store_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (retailer, item_key, store_id)
                )
                """
            )
            conn.commit()

    def get_status(
        self, retailer: str, item_key: str, store_id: str
    ) -> StockStatus | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT status
                FROM stock_state
                WHERE retailer = ? AND item_key = ? AND store_id = ?
                """,
                (retailer, item_key, store_id),
            ).fetchone()

        if row is None:
            return None
        return StockStatus(row["status"])

    def update_status(
        self, retailer: str, item_key: str, store_id: str, status: StockStatus
    ) -> TransitionResult:
        previous = self.get_status(retailer, item_key, store_id)
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO stock_state (retailer, item_key, store_id, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(retailer, item_key, store_id)
                DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at
                """,
                (retailer, item_key, store_id, status.value, now),
            )
            conn.commit()

        changed = previous != status
        should_alert = changed and status == StockStatus.IN_STOCK
        return TransitionResult(
            changed=changed,
            should_alert=should_alert,
            previous_status=previous,
            current_status=status,
        )

    def dump_status(self) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT retailer, item_key, store_id, status, updated_at
                FROM stock_state
                ORDER BY retailer, item_key, store_id
                """
            ).fetchall()

        return [dict(row) for row in rows]

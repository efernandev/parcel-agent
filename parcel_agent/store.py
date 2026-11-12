import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS parcels (
                    id TEXT PRIMARY KEY,
                    received_at TEXT NOT NULL,
                    collected INTEGER NOT NULL DEFAULT 0,
                    manual_collected INTEGER NOT NULL DEFAULT 0,
                    details TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processed (
                    message_id TEXT PRIMARY KEY
                );
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def pending(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id, details FROM parcels WHERE collected = 0 "
                "ORDER BY received_at DESC"
            ).fetchall()
        return [dict(json.loads(row["details"]), id=row["id"]) for row in rows]

    def is_processed(self, message_id: str) -> bool:
        with self.connection() as connection:
            return connection.execute(
                "SELECT 1 FROM processed WHERE message_id = ?", (message_id,)
            ).fetchone() is not None

    def apply_message(self, message_id: str, updates: list[dict[str, Any]]) -> None:
        with self.connection() as connection:
            for update in updates:
                parcel_id = update["id"]
                previous = connection.execute(
                    "SELECT * FROM parcels WHERE id = ?", (parcel_id,)
                ).fetchone()
                if previous and previous["received_at"] > update["received_at"]:
                    continue
                details = json.loads(previous["details"]) if previous else {}
                details.update({
                    key: value for key, value in update.items()
                    if value is not None and value != []
                })
                collected = update["event"] == "collected" or bool(
                    previous and previous["manual_collected"]
                )
                connection.execute(
                    "INSERT INTO parcels(id, received_at, collected, details) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET received_at=excluded.received_at, "
                    "collected=excluded.collected, details=excluded.details",
                    (parcel_id, update["received_at"], int(collected), json.dumps(details)),
                )
            connection.execute(
                "INSERT OR IGNORE INTO processed(message_id) VALUES (?)", (message_id,)
            )

    def collect(self, parcel_id: str, collected: bool = True) -> bool:
        with self.connection() as connection:
            result = connection.execute(
                "UPDATE parcels SET collected = ?, manual_collected = ? WHERE id = ?",
                (int(collected), int(collected), parcel_id),
            )
            return result.rowcount > 0
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc


def utc_now() -> datetime:
    """Utility function to get the current date and time in UTC with proper timezone information."""
    return datetime.now(tz=UTC)


@dataclass(slots=True)
class ApprovalRecord:
    approval_id: str
    user_id: str
    tool_name: str
    arguments_json: str
    arguments_hash: str
    status: str
    created_at: str
    expires_at: str
    approver: str | None
    note: str | None


class Storage:
    def __init__(self, db_path: str) -> None:
        """Initializes the SQLite database connection, applies thread safety locks, and ensures tables exist."""
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Creates the 'approvals' and 'audit_events' tables if they do not already exist in the database."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    arguments_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    approver TEXT,
                    note TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    user_id TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def log_event(self, event_type: str, user_id: str | None, payload: dict[str, Any]) -> None:
        """Records a security or system event into the historical audit log table."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO audit_events(created_at, event_type, user_id, payload_json) VALUES (?, ?, ?, ?)",
                (utc_now().isoformat(), event_type, user_id, json.dumps(payload, sort_keys=True)),
            )

    def ensure_pending_approval(
        self,
        *,
        user_id: str,
        tool_name: str,
        arguments_json: str,
        arguments_hash: str,
        ttl_seconds: int = 900,
    ) -> ApprovalRecord:
        """Retrieves an existing pending approval or creates a new one for a specific tool invocation."""
        expires_at = (utc_now() + timedelta(seconds=ttl_seconds)).isoformat()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM approvals
                WHERE user_id = ? AND tool_name = ? AND arguments_hash = ?
                  AND status = 'pending' AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, tool_name, arguments_hash, utc_now().isoformat()),
            ).fetchone()
            if row:
                return self._row_to_record(row)

            approval_id = str(uuid.uuid4())
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO approvals(
                        approval_id, user_id, tool_name, arguments_json, arguments_hash,
                        status, created_at, expires_at, approver, note
                    ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, NULL, NULL)
                    """,
                    (
                        approval_id,
                        user_id,
                        tool_name,
                        arguments_json,
                        arguments_hash,
                        utc_now().isoformat(),
                        expires_at,
                    ),
                )
            row = self._conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            return self._row_to_record(row)

    def has_active_approval(self, user_id: str, tool_name: str, arguments_hash: str) -> bool:
        """Checks if a valid, unexpired approval exists for a specific user and tool call signature."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT approval_id FROM approvals
                WHERE user_id = ? AND tool_name = ? AND arguments_hash = ?
                  AND status = 'approved' AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, tool_name, arguments_hash, utc_now().isoformat()),
            ).fetchone()
            return row is not None

    def update_approval_status(
        self,
        approval_id: str,
        *,
        status: str,
        approver: str,
        note: str | None,
        extend_ttl_seconds: int = 900,
    ) -> ApprovalRecord | None:
        """Updates a request status (e.g., 'approved') and optionally extends its expiration time."""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if not row:
                return None

            expires_at = row["expires_at"]
            if status == "approved":
                expires_at = (utc_now() + timedelta(seconds=extend_ttl_seconds)).isoformat()

            self._conn.execute(
                """
                UPDATE approvals
                SET status = ?, approver = ?, note = ?, expires_at = ?
                WHERE approval_id = ?
                """,
                (status, approver, note, expires_at, approval_id),
            )
            updated = self._conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            return self._row_to_record(updated)

    def list_approvals(self) -> list[ApprovalRecord]:
        """Retrieves all historical and pending approval records ordered by creation timestamp."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM approvals ORDER BY created_at DESC"
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ApprovalRecord:
        """Static helper to convert a SQLite row object into a structured ApprovalRecord dataclass."""
        return ApprovalRecord(
            approval_id=row["approval_id"],
            user_id=row["user_id"],
            tool_name=row["tool_name"],
            arguments_json=row["arguments_json"],
            arguments_hash=row["arguments_hash"],
            status=row["status"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            approver=row["approver"],
            note=row["note"],
        )

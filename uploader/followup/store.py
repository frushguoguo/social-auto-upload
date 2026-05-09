from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from conf import BASE_DIR

from .models import CommentEvent


def _utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


class FollowupStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Path(BASE_DIR / "db" / "database.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_tables(self) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS publish_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    account_name TEXT NOT NULL,
                    account_file TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    publish_time TEXT NOT NULL,
                    post_id TEXT DEFAULT '',
                    post_url TEXT DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_publish_records_platform_account_time
                ON publish_records(platform, account_name, publish_time DESC)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS comment_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    account_name TEXT NOT NULL,
                    comment_id TEXT NOT NULL,
                    post_id TEXT DEFAULT '',
                    post_url TEXT DEFAULT '',
                    commenter_id TEXT DEFAULT '',
                    commenter_name TEXT DEFAULT '',
                    comment_text TEXT NOT NULL DEFAULT '',
                    comment_time TEXT DEFAULT '',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(platform, comment_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_comment_events_platform_account
                ON comment_events(platform, account_name, last_seen_at DESC)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS comment_reply_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    account_name TEXT NOT NULL,
                    comment_id TEXT NOT NULL,
                    reply_text TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_comment_reply_logs_platform_comment
                ON comment_reply_logs(platform, comment_id, created_at DESC)
                """
            )
            conn.commit()

    def record_publish(
        self,
        *,
        platform: str,
        account_name: str,
        account_file: str,
        content_type: str,
        title: str,
        description: str = "",
        tags: list[str] | None = None,
        publish_time: str | None = None,
        post_id: str = "",
        post_url: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        publish_time = publish_time or _utcnow_iso()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO publish_records (
                    platform,
                    account_name,
                    account_file,
                    content_type,
                    title,
                    description,
                    tags_json,
                    publish_time,
                    post_id,
                    post_url,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    platform,
                    account_name,
                    account_file,
                    content_type,
                    title,
                    description,
                    tags_json,
                    publish_time,
                    post_id,
                    post_url,
                    metadata_json,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_recent_publish_records(
        self,
        *,
        platform: str,
        account_name: str,
        since_hours: int,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        since_at = (datetime.utcnow() - timedelta(hours=max(0, since_hours))).replace(microsecond=0).isoformat()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM publish_records
                WHERE platform = ? AND account_name = ? AND publish_time >= ?
                ORDER BY publish_time DESC
                LIMIT ?
                """,
                (platform, account_name, since_at, limit),
            )
            return list(cursor.fetchall())

    def count_comments(self, *, platform: str, account_name: str) -> int:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(1) AS cnt
                FROM comment_events
                WHERE platform = ? AND account_name = ?
                """,
                (platform, account_name),
            )
            row = cursor.fetchone()
            return int(row["cnt"] if row else 0)

    def upsert_comment_event(self, event: CommentEvent) -> bool:
        now = _utcnow_iso()
        raw_json = json.dumps(event.raw or {}, ensure_ascii=False)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO comment_events (
                    platform,
                    account_name,
                    comment_id,
                    post_id,
                    post_url,
                    commenter_id,
                    commenter_name,
                    comment_text,
                    comment_time,
                    raw_json,
                    first_seen_at,
                    last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.platform,
                    event.account_name,
                    event.comment_id,
                    event.post_id,
                    event.post_url,
                    event.commenter_id,
                    event.commenter_name,
                    event.comment_text,
                    event.comment_time,
                    raw_json,
                    now,
                    now,
                ),
            )
            inserted = cursor.rowcount > 0
            if not inserted:
                cursor.execute(
                    """
                    UPDATE comment_events
                    SET
                        account_name = ?,
                        post_id = ?,
                        post_url = ?,
                        commenter_id = ?,
                        commenter_name = ?,
                        comment_text = ?,
                        comment_time = ?,
                        raw_json = ?,
                        last_seen_at = ?
                    WHERE platform = ? AND comment_id = ?
                    """,
                    (
                        event.account_name,
                        event.post_id,
                        event.post_url,
                        event.commenter_id,
                        event.commenter_name,
                        event.comment_text,
                        event.comment_time,
                        raw_json,
                        now,
                        event.platform,
                        event.comment_id,
                    ),
                )
            conn.commit()
            return inserted

    def has_successful_reply(self, *, platform: str, comment_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1
                FROM comment_reply_logs
                WHERE platform = ? AND comment_id = ? AND status = 'success'
                LIMIT 1
                """,
                (platform, comment_id),
            )
            return cursor.fetchone() is not None

    def log_reply(
        self,
        *,
        platform: str,
        account_name: str,
        comment_id: str,
        reply_text: str,
        status: str,
        reason: str = "",
        error_message: str = "",
    ) -> int:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO comment_reply_logs (
                    platform,
                    account_name,
                    comment_id,
                    reply_text,
                    status,
                    reason,
                    error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    platform,
                    account_name,
                    comment_id,
                    reply_text,
                    status,
                    reason,
                    error_message,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)


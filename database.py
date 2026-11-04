"""
ADZOHO Bot — Database Layer
Async SQLite operations for leads, templates, admins, and settings.
"""

from __future__ import annotations

import aiosqlite
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Database:
    """Async SQLite wrapper for the ADZOHO bot."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()
        logger.info("Database connected: %s", self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            logger.info("Database closed.")

    async def _create_tables(self) -> None:
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                user_id        INTEGER PRIMARY KEY,
                username       TEXT,
                first_name     TEXT,
                last_name      TEXT,
                status         TEXT    NOT NULL DEFAULT 'New',
                join_date      TEXT    NOT NULL,
                last_msg_date  TEXT,
                next_followup  TEXT,
                followup_stage INTEGER NOT NULL DEFAULT 0,
                opted_out      INTEGER NOT NULL DEFAULT 0,
                source_chat_id INTEGER,
                created_at     TEXT    NOT NULL,
                updated_at     TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admins (
                user_id   INTEGER PRIMARY KEY,
                username  TEXT,
                is_super  INTEGER NOT NULL DEFAULT 0,
                added_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS message_templates (
                key        TEXT PRIMARY KEY,
                text       TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS message_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                template_key TEXT NOT NULL,
                stage       INTEGER,
                sent_at     TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'sent',
                FOREIGN KEY (user_id) REFERENCES leads(user_id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS lead_notes (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL,
                admin_id  INTEGER NOT NULL,
                note      TEXT    NOT NULL,
                created_at TEXT   NOT NULL,
                FOREIGN KEY (user_id) REFERENCES leads(user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_leads_status
                ON leads(status);
            CREATE INDEX IF NOT EXISTS idx_leads_next_followup
                ON leads(next_followup);
            CREATE INDEX IF NOT EXISTS idx_message_log_user
                ON message_log(user_id, template_key);
            """
        )
        await self._db.commit()

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _row_to_dict(self, row: aiosqlite.Row | None) -> dict | None:
        if row is None:
            return None
        return dict(row)

    # ── Leads ────────────────────────────────────────────────────────────

    async def add_lead(
        self,
        user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        source_chat_id: int | None = None,
    ) -> bool:
        """Insert a new lead. Returns True if inserted, False if duplicate."""
        now = self._now()
        try:
            await self._db.execute(
                """INSERT INTO leads
                   (user_id, username, first_name, last_name, join_date,
                    source_chat_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, username, first_name, last_name, now,
                 source_chat_id, now, now),
            )
            await self._db.commit()
            logger.info("New lead added: %s (%s)", user_id, username)
            return True
        except aiosqlite.IntegrityError:
            logger.debug("Lead already exists: %s", user_id)
            return False

    async def get_lead(self, user_id: int) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM leads WHERE user_id = ?", (user_id,)
        ) as cursor:
            return self._row_to_dict(await cursor.fetchone())

    async def lead_exists(self, user_id: int) -> bool:
        async with self._db.execute(
            "SELECT 1 FROM leads WHERE user_id = ?", (user_id,)
        ) as cursor:
            return (await cursor.fetchone()) is not None

    async def update_lead_status(self, user_id: int, status: str) -> None:
        await self._db.execute(
            "UPDATE leads SET status = ?, updated_at = ? WHERE user_id = ?",
            (status, self._now(), user_id),
        )
        await self._db.commit()

    async def update_lead_followup(
        self, user_id: int, stage: int, next_date: str | None
    ) -> None:
        await self._db.execute(
            """UPDATE leads
               SET followup_stage = ?, next_followup = ?, updated_at = ?
               WHERE user_id = ?""",
            (stage, next_date, self._now(), user_id),
        )
        await self._db.commit()

    async def update_lead_last_message(self, user_id: int) -> None:
        now = self._now()
        await self._db.execute(
            "UPDATE leads SET last_msg_date = ?, updated_at = ? WHERE user_id = ?",
            (now, now, user_id),
        )
        await self._db.commit()

    async def mark_opted_out(self, user_id: int) -> None:
        await self._db.execute(
            """UPDATE leads
               SET opted_out = 1, status = 'Opted Out',
                   next_followup = NULL, updated_at = ?
               WHERE user_id = ?""",
            (self._now(), user_id),
        )
        await self._db.commit()

    async def get_leads(
        self,
        status: str | None = None,
        page: int = 1,
        per_page: int = 8,
    ) -> tuple[list[dict], int]:
        """Return (leads, total_count) with optional status filter + pagination."""
        where = ""
        params: list[Any] = []
        if status:
            where = "WHERE status = ?"
            params.append(status)

        async with self._db.execute(
            f"SELECT COUNT(*) FROM leads {where}", params
        ) as cur:
            total = (await cur.fetchone())[0]

        offset = (page - 1) * per_page
        params_with_limit = params + [per_page, offset]
        async with self._db.execute(
            f"""SELECT * FROM leads {where}
                ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            params_with_limit,
        ) as cur:
            rows = await cur.fetchall()

        return [dict(r) for r in rows], total

    async def search_leads(self, query: str) -> list[dict]:
        q = f"%{query}%"
        async with self._db.execute(
            """SELECT * FROM leads
               WHERE username LIKE ? OR first_name LIKE ?
                     OR last_name LIKE ? OR CAST(user_id AS TEXT) LIKE ?
               ORDER BY created_at DESC LIMIT 20""",
            (q, q, q, q),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_lead_stats(self) -> dict[str, int]:
        stats: dict[str, int] = {}
        async with self._db.execute(
            "SELECT status, COUNT(*) as cnt FROM leads GROUP BY status"
        ) as cur:
            async for row in cur:
                stats[row["status"]] = row["cnt"]
        async with self._db.execute("SELECT COUNT(*) FROM leads") as cur:
            stats["Total"] = (await cur.fetchone())[0]
        return stats

    async def get_pending_followups(self) -> list[dict]:
        """Leads that have a scheduled next follow-up and are still active."""
        now = self._now()
        async with self._db.execute(
            """SELECT * FROM leads
               WHERE next_followup IS NOT NULL
                 AND next_followup <= ?
                 AND opted_out = 0
                 AND status IN ('New', 'Contacted', 'Interested')
               ORDER BY next_followup ASC""",
            (now,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_all_active_leads(self) -> list[dict]:
        """All leads that haven't opted out and are in active statuses."""
        async with self._db.execute(
            """SELECT * FROM leads
               WHERE opted_out = 0
                 AND status IN ('New', 'Contacted', 'Interested')
               ORDER BY created_at DESC"""
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_leads_with_pending_followups(self) -> list[dict]:
        """Leads with a future followup scheduled (for scheduler reload)."""
        async with self._db.execute(
            """SELECT * FROM leads
               WHERE next_followup IS NOT NULL
                 AND opted_out = 0
                 AND status IN ('New', 'Contacted', 'Interested')"""
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def export_leads_csv(self) -> str:
        """Export all leads as a CSV string."""
        async with self._db.execute(
            "SELECT * FROM leads ORDER BY created_at DESC"
        ) as cur:
            rows = await cur.fetchall()
            if not rows:
                return ""
            columns = [desc[0] for desc in cur.description]

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row[col] for col in columns])
        return output.getvalue()

    # ── Message Log ──────────────────────────────────────────────────────

    async def log_message(
        self, user_id: int, template_key: str, stage: int | None = None
    ) -> None:
        await self._db.execute(
            """INSERT INTO message_log (user_id, template_key, stage, sent_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, template_key, stage, self._now()),
        )
        await self._db.commit()

    async def was_message_sent(
        self, user_id: int, template_key: str
    ) -> bool:
        async with self._db.execute(
            """SELECT 1 FROM message_log
               WHERE user_id = ? AND template_key = ? LIMIT 1""",
            (user_id, template_key),
        ) as cur:
            return (await cur.fetchone()) is not None

    async def get_lead_message_history(self, user_id: int) -> list[dict]:
        async with self._db.execute(
            """SELECT * FROM message_log
               WHERE user_id = ? ORDER BY sent_at DESC LIMIT 20""",
            (user_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ── Templates ────────────────────────────────────────────────────────

    async def get_template(self, key: str) -> str | None:
        async with self._db.execute(
            "SELECT text FROM message_templates WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row["text"] if row else None

    async def set_template(self, key: str, text: str) -> None:
        await self._db.execute(
            """INSERT INTO message_templates (key, text, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET text = ?, updated_at = ?""",
            (key, text, self._now(), text, self._now()),
        )
        await self._db.commit()

    async def get_all_templates(self) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM message_templates ORDER BY key"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ── Settings ─────────────────────────────────────────────────────────

    async def get_setting(self, key: str) -> str | None:
        async with self._db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self._db.execute(
            """INSERT INTO settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = ?""",
            (key, value, value),
        )
        await self._db.commit()

    # ── Admins ───────────────────────────────────────────────────────────

    async def is_admin(self, user_id: int) -> bool:
        async with self._db.execute(
            "SELECT 1 FROM admins WHERE user_id = ?", (user_id,)
        ) as cur:
            return (await cur.fetchone()) is not None

    async def is_super_admin(self, user_id: int) -> bool:
        async with self._db.execute(
            "SELECT is_super FROM admins WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return bool(row["is_super"]) if row else False

    async def add_admin(
        self, user_id: int, username: str | None, is_super: bool = False
    ) -> None:
        await self._db.execute(
            """INSERT OR IGNORE INTO admins (user_id, username, is_super, added_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, username, int(is_super), self._now()),
        )
        await self._db.commit()

    async def add_or_update_admin(
        self, user_id: int, username: str | None, is_super: bool = False
    ) -> None:
        await self._db.execute(
            """INSERT INTO admins (user_id, username, is_super, added_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET is_super = MAX(is_super, excluded.is_super), username = excluded.username""",
            (user_id, username, int(is_super), self._now()),
        )
        await self._db.commit()

    async def clear_all_admins(self) -> None:
        """Revoke all active admin sessions."""
        await self._db.execute("DELETE FROM admins")
        await self._db.commit()

    async def remove_admin(self, user_id: int) -> None:
        await self._db.execute(
            "DELETE FROM admins WHERE user_id = ? AND is_super = 0",
            (user_id,),
        )
        await self._db.commit()

    async def get_all_admins(self) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM admins ORDER BY added_at"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def admin_count(self) -> int:
        async with self._db.execute("SELECT COUNT(*) FROM admins") as cur:
            return (await cur.fetchone())[0]

    # ── Lead Notes ───────────────────────────────────────────────────────

    async def add_note(
        self, user_id: int, admin_id: int, note: str
    ) -> None:
        await self._db.execute(
            """INSERT INTO lead_notes (user_id, admin_id, note, created_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, admin_id, note, self._now()),
        )
        await self._db.commit()

    async def get_notes(self, user_id: int) -> list[dict]:
        async with self._db.execute(
            """SELECT * FROM lead_notes
               WHERE user_id = ? ORDER BY created_at DESC LIMIT 10""",
            (user_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .context_store import ChatMessage
from .openai_client import OpenAIResponsesClient
from .prompt_builder import build_prompt_preview, build_reply_instructions, select_memory_with_budget


@dataclass(frozen=True)
class PreparedConversation:
    session_id: int
    instructions: str
    input_messages: List[ChatMessage]
    prompt_preview: str


class SQLiteMemoryRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at INTEGER NOT NULL,
                    last_activity_at INTEGER NOT NULL,
                    closed_at INTEGER,
                    summarized_at INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_user_status
                ON sessions (telegram_user_id, status, last_activity_at);

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    content_json TEXT NOT NULL,
                    summary_text TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_id
                ON messages (session_id, id);

                CREATE TABLE IF NOT EXISTS personal_memory (
                    telegram_user_id INTEGER PRIMARY KEY,
                    content_json TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS session_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL UNIQUE,
                    telegram_user_id INTEGER NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                """
            )

    def ensure_user(self, telegram_user_id: int, now_ts: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (telegram_user_id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (telegram_user_id, now_ts, now_ts),
            )

    def get_open_session(self, telegram_user_id: int) -> Optional[sqlite3.Row]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT * FROM sessions
                WHERE telegram_user_id = ? AND status = 'open'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (telegram_user_id,),
            )
            return cursor.fetchone()

    def create_session(self, telegram_user_id: int, now_ts: int) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO sessions (telegram_user_id, status, started_at, last_activity_at)
                VALUES (?, 'open', ?, ?)
                """,
                (telegram_user_id, now_ts, now_ts),
            )
            return int(cursor.lastrowid)

    def update_session_activity(self, session_id: int, now_ts: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET last_activity_at = ? WHERE id = ?",
                (now_ts, session_id),
            )

    def close_session(self, session_id: int, now_ts: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET status = 'closed_pending_summary', closed_at = ?, last_activity_at = ?
                WHERE id = ? AND status = 'open'
                """,
                (now_ts, now_ts, session_id),
            )

    def mark_session_summarized(self, session_id: int, now_ts: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET status = 'summarized', summarized_at = ?
                WHERE id = ?
                """,
                (now_ts, session_id),
            )

    def discard_open_session(self, telegram_user_id: int) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "SELECT id FROM sessions WHERE telegram_user_id = ? AND status = 'open'",
                (telegram_user_id,),
            )
            session_ids = [int(row["id"]) for row in cursor.fetchall()]
            if not session_ids:
                return
            connection.executemany("DELETE FROM messages WHERE session_id = ?", ((session_id,) for session_id in session_ids))
            connection.executemany("DELETE FROM sessions WHERE id = ?", ((session_id,) for session_id in session_ids))

    def add_message(self, session_id: int, message: ChatMessage, summary_text: str, now_ts: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (session_id, role, created_at, content_json, summary_text)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    message.role,
                    now_ts,
                    json.dumps(message.to_storage_dict(), ensure_ascii=False),
                    summary_text,
                ),
            )

    def get_recent_messages(self, session_id: int, limit: int) -> List[ChatMessage]:
        if limit <= 0:
            return []
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT content_json
                FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
            rows = list(reversed(cursor.fetchall()))
        return [ChatMessage.from_storage_dict(json.loads(row["content_json"])) for row in rows]

    def get_session_summary_transcript(self, session_id: int) -> str:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT summary_text
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            )
            lines = [row["summary_text"] for row in cursor.fetchall() if row["summary_text"]]
        return "\n".join(lines).strip()

    def get_expired_open_sessions(self, cutoff_ts: int, limit: int = 20) -> List[sqlite3.Row]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT *
                FROM sessions
                WHERE status = 'open' AND last_activity_at <= ?
                ORDER BY last_activity_at ASC
                LIMIT ?
                """,
                (cutoff_ts, limit),
            )
            return cursor.fetchall()

    def get_personal_memory(self, telegram_user_id: int) -> List[Dict[str, str]]:
        with self._connect() as connection:
            cursor = connection.execute(
                "SELECT content_json FROM personal_memory WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            row = cursor.fetchone()
        if not row:
            return []
        payload = json.loads(row["content_json"])
        return [dict(item) for item in payload]

    def save_personal_memory(
        self,
        telegram_user_id: int,
        personal_memory: Sequence[Dict[str, str]],
        now_ts: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO personal_memory (telegram_user_id, content_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    content_json = excluded.content_json,
                    updated_at = excluded.updated_at
                """,
                (telegram_user_id, json.dumps(list(personal_memory), ensure_ascii=False), now_ts),
            )

    def get_recent_summaries(self, telegram_user_id: int, limit: int) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT session_id, summary_json, created_at
                FROM session_summaries
                WHERE telegram_user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (telegram_user_id, limit),
            )
            rows = cursor.fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["summary_json"])
            payload["session_id"] = row["session_id"]
            payload["created_at"] = row["created_at"]
            results.append(payload)
        return results

    def save_session_summary(
        self,
        session_id: int,
        telegram_user_id: int,
        summary_payload: Dict[str, Any],
        now_ts: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO session_summaries (session_id, telegram_user_id, summary_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, telegram_user_id, json.dumps(summary_payload, ensure_ascii=False), now_ts),
            )


class MemoryService:
    def __init__(
        self,
        repository: SQLiteMemoryRepository,
        openai_client: OpenAIResponsesClient,
        context_size: int,
        summary_count: int,
        memory_budget: int,
        session_timeout_seconds: int,
        base_system_prompt: str,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.repository = repository
        self.openai_client = openai_client
        self.context_size = context_size
        self.summary_count = summary_count
        self.memory_budget = memory_budget
        self.session_timeout_seconds = session_timeout_seconds
        self.base_system_prompt = base_system_prompt
        self.logger = logger or logging.getLogger(__name__)

    def prepare_conversation(
        self,
        telegram_user_id: int,
        message: ChatMessage,
        summary_text: str,
        correlation_id: str,
        now_ts: Optional[int] = None,
    ) -> PreparedConversation:
        current_ts = _normalize_ts(now_ts)
        self.repository.ensure_user(telegram_user_id, current_ts)
        self._summarize_stale_session_for_user(telegram_user_id, current_ts, correlation_id)

        session = self.repository.get_open_session(telegram_user_id)
        if session is None:
            session_id = self.repository.create_session(telegram_user_id, current_ts)
            self.logger.info(
                "Created new session correlation_id=%s telegram_user_id=%s session_id=%s",
                correlation_id,
                telegram_user_id,
                session_id,
            )
        else:
            session_id = int(session["id"])

        self.repository.add_message(session_id, message, summary_text, current_ts)
        self.repository.update_session_activity(session_id, current_ts)

        recent_messages = self.repository.get_recent_messages(session_id, self.context_size)
        personal_memory = self.repository.get_personal_memory(telegram_user_id)
        summaries = self.repository.get_recent_summaries(telegram_user_id, self.summary_count)
        selected_personal, selected_summaries, budget_info = select_memory_with_budget(
            personal_memory,
            summaries,
            self.memory_budget,
        )
        instructions = build_reply_instructions(
            self.base_system_prompt,
            selected_personal,
            selected_summaries,
        )
        prompt_preview = build_prompt_preview(
            self.base_system_prompt,
            selected_personal,
            selected_summaries,
            recent_messages,
        )
        self.logger.debug(
            "Prepared prompt correlation_id=%s telegram_user_id=%s session_id=%s summaries_included=%s memory_tokens=%s",
            correlation_id,
            telegram_user_id,
            session_id,
            len(selected_summaries),
            budget_info["total_tokens"],
        )
        return PreparedConversation(
            session_id=session_id,
            instructions=instructions,
            input_messages=recent_messages,
            prompt_preview=prompt_preview,
        )

    def store_assistant_reply(
        self,
        session_id: int,
        reply_text: str,
        now_ts: Optional[int] = None,
    ) -> None:
        current_ts = _normalize_ts(now_ts)
        self.repository.add_message(
            session_id=session_id,
            message=ChatMessage.from_text(role="assistant", text=reply_text),
            summary_text=f"Ассистент: {reply_text}",
            now_ts=current_ts,
        )
        self.repository.update_session_activity(session_id, current_ts)

    def reset_active_session(self, telegram_user_id: int) -> None:
        self.repository.discard_open_session(telegram_user_id)

    def summarize_expired_sessions(self, now_ts: Optional[int] = None, limit: int = 10) -> None:
        current_ts = _normalize_ts(now_ts)
        cutoff_ts = current_ts - self.session_timeout_seconds
        for session in self.repository.get_expired_open_sessions(cutoff_ts, limit=limit):
            session_id = int(session["id"])
            telegram_user_id = int(session["telegram_user_id"])
            self.repository.close_session(session_id, current_ts)
            self.logger.info(
                "Closing expired session telegram_user_id=%s session_id=%s",
                telegram_user_id,
                session_id,
            )
            self._summarize_session(
                session_id=session_id,
                telegram_user_id=telegram_user_id,
                correlation_id=f"summary-session-{session_id}",
                now_ts=current_ts,
            )

    def _summarize_stale_session_for_user(
        self,
        telegram_user_id: int,
        current_ts: int,
        correlation_id: str,
    ) -> None:
        session = self.repository.get_open_session(telegram_user_id)
        if session is None:
            return
        last_activity_at = int(session["last_activity_at"])
        if current_ts - last_activity_at <= self.session_timeout_seconds:
            return
        session_id = int(session["id"])
        self.repository.close_session(session_id, current_ts)
        self.logger.info(
            "Closing stale session before new user message correlation_id=%s telegram_user_id=%s session_id=%s",
            correlation_id,
            telegram_user_id,
            session_id,
        )
        self._summarize_session(
            session_id=session_id,
            telegram_user_id=telegram_user_id,
            correlation_id=f"{correlation_id}-summary",
            now_ts=current_ts,
        )

    def _summarize_session(
        self,
        session_id: int,
        telegram_user_id: int,
        correlation_id: str,
        now_ts: int,
    ) -> None:
        transcript = self.repository.get_session_summary_transcript(session_id)
        if not transcript:
            self.repository.mark_session_summarized(session_id, now_ts)
            return

        existing_personal = self.repository.get_personal_memory(telegram_user_id)
        summary_payload = self.openai_client.summarize_dialogue(
            transcript=transcript,
            existing_personal_memory=existing_personal,
            correlation_id=correlation_id,
            user_reference=str(telegram_user_id),
        )
        merged_personal = merge_personal_memory(existing_personal, summary_payload["personal"])
        self.repository.save_personal_memory(telegram_user_id, merged_personal, now_ts)
        self.repository.save_session_summary(
            session_id=session_id,
            telegram_user_id=telegram_user_id,
            summary_payload={"dialog_summary": summary_payload["dialog_summary"]},
            now_ts=now_ts,
        )
        self.repository.mark_session_summarized(session_id, now_ts)
        self.logger.info(
            "Session summarized correlation_id=%s telegram_user_id=%s session_id=%s personal_items=%s",
            correlation_id,
            telegram_user_id,
            session_id,
            len(merged_personal),
        )


def merge_personal_memory(
    existing_memory: Sequence[Dict[str, str]],
    new_items: Sequence[Dict[str, str]],
) -> List[Dict[str, str]]:
    merged: Dict[tuple[str, str], Dict[str, str]] = {}
    for item in list(existing_memory) + list(new_items):
        fact = item.get("fact", "").strip()
        category = item.get("category", "general").strip() or "general"
        if not fact:
            continue
        key = (category.lower(), fact.lower())
        merged[key] = {"category": category, "fact": fact}
    return list(merged.values())


def _normalize_ts(now_ts: Optional[int]) -> int:
    if now_ts is None:
        return int(time())
    return int(now_ts)

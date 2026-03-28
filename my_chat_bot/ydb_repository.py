from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any, Dict, List, Optional, Sequence

from .context_store import ChatMessage
from .memory_repository import SessionId


class YDBMemoryRepository:
    def __init__(
        self,
        endpoint: str,
        database: str,
        logger: Optional[logging.Logger] = None,
        driver: Any = None,
        pool: Any = None,
    ) -> None:
        self.endpoint = endpoint
        self.database = database
        self.logger = logger or logging.getLogger(__name__)
        self.driver = driver
        self.pool = pool
        self._ydb = None

        if self.pool is None:
            try:
                import ydb
                import ydb.iam
            except ImportError as exc:
                raise RuntimeError(
                    "YDB support requires the 'ydb' package. Add it to the Cloud Function requirements."
                ) from exc

            self._ydb = ydb
            if self.driver is None:
                self.driver = ydb.Driver(
                    endpoint=endpoint,
                    database=database,
                    credentials=ydb.iam.MetadataUrlCredentials(),
                )
                self.driver.wait(fail_fast=True, timeout=5)
            pool_cls = getattr(ydb, "QuerySessionPool", None) or getattr(ydb, "SessionPool")
            self.pool = pool_cls(self.driver)

        self._initialize()

    def _initialize(self) -> None:
        for statement in _SCHEMA_STATEMENTS:
            self.pool.execute_with_retries(statement)

    def ensure_user(self, telegram_user_id: int, now_ts: int) -> None:
        self.pool.execute_with_retries(
            """
            DECLARE $telegram_user_id AS Int64;
            DECLARE $created_at AS Uint32;
            DECLARE $updated_at AS Uint32;

            UPSERT INTO users (telegram_user_id, created_at, updated_at)
            VALUES ($telegram_user_id, $created_at, $updated_at);
            """,
            {
                "$telegram_user_id": telegram_user_id,
                "$created_at": _to_uint32_value(self._ydb, now_ts),
                "$updated_at": _to_uint32_value(self._ydb, now_ts),
            },
        )

    def get_open_session(self, telegram_user_id: int) -> Optional[Dict[str, Any]]:
        result_sets = self.pool.execute_with_retries(
            """
            DECLARE $telegram_user_id AS Int64;
            DECLARE $status AS Utf8;

            SELECT
                session_id AS id,
                telegram_user_id,
                status,
                started_at,
                last_activity_at,
                closed_at,
                summarized_at
            FROM sessions
            WHERE telegram_user_id = $telegram_user_id AND status = $status
            ORDER BY started_at DESC
            LIMIT 1;
            """,
            {
                "$telegram_user_id": telegram_user_id,
                "$status": "open",
            },
        )
        rows = _rows(result_sets)
        if not rows:
            return None
        row = rows[0]
        return {
            "id": _row_value(row, "id"),
            "telegram_user_id": int(_row_value(row, "telegram_user_id")),
            "status": str(_row_value(row, "status")),
            "started_at": int(_row_value(row, "started_at")),
            "last_activity_at": int(_row_value(row, "last_activity_at")),
            "closed_at": _nullable_int(_row_value(row, "closed_at")),
            "summarized_at": _nullable_int(_row_value(row, "summarized_at")),
        }

    def create_session(self, telegram_user_id: int, now_ts: int) -> SessionId:
        session_id = _new_identifier()
        self.pool.execute_with_retries(
            """
            DECLARE $session_id AS Utf8;
            DECLARE $telegram_user_id AS Int64;
            DECLARE $status AS Utf8;
            DECLARE $started_at AS Uint32;
            DECLARE $last_activity_at AS Uint32;
            DECLARE $closed_at AS Uint32;
            DECLARE $summarized_at AS Uint32;

            UPSERT INTO sessions (
                session_id,
                telegram_user_id,
                status,
                started_at,
                last_activity_at,
                closed_at,
                summarized_at
            )
            VALUES (
                $session_id,
                $telegram_user_id,
                $status,
                $started_at,
                $last_activity_at,
                $closed_at,
                $summarized_at
            );
            """,
            {
                "$session_id": session_id,
                "$telegram_user_id": telegram_user_id,
                "$status": "open",
                "$started_at": _to_uint32_value(self._ydb, now_ts),
                "$last_activity_at": _to_uint32_value(self._ydb, now_ts),
                "$closed_at": _to_uint32_value(self._ydb, 0),
                "$summarized_at": _to_uint32_value(self._ydb, 0),
            },
        )
        return session_id

    def update_session_activity(self, session_id: SessionId, now_ts: int) -> None:
        session = self._get_session_by_id(session_id)
        if session is None:
            return
        session["last_activity_at"] = now_ts
        self._upsert_session(session)

    def close_session(self, session_id: SessionId, now_ts: int) -> None:
        session = self._get_session_by_id(session_id)
        if session is None or session["status"] != "open":
            return
        session["status"] = "closed_pending_summary"
        session["closed_at"] = now_ts
        session["last_activity_at"] = now_ts
        self._upsert_session(session)

    def mark_session_summarized(self, session_id: SessionId, now_ts: int) -> None:
        session = self._get_session_by_id(session_id)
        if session is None:
            return
        session["status"] = "summarized"
        session["summarized_at"] = now_ts
        self._upsert_session(session)

    def discard_open_session(self, telegram_user_id: int) -> None:
        result_sets = self.pool.execute_with_retries(
            """
            DECLARE $telegram_user_id AS Int64;
            DECLARE $status AS Utf8;

            SELECT session_id
            FROM sessions
            WHERE telegram_user_id = $telegram_user_id AND status = $status;
            """,
            {
                "$telegram_user_id": telegram_user_id,
                "$status": "open",
            },
        )
        session_ids = [str(_row_value(row, "session_id")) for row in _rows(result_sets)]
        for session_id in session_ids:
            self.pool.execute_with_retries(
                """
                DECLARE $session_id AS Utf8;

                DELETE FROM messages
                WHERE session_id = $session_id;
                """,
                {"$session_id": session_id},
            )
            self.pool.execute_with_retries(
                """
                DECLARE $session_id AS Utf8;

                DELETE FROM sessions
                WHERE session_id = $session_id;
                """,
                {"$session_id": session_id},
            )

    def add_message(self, session_id: SessionId, message: ChatMessage, summary_text: str, now_ts: int) -> None:
        self.pool.execute_with_retries(
            """
            DECLARE $session_id AS Utf8;
            DECLARE $message_id AS Utf8;
            DECLARE $role AS Utf8;
            DECLARE $created_at AS Uint32;
            DECLARE $content_json AS Utf8;
            DECLARE $summary_text AS Utf8;

            UPSERT INTO messages (
                session_id,
                message_id,
                role,
                created_at,
                content_json,
                summary_text
            )
            VALUES (
                $session_id,
                $message_id,
                $role,
                $created_at,
                $content_json,
                $summary_text
            );
            """,
            {
                "$session_id": str(session_id),
                "$message_id": _new_identifier(),
                "$role": message.role,
                "$created_at": _to_uint32_value(self._ydb, now_ts),
                "$content_json": json.dumps(message.to_storage_dict(), ensure_ascii=False),
                "$summary_text": summary_text,
            },
        )

    def get_recent_messages(self, session_id: SessionId, limit: int) -> List[ChatMessage]:
        if limit <= 0:
            return []
        result_sets = self.pool.execute_with_retries(
            f"""
            DECLARE $session_id AS Utf8;

            SELECT content_json
            FROM messages
            WHERE session_id = $session_id
            ORDER BY created_at DESC, message_id DESC
            LIMIT {int(limit)};
            """,
            {"$session_id": str(session_id)},
        )
        rows = list(reversed(_rows(result_sets)))
        return [ChatMessage.from_storage_dict(json.loads(str(_row_value(row, "content_json")))) for row in rows]

    def get_session_summary_transcript(self, session_id: SessionId) -> str:
        result_sets = self.pool.execute_with_retries(
            """
            DECLARE $session_id AS Utf8;

            SELECT summary_text
            FROM messages
            WHERE session_id = $session_id
            ORDER BY created_at ASC, message_id ASC;
            """,
            {"$session_id": str(session_id)},
        )
        lines = [str(_row_value(row, "summary_text")) for row in _rows(result_sets) if _row_value(row, "summary_text")]
        return "\n".join(lines).strip()

    def get_expired_open_sessions(self, cutoff_ts: int, limit: int = 20) -> List[Dict[str, Any]]:
        result_sets = self.pool.execute_with_retries(
            f"""
            DECLARE $status AS Utf8;
            DECLARE $cutoff_ts AS Uint32;

            SELECT
                session_id AS id,
                telegram_user_id,
                status,
                started_at,
                last_activity_at,
                closed_at,
                summarized_at
            FROM sessions
            WHERE status = $status AND last_activity_at <= $cutoff_ts
            ORDER BY last_activity_at ASC
            LIMIT {int(limit)};
            """,
            {
                "$status": "open",
                "$cutoff_ts": _to_uint32_value(self._ydb, cutoff_ts),
            },
        )
        return [
            {
                "id": _row_value(row, "id"),
                "telegram_user_id": int(_row_value(row, "telegram_user_id")),
                "status": str(_row_value(row, "status")),
                "started_at": int(_row_value(row, "started_at")),
                "last_activity_at": int(_row_value(row, "last_activity_at")),
                "closed_at": _nullable_int(_row_value(row, "closed_at")),
                "summarized_at": _nullable_int(_row_value(row, "summarized_at")),
            }
            for row in _rows(result_sets)
        ]

    def get_personal_memory(self, telegram_user_id: int) -> List[Dict[str, str]]:
        result_sets = self.pool.execute_with_retries(
            """
            DECLARE $telegram_user_id AS Int64;

            SELECT content_json
            FROM personal_memory
            WHERE telegram_user_id = $telegram_user_id
            LIMIT 1;
            """,
            {"$telegram_user_id": telegram_user_id},
        )
        rows = _rows(result_sets)
        if not rows:
            return []
        payload = json.loads(str(_row_value(rows[0], "content_json")))
        return [dict(item) for item in payload]

    def save_personal_memory(
        self,
        telegram_user_id: int,
        personal_memory: Sequence[Dict[str, str]],
        now_ts: int,
    ) -> None:
        self.pool.execute_with_retries(
            """
            DECLARE $telegram_user_id AS Int64;
            DECLARE $content_json AS Utf8;
            DECLARE $updated_at AS Uint32;

            UPSERT INTO personal_memory (telegram_user_id, content_json, updated_at)
            VALUES ($telegram_user_id, $content_json, $updated_at);
            """,
            {
                "$telegram_user_id": telegram_user_id,
                "$content_json": json.dumps(list(personal_memory), ensure_ascii=False),
                "$updated_at": _to_uint32_value(self._ydb, now_ts),
            },
        )

    def get_recent_summaries(self, telegram_user_id: int, limit: int) -> List[Dict[str, Any]]:
        result_sets = self.pool.execute_with_retries(
            f"""
            DECLARE $telegram_user_id AS Int64;

            SELECT session_id, summary_json, created_at
            FROM session_summaries
            WHERE telegram_user_id = $telegram_user_id
            ORDER BY created_at DESC
            LIMIT {int(limit)};
            """,
            {"$telegram_user_id": telegram_user_id},
        )
        results: List[Dict[str, Any]] = []
        for row in _rows(result_sets):
            payload = json.loads(str(_row_value(row, "summary_json")))
            payload["session_id"] = _row_value(row, "session_id")
            payload["created_at"] = int(_row_value(row, "created_at"))
            results.append(payload)
        return results

    def save_session_summary(
        self,
        session_id: SessionId,
        telegram_user_id: int,
        summary_payload: Dict[str, Any],
        now_ts: int,
    ) -> None:
        self.pool.execute_with_retries(
            """
            DECLARE $session_id AS Utf8;
            DECLARE $telegram_user_id AS Int64;
            DECLARE $summary_json AS Utf8;
            DECLARE $created_at AS Uint32;

            UPSERT INTO session_summaries (session_id, telegram_user_id, summary_json, created_at)
            VALUES ($session_id, $telegram_user_id, $summary_json, $created_at);
            """,
            {
                "$session_id": str(session_id),
                "$telegram_user_id": telegram_user_id,
                "$summary_json": json.dumps(summary_payload, ensure_ascii=False),
                "$created_at": _to_uint32_value(self._ydb, now_ts),
            },
        )

    def get_web_client(self, session_token: str) -> Optional[Dict[str, Any]]:
        result_sets = self.pool.execute_with_retries(
            """
            DECLARE $session_token AS Utf8;

            SELECT session_token, memory_user_id, linked_telegram_user_id, created_at, updated_at
            FROM web_clients
            WHERE session_token = $session_token
            LIMIT 1;
            """,
            {"$session_token": session_token},
        )
        rows = _rows(result_sets)
        if not rows:
            return None
        row = rows[0]
        return {
            "session_token": str(_row_value(row, "session_token")),
            "memory_user_id": int(_row_value(row, "memory_user_id")),
            "linked_telegram_user_id": _nullable_int(_row_value(row, "linked_telegram_user_id")),
            "created_at": int(_row_value(row, "created_at")),
            "updated_at": int(_row_value(row, "updated_at")),
        }

    def create_web_client(
        self,
        session_token: str,
        memory_user_id: int,
        linked_telegram_user_id: Optional[int],
        now_ts: int,
    ) -> None:
        self.pool.execute_with_retries(
            """
            DECLARE $session_token AS Utf8;
            DECLARE $memory_user_id AS Int64;
            DECLARE $linked_telegram_user_id AS Int64;
            DECLARE $created_at AS Uint32;
            DECLARE $updated_at AS Uint32;

            UPSERT INTO web_clients (
                session_token,
                memory_user_id,
                linked_telegram_user_id,
                created_at,
                updated_at
            )
            VALUES (
                $session_token,
                $memory_user_id,
                $linked_telegram_user_id,
                $created_at,
                $updated_at
            );
            """,
            {
                "$session_token": session_token,
                "$memory_user_id": memory_user_id,
                "$linked_telegram_user_id": linked_telegram_user_id or 0,
                "$created_at": _to_uint32_value(self._ydb, now_ts),
                "$updated_at": _to_uint32_value(self._ydb, now_ts),
            },
        )

    def update_web_client_link(
        self,
        session_token: str,
        memory_user_id: int,
        linked_telegram_user_id: Optional[int],
        now_ts: int,
    ) -> None:
        row = self.get_web_client(session_token)
        created_at = now_ts if row is None else int(row["created_at"])
        self.pool.execute_with_retries(
            """
            DECLARE $session_token AS Utf8;
            DECLARE $memory_user_id AS Int64;
            DECLARE $linked_telegram_user_id AS Int64;
            DECLARE $created_at AS Uint32;
            DECLARE $updated_at AS Uint32;

            UPSERT INTO web_clients (
                session_token,
                memory_user_id,
                linked_telegram_user_id,
                created_at,
                updated_at
            )
            VALUES (
                $session_token,
                $memory_user_id,
                $linked_telegram_user_id,
                $created_at,
                $updated_at
            );
            """,
            {
                "$session_token": session_token,
                "$memory_user_id": memory_user_id,
                "$linked_telegram_user_id": linked_telegram_user_id or 0,
                "$created_at": _to_uint32_value(self._ydb, created_at),
                "$updated_at": _to_uint32_value(self._ydb, now_ts),
            },
        )

    def get_next_anonymous_user_id(self) -> int:
        return -(int(time.time() * 1000) * 1000 + secrets.randbelow(1000) + 1)

    def create_link_code(self, code: str, telegram_user_id: int, created_at: int, expires_at: int) -> None:
        self.pool.execute_with_retries(
            """
            DECLARE $code AS Utf8;
            DECLARE $telegram_user_id AS Int64;
            DECLARE $created_at AS Uint32;
            DECLARE $expires_at AS Uint32;
            DECLARE $used_at AS Uint32;

            UPSERT INTO link_codes (code, telegram_user_id, created_at, expires_at, used_at)
            VALUES ($code, $telegram_user_id, $created_at, $expires_at, $used_at);
            """,
            {
                "$code": code,
                "$telegram_user_id": telegram_user_id,
                "$created_at": _to_uint32_value(self._ydb, created_at),
                "$expires_at": _to_uint32_value(self._ydb, expires_at),
                "$used_at": _to_uint32_value(self._ydb, 0),
            },
        )

    def consume_link_code(self, code: str, now_ts: int) -> Optional[int]:
        result_sets = self.pool.execute_with_retries(
            """
            DECLARE $code AS Utf8;

            SELECT code, telegram_user_id, created_at, expires_at, used_at
            FROM link_codes
            WHERE code = $code
            LIMIT 1;
            """,
            {"$code": code},
        )
        rows = _rows(result_sets)
        if not rows:
            return None
        row = rows[0]
        expires_at = int(_row_value(row, "expires_at"))
        used_at = int(_row_value(row, "used_at"))
        if used_at != 0 or expires_at < now_ts:
            return None
        telegram_user_id = int(_row_value(row, "telegram_user_id"))
        self.pool.execute_with_retries(
            """
            DECLARE $code AS Utf8;
            DECLARE $telegram_user_id AS Int64;
            DECLARE $created_at AS Uint32;
            DECLARE $expires_at AS Uint32;
            DECLARE $used_at AS Uint32;

            UPSERT INTO link_codes (code, telegram_user_id, created_at, expires_at, used_at)
            VALUES ($code, $telegram_user_id, $created_at, $expires_at, $used_at);
            """,
            {
                "$code": code,
                "$telegram_user_id": telegram_user_id,
                "$created_at": _to_uint32_value(self._ydb, int(_row_value(row, "created_at"))),
                "$expires_at": _to_uint32_value(self._ydb, expires_at),
                "$used_at": _to_uint32_value(self._ydb, now_ts),
            },
        )
        return telegram_user_id

    def get_active_session_messages_for_user(self, telegram_user_id: int, limit: int) -> List[ChatMessage]:
        session = self.get_open_session(telegram_user_id)
        if session is None:
            return []
        return self.get_recent_messages(session["id"], limit)

    def _get_session_by_id(self, session_id: SessionId) -> Optional[Dict[str, Any]]:
        result_sets = self.pool.execute_with_retries(
            """
            DECLARE $session_id AS Utf8;

            SELECT
                session_id AS id,
                telegram_user_id,
                status,
                started_at,
                last_activity_at,
                closed_at,
                summarized_at
            FROM sessions
            WHERE session_id = $session_id
            LIMIT 1;
            """,
            {"$session_id": str(session_id)},
        )
        rows = _rows(result_sets)
        if not rows:
            return None
        row = rows[0]
        return {
            "id": str(_row_value(row, "id")),
            "telegram_user_id": int(_row_value(row, "telegram_user_id")),
            "status": str(_row_value(row, "status")),
            "started_at": int(_row_value(row, "started_at")),
            "last_activity_at": int(_row_value(row, "last_activity_at")),
            "closed_at": _nullable_int(_row_value(row, "closed_at")),
            "summarized_at": _nullable_int(_row_value(row, "summarized_at")),
        }

    def _upsert_session(self, session: Dict[str, Any]) -> None:
        self.pool.execute_with_retries(
            """
            DECLARE $session_id AS Utf8;
            DECLARE $telegram_user_id AS Int64;
            DECLARE $status AS Utf8;
            DECLARE $started_at AS Uint32;
            DECLARE $last_activity_at AS Uint32;
            DECLARE $closed_at AS Uint32;
            DECLARE $summarized_at AS Uint32;

            UPSERT INTO sessions (
                session_id,
                telegram_user_id,
                status,
                started_at,
                last_activity_at,
                closed_at,
                summarized_at
            )
            VALUES (
                $session_id,
                $telegram_user_id,
                $status,
                $started_at,
                $last_activity_at,
                $closed_at,
                $summarized_at
            );
            """,
            {
                "$session_id": str(session["id"]),
                "$telegram_user_id": int(session["telegram_user_id"]),
                "$status": str(session["status"]),
                "$started_at": _to_uint32_value(self._ydb, int(session["started_at"])),
                "$last_activity_at": _to_uint32_value(self._ydb, int(session["last_activity_at"])),
                "$closed_at": _to_uint32_value(self._ydb, int(session.get("closed_at") or 0)),
                "$summarized_at": _to_uint32_value(self._ydb, int(session.get("summarized_at") or 0)),
            },
        )


def _rows(result_sets: Any) -> List[Any]:
    if not result_sets:
        return []
    first = result_sets[0]
    return list(getattr(first, "rows", []))


def _row_value(row: Any, name: str) -> Any:
    if isinstance(row, dict):
        return row[name]
    if hasattr(row, name):
        return getattr(row, name)
    if hasattr(row, "items"):
        return dict(row.items())[name]
    raise KeyError(name)


def _nullable_int(value: Any) -> Optional[int]:
    if value in (None, 0, "0"):
        return None
    return int(value)


def _to_uint32_value(ydb_module: Any, value: int) -> Any:
    normalized = max(0, int(value))
    if ydb_module is None:
        return normalized

    value_cls = getattr(ydb_module, "Value", None)
    if value_cls is not None and hasattr(value_cls, "from_uint32"):
        return value_cls.from_uint32(normalized)

    primitive_type = getattr(getattr(ydb_module, "PrimitiveType", None), "Uint32", None)
    typed_value = getattr(ydb_module, "TypedValue", None)
    if primitive_type is not None and typed_value is not None:
        return typed_value(normalized, primitive_type)

    return normalized


def _new_identifier() -> str:
    return f"{time.time_ns():020d}-{secrets.randbelow(10000):04d}"


_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        telegram_user_id Int64,
        created_at Uint32,
        updated_at Uint32,
        PRIMARY KEY (telegram_user_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id Utf8,
        telegram_user_id Int64,
        status Utf8,
        started_at Uint32,
        last_activity_at Uint32,
        closed_at Uint32,
        summarized_at Uint32,
        PRIMARY KEY (session_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        session_id Utf8,
        message_id Utf8,
        role Utf8,
        created_at Uint32,
        content_json Utf8,
        summary_text Utf8,
        PRIMARY KEY (session_id, message_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS personal_memory (
        telegram_user_id Int64,
        content_json Utf8,
        updated_at Uint32,
        PRIMARY KEY (telegram_user_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS session_summaries (
        session_id Utf8,
        telegram_user_id Int64,
        summary_json Utf8,
        created_at Uint32,
        PRIMARY KEY (session_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS web_clients (
        session_token Utf8,
        memory_user_id Int64,
        linked_telegram_user_id Int64,
        created_at Uint32,
        updated_at Uint32,
        PRIMARY KEY (session_token)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS link_codes (
        code Utf8,
        telegram_user_id Int64,
        created_at Uint32,
        expires_at Uint32,
        used_at Uint32,
        PRIMARY KEY (code)
    );
    """,
]

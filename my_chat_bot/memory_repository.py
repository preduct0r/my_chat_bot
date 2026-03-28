from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Sequence, Union

from .context_store import ChatMessage

SessionId = Union[int, str]
Record = Dict[str, Any]


class MemoryRepository(Protocol):
    def ensure_user(self, telegram_user_id: int, now_ts: int) -> None:
        ...

    def get_open_session(self, telegram_user_id: int) -> Optional[Record]:
        ...

    def create_session(self, telegram_user_id: int, now_ts: int) -> SessionId:
        ...

    def update_session_activity(self, session_id: SessionId, now_ts: int) -> None:
        ...

    def close_session(self, session_id: SessionId, now_ts: int) -> None:
        ...

    def mark_session_summarized(self, session_id: SessionId, now_ts: int) -> None:
        ...

    def discard_open_session(self, telegram_user_id: int) -> None:
        ...

    def add_message(self, session_id: SessionId, message: ChatMessage, summary_text: str, now_ts: int) -> None:
        ...

    def get_recent_messages(self, session_id: SessionId, limit: int) -> List[ChatMessage]:
        ...

    def get_session_summary_transcript(self, session_id: SessionId) -> str:
        ...

    def get_expired_open_sessions(self, cutoff_ts: int, limit: int = 20) -> List[Record]:
        ...

    def get_personal_memory(self, telegram_user_id: int) -> List[Dict[str, str]]:
        ...

    def save_personal_memory(
        self,
        telegram_user_id: int,
        personal_memory: Sequence[Dict[str, str]],
        now_ts: int,
    ) -> None:
        ...

    def get_recent_summaries(self, telegram_user_id: int, limit: int) -> List[Dict[str, Any]]:
        ...

    def save_session_summary(
        self,
        session_id: SessionId,
        telegram_user_id: int,
        summary_payload: Dict[str, Any],
        now_ts: int,
    ) -> None:
        ...

    def get_web_client(self, session_token: str) -> Optional[Record]:
        ...

    def create_web_client(
        self,
        session_token: str,
        memory_user_id: int,
        linked_telegram_user_id: Optional[int],
        now_ts: int,
    ) -> None:
        ...

    def update_web_client_link(
        self,
        session_token: str,
        memory_user_id: int,
        linked_telegram_user_id: Optional[int],
        now_ts: int,
    ) -> None:
        ...

    def get_next_anonymous_user_id(self) -> int:
        ...

    def create_link_code(self, code: str, telegram_user_id: int, created_at: int, expires_at: int) -> None:
        ...

    def consume_link_code(self, code: str, now_ts: int) -> Optional[int]:
        ...

    def get_active_session_messages_for_user(self, telegram_user_id: int, limit: int) -> List[ChatMessage]:
        ...

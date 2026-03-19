from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Mapping, MutableMapping, Tuple


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: Tuple[Mapping[str, str], ...]

    @classmethod
    def from_text(cls, role: str, text: str) -> "ChatMessage":
        return cls(role=role, content=({"type": _content_type_for_role(role), "text": text},))

    @classmethod
    def from_storage_dict(cls, payload: Mapping[str, Any]) -> "ChatMessage":
        role = payload.get("role")
        raw_content = payload.get("content")
        if not isinstance(role, str) or not isinstance(raw_content, list):
            raise ValueError(f"Invalid stored chat message payload: {payload}")
        content: List[Mapping[str, str]] = []
        for part in raw_content:
            if not isinstance(part, dict):
                raise ValueError(f"Invalid stored message content part: {part}")
            normalized = {str(key): str(value) for key, value in part.items()}
            content.append(normalized)
        return cls(role=role, content=tuple(content))

    def to_openai_input(self) -> Mapping[str, object]:
        return {"role": self.role, "content": [dict(part) for part in self.content]}

    def to_storage_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "content": [dict(part) for part in self.content]}

    def to_preview_text(self) -> str:
        parts: List[str] = []
        for part in self.content:
            part_type = part.get("type")
            if part_type in {"input_text", "output_text"} and part.get("text"):
                parts.append(part["text"])
            elif part_type == "input_file":
                parts.append(f"[file: {part.get('filename', 'document')}]")
            elif part_type == "input_image":
                parts.append("[image]")
        if not parts:
            return "[empty]"
        return " ".join(parts)


def _content_type_for_role(role: str) -> str:
    if role == "assistant":
        return "output_text"
    return "input_text"


class RecentMessageStore:
    """Stores only the latest N messages per chat."""

    def __init__(self, max_messages: int) -> None:
        if max_messages <= 0:
            raise ValueError("max_messages must be a positive integer")
        self.max_messages = max_messages
        self._messages: MutableMapping[int, Deque[ChatMessage]] = defaultdict(
            lambda: deque(maxlen=max_messages)
        )

    def append(self, chat_id: int, message: ChatMessage) -> None:
        self._messages[chat_id].append(message)

    def get(self, chat_id: int) -> List[ChatMessage]:
        return list(self._messages.get(chat_id, ()))

    def clear(self, chat_id: int) -> None:
        self._messages.pop(chat_id, None)

    def snapshot(self) -> Dict[int, List[ChatMessage]]:
        return {chat_id: list(messages) for chat_id, messages in self._messages.items()}

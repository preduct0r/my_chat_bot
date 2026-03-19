from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Mapping, MutableMapping, Tuple


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: Tuple[Mapping[str, str], ...]

    @classmethod
    def from_text(cls, role: str, text: str) -> "ChatMessage":
        return cls(role=role, content=({"type": _content_type_for_role(role), "text": text},))

    def to_openai_input(self) -> Mapping[str, object]:
        return {"role": self.role, "content": [dict(part) for part in self.content]}


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

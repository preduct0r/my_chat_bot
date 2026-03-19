from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Mapping, MutableMapping


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def to_openai_input(self) -> Mapping[str, str]:
        return {"role": self.role, "content": self.content}


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


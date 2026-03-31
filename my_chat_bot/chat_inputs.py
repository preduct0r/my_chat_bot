from __future__ import annotations

from typing import Dict, List, Sequence

from .attachments import IncomingAttachment
from .context_store import ChatMessage

DEFAULT_ATTACHMENT_PROMPT = "Опиши вложение и ответь по нему."
SUPPORTED_ATTACHMENT_MESSAGE = (
    "Поддерживаются текстовые сообщения, изображения, PDF, DOC, DOCX, XLSX и текстовые файлы."
)


def build_user_message(prompt_text: str, attachments: Sequence[IncomingAttachment]) -> ChatMessage:
    content_parts: List[Dict[str, str]] = [{"type": "input_text", "text": prompt_text}]
    for attachment in attachments:
        content_parts.extend(attachment.to_content_parts())
    return ChatMessage(role="user", content=tuple(content_parts))


def build_user_summary_text(prompt_text: str, attachments: Sequence[IncomingAttachment]) -> str:
    attachment_descriptions = [attachment.summary_description() for attachment in attachments]
    lines = [f"Пользователь: {prompt_text}"]
    lines.extend(attachment_descriptions)
    return "\n".join(lines)

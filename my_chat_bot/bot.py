from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .attachments import IncomingAttachment, classify_attachment
from .context_store import ChatMessage
from .http_utils import ExternalServiceError
from .memory import MemoryService
from .openai_client import OpenAIResponsesClient
from .telegram_client import TelegramClient

DEFAULT_ATTACHMENT_PROMPT = "Опиши вложение и ответь по нему."
SUPPORTED_ATTACHMENT_MESSAGE = (
    "Поддерживаются текстовые сообщения, изображения, PDF, DOC, DOCX, XLSX и текстовые файлы."
)


class TelegramBotApp:
    def __init__(
        self,
        telegram_client: TelegramClient,
        openai_client: OpenAIResponsesClient,
        memory_service: MemoryService,
        poll_timeout: int,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.telegram_client = telegram_client
        self.openai_client = openai_client
        self.memory_service = memory_service
        self.poll_timeout = poll_timeout
        self.logger = logger or logging.getLogger(__name__)

    def run_forever(self) -> None:
        offset: Optional[int] = None
        last_maintenance_ts = 0.0
        self.logger.info(
            "Starting Telegram polling poll_timeout=%s",
            self.poll_timeout,
        )
        while True:
            try:
                if time.time() - last_maintenance_ts >= 60:
                    self.memory_service.summarize_expired_sessions()
                    last_maintenance_ts = time.time()
                updates = self.telegram_client.get_updates(offset=offset, poll_timeout=self.poll_timeout)
                for update in updates:
                    update_id = update.get("update_id")
                    self.handle_update(update)
                    if isinstance(update_id, int):
                        offset = update_id + 1
            except KeyboardInterrupt:
                self.logger.info("Stopping bot by user request")
                raise
            except ExternalServiceError:
                self.logger.exception("External service error during polling; retrying shortly")
                time.sleep(2)
            except Exception:
                self.logger.exception("Unexpected bot error; retrying shortly")
                time.sleep(2)

    def handle_update(self, update: Dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            self.logger.debug("Skipping update without message payload update=%s", update)
            return

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            self.logger.warning("Skipping message without valid chat_id update=%s", update)
            return

        text = message.get("text")
        caption = message.get("caption")
        message_id = message.get("message_id")
        update_id = update.get("update_id", "unknown")
        user_id = message.get("from", {}).get("id")
        correlation_id = f"tg-{update_id}"
        if not isinstance(user_id, int):
            self.logger.warning("Skipping message without valid user_id update=%s", update)
            return

        self.logger.info(
            "Received Telegram update correlation_id=%s chat_id=%s user_id=%s",
            correlation_id,
            chat_id,
            user_id,
        )

        attachments: List[IncomingAttachment]
        try:
            attachments = self._extract_attachments(message, correlation_id)
        except ValueError:
            self.logger.warning(
                "Unsupported attachment correlation_id=%s chat_id=%s",
                correlation_id,
                chat_id,
            )
            self.telegram_client.send_message(
                chat_id=chat_id,
                text=SUPPORTED_ATTACHMENT_MESSAGE,
                reply_to_message_id=message_id if isinstance(message_id, int) else None,
            )
            return
        except ExternalServiceError:
            self.logger.exception(
                "Failed to download attachment correlation_id=%s chat_id=%s",
                correlation_id,
                chat_id,
            )
            self.telegram_client.send_message(
                chat_id=chat_id,
                text="Не удалось скачать вложение из Telegram. Попробуйте отправить его еще раз.",
                reply_to_message_id=message_id if isinstance(message_id, int) else None,
            )
            return

        raw_text = text if isinstance(text, str) else caption if isinstance(caption, str) else ""
        clean_text = raw_text.strip()
        if not clean_text and not attachments:
            self.telegram_client.send_message(
                chat_id=chat_id,
                text=SUPPORTED_ATTACHMENT_MESSAGE,
                reply_to_message_id=message_id if isinstance(message_id, int) else None,
            )
            self.logger.debug("Rejected unsupported message correlation_id=%s chat_id=%s", correlation_id, chat_id)
            return

        if clean_text == "/start" and not attachments:
            self.telegram_client.send_message(
                chat_id=chat_id,
                text=(
                    "Бот запущен. Отправьте сообщение, и я отвечу через OpenAI. "
                    "Можно присылать текст, фото, PDF, DOC, DOCX, XLSX и текстовые файлы. "
                    "В контексте хранятся только последние сообщения текущего чата."
                ),
                reply_to_message_id=message_id if isinstance(message_id, int) else None,
            )
            return

        if clean_text == "/reset" and not attachments:
            self.memory_service.reset_active_session(user_id)
            self.telegram_client.send_message(
                chat_id=chat_id,
                text="Активная сессия очищена. Долговременная память пользователя сохранена.",
                reply_to_message_id=message_id if isinstance(message_id, int) else None,
            )
            self.logger.info("Active session cleared correlation_id=%s chat_id=%s", correlation_id, chat_id)
            return

        if clean_text == "/link" and not attachments:
            link_code = self.memory_service.create_telegram_link_code(user_id)
            self.telegram_client.send_message(
                chat_id=chat_id,
                text=(
                    "Код для привязки web-интерфейса к этому Telegram-пользователю:\n"
                    f"`{link_code}`\n\n"
                    "Введите его в web-форме в течение 10 минут."
                ),
                reply_to_message_id=message_id if isinstance(message_id, int) else None,
            )
            self.logger.info("Telegram link code generated correlation_id=%s chat_id=%s", correlation_id, chat_id)
            return

        prompt_text = clean_text or DEFAULT_ATTACHMENT_PROMPT
        user_message = self._build_user_message(prompt_text, attachments)
        user_summary_text = self._build_user_summary_text(prompt_text, attachments)
        try:
            prepared = self.memory_service.prepare_conversation(
                telegram_user_id=user_id,
                message=user_message,
                summary_text=user_summary_text,
                correlation_id=correlation_id,
            )
            self.logger.debug(
                "Prepared final prompt correlation_id=%s prompt_preview=%s",
                correlation_id,
                prepared.prompt_preview,
            )
            assistant_reply = self.openai_client.generate_reply(
                messages=prepared.input_messages,
                correlation_id=correlation_id,
                user_reference=str(user_id),
                instructions=prepared.instructions,
            )
        except ExternalServiceError:
            self.logger.exception(
                "OpenAI request failed correlation_id=%s chat_id=%s",
                correlation_id,
                chat_id,
            )
            self.telegram_client.send_message(
                chat_id=chat_id,
                text="Не удалось получить ответ от модели. Попробуйте еще раз чуть позже.",
                reply_to_message_id=message_id if isinstance(message_id, int) else None,
            )
            return

        self.memory_service.store_assistant_reply(
            session_id=prepared.session_id,
            reply_text=assistant_reply,
        )
        self.telegram_client.send_message(
            chat_id=chat_id,
            text=assistant_reply,
            reply_to_message_id=message_id if isinstance(message_id, int) else None,
        )
        self.logger.info(
            "Reply sent correlation_id=%s chat_id=%s session_id=%s",
            correlation_id,
            chat_id,
            prepared.session_id,
        )

    def _build_user_message(
        self,
        prompt_text: str,
        attachments: List[IncomingAttachment],
    ) -> ChatMessage:
        content_parts: List[Dict[str, str]] = [{"type": "input_text", "text": prompt_text}]
        for attachment in attachments:
            content_parts.extend(attachment.to_content_parts())
        return ChatMessage(role="user", content=tuple(content_parts))

    def _build_user_summary_text(self, prompt_text: str, attachments: List[IncomingAttachment]) -> str:
        attachment_descriptions = [attachment.summary_description() for attachment in attachments]
        lines = [f"Пользователь: {prompt_text}"]
        lines.extend(attachment_descriptions)
        return "\n".join(lines)

    def _extract_attachments(
        self,
        message: Dict[str, Any],
        correlation_id: str,
    ) -> List[IncomingAttachment]:
        attachments: List[IncomingAttachment] = []

        photo_sizes = message.get("photo")
        if isinstance(photo_sizes, list) and photo_sizes:
            largest_photo = max(
                (photo for photo in photo_sizes if isinstance(photo, dict)),
                key=lambda item: item.get("file_size", 0),
            )
            file_id = largest_photo.get("file_id")
            if isinstance(file_id, str):
                attachments.append(
                    self._download_attachment(
                        file_id=file_id,
                        fallback_filename="photo.jpg",
                        fallback_mime_type="image/jpeg",
                        correlation_id=correlation_id,
                    )
                )

        document = message.get("document")
        if isinstance(document, dict):
            file_id = document.get("file_id")
            filename = document.get("file_name") or "document"
            mime_type = document.get("mime_type") or ""
            if isinstance(file_id, str):
                attachments.append(
                    self._download_attachment(
                        file_id=file_id,
                        fallback_filename=str(filename),
                        fallback_mime_type=str(mime_type),
                        correlation_id=correlation_id,
                    )
                )

        return attachments

    def _download_attachment(
        self,
        file_id: str,
        fallback_filename: str,
        fallback_mime_type: str,
        correlation_id: str,
    ) -> IncomingAttachment:
        file_info = self.telegram_client.get_file(file_id)
        file_path = file_info["file_path"]
        file_bytes = self.telegram_client.download_file(file_path)
        mime_type = str(file_info.get("mime_type") or fallback_mime_type or "")
        filename = str(file_info.get("file_name") or fallback_filename)
        kind = classify_attachment(filename=filename, mime_type=mime_type)
        self.logger.info(
            "Downloaded attachment correlation_id=%s file_id=%s kind=%s filename=%s size_bytes=%s",
            correlation_id,
            file_id,
            kind,
            filename,
            len(file_bytes),
        )
        return IncomingAttachment(
            kind=kind,
            filename=filename,
            mime_type=mime_type or _infer_mime_type_from_kind(kind),
            data=file_bytes,
        )


def _infer_mime_type_from_kind(kind: str) -> str:
    if kind == "image":
        return "image/jpeg"
    if kind == "pdf":
        return "application/pdf"
    if kind == "rich_document":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if kind == "spreadsheet":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return "text/plain"

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from .context_store import ChatMessage, RecentMessageStore
from .http_utils import ExternalServiceError
from .openai_client import OpenAIResponsesClient
from .telegram_client import TelegramClient


class TelegramBotApp:
    def __init__(
        self,
        telegram_client: TelegramClient,
        openai_client: OpenAIResponsesClient,
        context_store: RecentMessageStore,
        poll_timeout: int,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.telegram_client = telegram_client
        self.openai_client = openai_client
        self.context_store = context_store
        self.poll_timeout = poll_timeout
        self.logger = logger or logging.getLogger(__name__)

    def run_forever(self) -> None:
        offset: Optional[int] = None
        self.logger.info(
            "Starting Telegram polling context_size=%s poll_timeout=%s",
            self.context_store.max_messages,
            self.poll_timeout,
        )
        while True:
            try:
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
        message_id = message.get("message_id")
        update_id = update.get("update_id", "unknown")
        user_id = message.get("from", {}).get("id", "unknown")
        correlation_id = f"tg-{update_id}"

        self.logger.info(
            "Received Telegram update correlation_id=%s chat_id=%s user_id=%s",
            correlation_id,
            chat_id,
            user_id,
        )

        if not isinstance(text, str) or not text.strip():
            self.telegram_client.send_message(
                chat_id=chat_id,
                text="Пока поддерживаются только текстовые сообщения.",
                reply_to_message_id=message_id if isinstance(message_id, int) else None,
            )
            self.logger.debug(
                "Rejected non-text message correlation_id=%s chat_id=%s",
                correlation_id,
                chat_id,
            )
            return

        clean_text = text.strip()
        if clean_text == "/start":
            self.telegram_client.send_message(
                chat_id=chat_id,
                text=(
                    "Бот запущен. Отправьте сообщение, и я отвечу через OpenAI. "
                    "В контексте хранятся только последние сообщения текущего чата."
                ),
                reply_to_message_id=message_id if isinstance(message_id, int) else None,
            )
            return

        if clean_text == "/reset":
            self.context_store.clear(chat_id)
            self.telegram_client.send_message(
                chat_id=chat_id,
                text="Контекст чата очищен.",
                reply_to_message_id=message_id if isinstance(message_id, int) else None,
            )
            self.logger.info("Context cleared correlation_id=%s chat_id=%s", correlation_id, chat_id)
            return

        history = self.context_store.get(chat_id)
        self.logger.debug(
            "Preparing OpenAI request correlation_id=%s chat_id=%s history_messages=%s",
            correlation_id,
            chat_id,
            len(history),
        )

        request_messages = history + [ChatMessage(role="user", content=clean_text)]
        try:
            assistant_reply = self.openai_client.generate_reply(
                messages=request_messages,
                correlation_id=correlation_id,
                user_reference=str(user_id),
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

        self.context_store.append(chat_id, ChatMessage(role="user", content=clean_text))
        self.context_store.append(chat_id, ChatMessage(role="assistant", content=assistant_reply))
        self.telegram_client.send_message(
            chat_id=chat_id,
            text=assistant_reply,
            reply_to_message_id=message_id if isinstance(message_id, int) else None,
        )
        self.logger.info(
            "Reply sent correlation_id=%s chat_id=%s stored_messages=%s",
            correlation_id,
            chat_id,
            len(self.context_store.get(chat_id)),
        )


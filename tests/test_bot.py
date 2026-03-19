import unittest

from my_chat_bot.bot import TelegramBotApp
from my_chat_bot.context_store import ChatMessage, RecentMessageStore
from my_chat_bot.http_utils import ExternalServiceError


class FakeTelegramClient:
    def __init__(self) -> None:
        self.sent_messages = []

    def send_message(self, chat_id, text, reply_to_message_id=None) -> None:
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
            }
        )


class FakeOpenAIClient:
    def __init__(self, reply="Ответ модели", error=None) -> None:
        self.reply = reply
        self.error = error
        self.calls = []

    def generate_reply(self, messages, correlation_id, user_reference):
        self.calls.append(
            {
                "messages": list(messages),
                "correlation_id": correlation_id,
                "user_reference": user_reference,
            }
        )
        if self.error is not None:
            raise self.error
        return self.reply


class TelegramBotAppTests(unittest.TestCase):
    def test_handle_update_builds_context_and_stores_last_messages(self) -> None:
        telegram_client = FakeTelegramClient()
        openai_client = FakeOpenAIClient(reply="Готово")
        context_store = RecentMessageStore(max_messages=3)
        context_store.append(1, ChatMessage(role="user", content="старый вопрос"))
        context_store.append(1, ChatMessage(role="assistant", content="старый ответ"))

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            context_store=context_store,
            poll_timeout=10,
        )

        app.handle_update(
            {
                "update_id": 7,
                "message": {
                    "message_id": 99,
                    "text": "новый вопрос",
                    "chat": {"id": 1},
                    "from": {"id": 55},
                },
            }
        )

        self.assertEqual(len(openai_client.calls), 1)
        self.assertEqual(
            openai_client.calls[0]["messages"],
            [
                ChatMessage(role="user", content="старый вопрос"),
                ChatMessage(role="assistant", content="старый ответ"),
                ChatMessage(role="user", content="новый вопрос"),
            ],
        )
        self.assertEqual(
            context_store.get(1),
            [
                ChatMessage(role="assistant", content="старый ответ"),
                ChatMessage(role="user", content="новый вопрос"),
                ChatMessage(role="assistant", content="Готово"),
            ],
        )
        self.assertEqual(telegram_client.sent_messages[0]["text"], "Готово")

    def test_reset_command_clears_context(self) -> None:
        telegram_client = FakeTelegramClient()
        openai_client = FakeOpenAIClient()
        context_store = RecentMessageStore(max_messages=2)
        context_store.append(10, ChatMessage(role="user", content="hello"))

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            context_store=context_store,
            poll_timeout=10,
        )

        app.handle_update(
            {
                "update_id": 8,
                "message": {
                    "message_id": 1,
                    "text": "/reset",
                    "chat": {"id": 10},
                    "from": {"id": 22},
                },
            }
        )

        self.assertEqual(context_store.get(10), [])
        self.assertEqual(telegram_client.sent_messages[0]["text"], "Контекст чата очищен.")

    def test_non_text_message_gets_fallback_reply(self) -> None:
        telegram_client = FakeTelegramClient()
        openai_client = FakeOpenAIClient()
        context_store = RecentMessageStore(max_messages=2)

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            context_store=context_store,
            poll_timeout=10,
        )

        app.handle_update(
            {
                "update_id": 11,
                "message": {
                    "message_id": 5,
                    "chat": {"id": 1},
                    "from": {"id": 2},
                },
            }
        )

        self.assertEqual(len(openai_client.calls), 0)
        self.assertEqual(
            telegram_client.sent_messages[0]["text"],
            "Пока поддерживаются только текстовые сообщения.",
        )

    def test_openai_error_returns_user_friendly_message(self) -> None:
        telegram_client = FakeTelegramClient()
        openai_client = FakeOpenAIClient(error=ExternalServiceError("boom"))
        context_store = RecentMessageStore(max_messages=2)

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            context_store=context_store,
            poll_timeout=10,
        )

        app.handle_update(
            {
                "update_id": 12,
                "message": {
                    "message_id": 6,
                    "text": "привет",
                    "chat": {"id": 1},
                    "from": {"id": 2},
                },
            }
        )

        self.assertEqual(context_store.get(1), [])
        self.assertEqual(
            telegram_client.sent_messages[0]["text"],
            "Не удалось получить ответ от модели. Попробуйте еще раз чуть позже.",
        )


if __name__ == "__main__":
    unittest.main()


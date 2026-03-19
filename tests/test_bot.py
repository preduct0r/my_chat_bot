import unittest

from my_chat_bot.bot import TelegramBotApp
from my_chat_bot.context_store import ChatMessage
from my_chat_bot.http_utils import ExternalServiceError
from my_chat_bot.memory import PreparedConversation


class FakeTelegramClient:
    def __init__(self) -> None:
        self.sent_messages = []
        self.files = {}

    def send_message(self, chat_id, text, reply_to_message_id=None) -> None:
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
            }
        )

    def get_file(self, file_id):
        return self.files[file_id]["meta"]

    def download_file(self, file_path):
        for payload in self.files.values():
            if payload["meta"]["file_path"] == file_path:
                return payload["bytes"]
        raise KeyError(file_path)

    def get_updates(self, offset=None, poll_timeout=30):
        return []


class FakeOpenAIClient:
    def __init__(self, reply="Ответ модели", error=None) -> None:
        self.reply = reply
        self.error = error
        self.calls = []

    def generate_reply(self, messages, correlation_id, user_reference, instructions=None):
        self.calls.append(
            {
                "messages": list(messages),
                "correlation_id": correlation_id,
                "user_reference": user_reference,
                "instructions": instructions,
            }
        )
        if self.error is not None:
            raise self.error
        return self.reply


class FakeMemoryService:
    def __init__(self) -> None:
        self.prepare_calls = []
        self.stored_replies = []
        self.reset_calls = []
        self.summarize_calls = []
        self.prepared = PreparedConversation(
            session_id=101,
            instructions="FINAL INSTRUCTIONS",
            input_messages=[ChatMessage.from_text(role="user", text="prepared message")],
            prompt_preview="PROMPT PREVIEW",
        )

    def prepare_conversation(self, telegram_user_id, message, summary_text, correlation_id, now_ts=None):
        self.prepare_calls.append(
            {
                "telegram_user_id": telegram_user_id,
                "message": message,
                "summary_text": summary_text,
                "correlation_id": correlation_id,
            }
        )
        return self.prepared

    def store_assistant_reply(self, session_id, reply_text, now_ts=None):
        self.stored_replies.append({"session_id": session_id, "reply_text": reply_text})

    def reset_active_session(self, telegram_user_id):
        self.reset_calls.append(telegram_user_id)

    def summarize_expired_sessions(self, now_ts=None, limit=10):
        self.summarize_calls.append({"now_ts": now_ts, "limit": limit})


class TelegramBotAppTests(unittest.TestCase):
    def test_handle_update_uses_memory_service_and_final_instructions(self) -> None:
        telegram_client = FakeTelegramClient()
        openai_client = FakeOpenAIClient(reply="Готово")
        memory_service = FakeMemoryService()

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            memory_service=memory_service,
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

        self.assertEqual(len(memory_service.prepare_calls), 1)
        self.assertEqual(memory_service.prepare_calls[0]["telegram_user_id"], 55)
        self.assertEqual(memory_service.prepare_calls[0]["summary_text"], "Пользователь: новый вопрос")
        self.assertEqual(openai_client.calls[0]["instructions"], "FINAL INSTRUCTIONS")
        self.assertEqual(
            openai_client.calls[0]["messages"],
            [ChatMessage.from_text(role="user", text="prepared message")],
        )
        self.assertEqual(memory_service.stored_replies[0]["reply_text"], "Готово")
        self.assertEqual(telegram_client.sent_messages[0]["text"], "Готово")

    def test_reset_command_clears_active_session_only(self) -> None:
        telegram_client = FakeTelegramClient()
        openai_client = FakeOpenAIClient()
        memory_service = FakeMemoryService()

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            memory_service=memory_service,
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

        self.assertEqual(memory_service.reset_calls, [22])
        self.assertEqual(
            telegram_client.sent_messages[0]["text"],
            "Активная сессия очищена. Долговременная память пользователя сохранена.",
        )

    def test_link_command_generates_code(self) -> None:
        telegram_client = FakeTelegramClient()
        openai_client = FakeOpenAIClient()
        memory_service = FakeMemoryService()
        memory_service.link_code = "ABCD-1234"
        memory_service.create_telegram_link_code = lambda telegram_user_id: memory_service.link_code

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            memory_service=memory_service,
            poll_timeout=10,
        )

        app.handle_update(
            {
                "update_id": 9,
                "message": {
                    "message_id": 2,
                    "text": "/link",
                    "chat": {"id": 10},
                    "from": {"id": 22},
                },
            }
        )

        self.assertIn("ABCD-1234", telegram_client.sent_messages[0]["text"])

    def test_unsupported_message_gets_fallback_reply(self) -> None:
        telegram_client = FakeTelegramClient()
        openai_client = FakeOpenAIClient()
        memory_service = FakeMemoryService()

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            memory_service=memory_service,
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
            "Поддерживаются текстовые сообщения, изображения, PDF, DOC, DOCX, XLSX и текстовые файлы.",
        )

    def test_openai_error_returns_user_friendly_message(self) -> None:
        telegram_client = FakeTelegramClient()
        openai_client = FakeOpenAIClient(error=ExternalServiceError("boom"))
        memory_service = FakeMemoryService()

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            memory_service=memory_service,
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

        self.assertEqual(memory_service.stored_replies, [])
        self.assertEqual(
            telegram_client.sent_messages[0]["text"],
            "Не удалось получить ответ от модели. Попробуйте еще раз чуть позже.",
        )

    def test_photo_message_builds_summary_text_without_binary_payload(self) -> None:
        telegram_client = FakeTelegramClient()
        telegram_client.files["photo-file"] = {
            "meta": {"file_path": "photos/1.jpg"},
            "bytes": b"\xff\xd8\xff",
        }
        openai_client = FakeOpenAIClient(reply="На фото кот")
        memory_service = FakeMemoryService()

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            memory_service=memory_service,
            poll_timeout=10,
        )

        app.handle_update(
            {
                "update_id": 20,
                "message": {
                    "message_id": 7,
                    "chat": {"id": 1},
                    "from": {"id": 2},
                    "photo": [
                        {"file_id": "photo-file", "file_size": 10},
                    ],
                },
            }
        )

        prepared = memory_service.prepare_calls[0]
        self.assertEqual(prepared["message"].content[0]["text"], "Опиши вложение и ответь по нему.")
        self.assertEqual(prepared["message"].content[1]["type"], "input_image")
        self.assertIn('Пользователь прикрепил изображение "photo.jpg".', prepared["summary_text"])

    def test_text_document_is_inlined_for_reply_but_summary_uses_description(self) -> None:
        telegram_client = FakeTelegramClient()
        telegram_client.files["text-file"] = {
            "meta": {"file_path": "docs/notes.txt"},
            "bytes": "строка 1\nстрока 2".encode("utf-8"),
        }
        openai_client = FakeOpenAIClient(reply="Прочитал текст")
        memory_service = FakeMemoryService()

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            memory_service=memory_service,
            poll_timeout=10,
        )

        app.handle_update(
            {
                "update_id": 22,
                "message": {
                    "message_id": 9,
                    "chat": {"id": 1},
                    "from": {"id": 2},
                    "caption": "Кратко перескажи",
                    "document": {
                        "file_id": "text-file",
                        "file_name": "notes.txt",
                        "mime_type": "text/plain",
                    },
                },
            }
        )

        prepared = memory_service.prepare_calls[0]
        self.assertIn("Содержимое файла notes.txt:\nстрока 1\nстрока 2", prepared["message"].content[1]["text"])
        self.assertEqual(
            prepared["summary_text"],
            'Пользователь: Кратко перескажи\nПользователь прикрепил текстовый файл "notes.txt".',
        )


if __name__ == "__main__":
    unittest.main()

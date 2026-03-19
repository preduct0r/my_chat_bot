import unittest

from my_chat_bot.bot import TelegramBotApp
from my_chat_bot.context_store import ChatMessage, RecentMessageStore
from my_chat_bot.http_utils import ExternalServiceError


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
        context_store.append(1, ChatMessage.from_text(role="user", text="старый вопрос"))
        context_store.append(1, ChatMessage.from_text(role="assistant", text="старый ответ"))

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
                ChatMessage.from_text(role="user", text="старый вопрос"),
                ChatMessage.from_text(role="assistant", text="старый ответ"),
                ChatMessage.from_text(role="user", text="новый вопрос"),
            ],
        )
        self.assertEqual(
            context_store.get(1),
            [
                ChatMessage.from_text(role="assistant", text="старый ответ"),
                ChatMessage.from_text(role="user", text="новый вопрос"),
                ChatMessage.from_text(role="assistant", text="Готово"),
            ],
        )
        self.assertEqual(telegram_client.sent_messages[0]["text"], "Готово")

    def test_reset_command_clears_context(self) -> None:
        telegram_client = FakeTelegramClient()
        openai_client = FakeOpenAIClient()
        context_store = RecentMessageStore(max_messages=2)
        context_store.append(10, ChatMessage.from_text(role="user", text="hello"))

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

    def test_unsupported_message_gets_fallback_reply(self) -> None:
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
            "Поддерживаются текстовые сообщения, изображения, PDF, DOC, DOCX, XLSX и текстовые файлы.",
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

    def test_photo_message_is_sent_to_model_with_default_prompt(self) -> None:
        telegram_client = FakeTelegramClient()
        telegram_client.files["photo-file"] = {
            "meta": {"file_path": "photos/1.jpg"},
            "bytes": b"\xff\xd8\xff",
        }
        openai_client = FakeOpenAIClient(reply="На фото кот")
        context_store = RecentMessageStore(max_messages=2)

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            context_store=context_store,
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

        user_message = openai_client.calls[0]["messages"][0]
        self.assertEqual(user_message.content[0]["text"], "Опиши вложение и ответь по нему.")
        self.assertEqual(user_message.content[1]["type"], "input_image")
        self.assertTrue(user_message.content[1]["image_url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(telegram_client.sent_messages[0]["text"], "На фото кот")

    def test_pdf_document_is_sent_as_input_file(self) -> None:
        telegram_client = FakeTelegramClient()
        telegram_client.files["pdf-file"] = {
            "meta": {"file_path": "docs/test.pdf"},
            "bytes": b"%PDF-1.4",
        }
        openai_client = FakeOpenAIClient(reply="Это PDF")
        context_store = RecentMessageStore(max_messages=2)

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            context_store=context_store,
            poll_timeout=10,
        )

        app.handle_update(
            {
                "update_id": 21,
                "message": {
                    "message_id": 8,
                    "chat": {"id": 1},
                    "from": {"id": 2},
                    "caption": "Что в файле?",
                    "document": {
                        "file_id": "pdf-file",
                        "file_name": "test.pdf",
                        "mime_type": "application/pdf",
                    },
                },
            }
        )

        user_message = openai_client.calls[0]["messages"][0]
        self.assertEqual(user_message.content[0]["text"], "Что в файле?")
        self.assertEqual(user_message.content[1]["type"], "input_file")
        self.assertEqual(user_message.content[1]["filename"], "test.pdf")
        self.assertTrue(
            user_message.content[1]["file_data"].startswith("data:application/pdf;base64,")
        )

    def test_text_document_is_inlined_as_text(self) -> None:
        telegram_client = FakeTelegramClient()
        telegram_client.files["text-file"] = {
            "meta": {"file_path": "docs/notes.txt"},
            "bytes": "строка 1\nстрока 2".encode("utf-8"),
        }
        openai_client = FakeOpenAIClient(reply="Прочитал текст")
        context_store = RecentMessageStore(max_messages=2)

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            context_store=context_store,
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

        user_message = openai_client.calls[0]["messages"][0]
        self.assertEqual(user_message.content[0]["text"], "Кратко перескажи")
        self.assertIn("Содержимое файла notes.txt:\nстрока 1\nстрока 2", user_message.content[1]["text"])

    def test_unsupported_document_returns_fallback_reply(self) -> None:
        telegram_client = FakeTelegramClient()
        telegram_client.files["bin-file"] = {
            "meta": {"file_path": "docs/archive.zip"},
            "bytes": b"PK\x03\x04",
        }
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
                "update_id": 23,
                "message": {
                    "message_id": 10,
                    "chat": {"id": 1},
                    "from": {"id": 2},
                    "document": {
                        "file_id": "bin-file",
                        "file_name": "archive.zip",
                        "mime_type": "application/zip",
                    },
                },
            }
        )

        self.assertEqual(len(openai_client.calls), 0)
        self.assertEqual(
            telegram_client.sent_messages[0]["text"],
            "Поддерживаются текстовые сообщения, изображения, PDF, DOC, DOCX, XLSX и текстовые файлы.",
        )

    def test_docx_document_is_sent_as_input_file(self) -> None:
        telegram_client = FakeTelegramClient()
        telegram_client.files["docx-file"] = {
            "meta": {"file_path": "docs/spec.docx"},
            "bytes": b"PK\x03\x04docx",
        }
        openai_client = FakeOpenAIClient(reply="Это DOCX")
        context_store = RecentMessageStore(max_messages=2)

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            context_store=context_store,
            poll_timeout=10,
        )

        app.handle_update(
            {
                "update_id": 24,
                "message": {
                    "message_id": 11,
                    "chat": {"id": 1},
                    "from": {"id": 2},
                    "caption": "Что в документе?",
                    "document": {
                        "file_id": "docx-file",
                        "file_name": "spec.docx",
                        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    },
                },
            }
        )

        user_message = openai_client.calls[0]["messages"][0]
        self.assertEqual(user_message.content[0]["text"], "Что в документе?")
        self.assertEqual(user_message.content[1]["type"], "input_file")
        self.assertEqual(user_message.content[1]["filename"], "spec.docx")
        self.assertTrue(
            user_message.content[1]["file_data"].startswith(
                "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,"
            )
        )

    def test_doc_document_is_sent_as_input_file(self) -> None:
        telegram_client = FakeTelegramClient()
        telegram_client.files["doc-file"] = {
            "meta": {"file_path": "docs/legacy.doc"},
            "bytes": b"\xd0\xcf\x11\xe0",
        }
        openai_client = FakeOpenAIClient(reply="Это DOC")
        context_store = RecentMessageStore(max_messages=2)

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            context_store=context_store,
            poll_timeout=10,
        )

        app.handle_update(
            {
                "update_id": 25,
                "message": {
                    "message_id": 12,
                    "chat": {"id": 1},
                    "from": {"id": 2},
                    "document": {
                        "file_id": "doc-file",
                        "file_name": "legacy.doc",
                        "mime_type": "application/msword",
                    },
                },
            }
        )

        user_message = openai_client.calls[0]["messages"][0]
        self.assertEqual(user_message.content[0]["text"], "Опиши вложение и ответь по нему.")
        self.assertEqual(user_message.content[1]["type"], "input_file")
        self.assertEqual(user_message.content[1]["filename"], "legacy.doc")
        self.assertTrue(
            user_message.content[1]["file_data"].startswith("data:application/msword;base64,")
        )

    def test_xlsx_document_is_sent_as_input_file(self) -> None:
        telegram_client = FakeTelegramClient()
        telegram_client.files["xlsx-file"] = {
            "meta": {"file_path": "docs/report.xlsx"},
            "bytes": b"PK\x03\x04xlsx",
        }
        openai_client = FakeOpenAIClient(reply="Это XLSX")
        context_store = RecentMessageStore(max_messages=2)

        app = TelegramBotApp(
            telegram_client=telegram_client,
            openai_client=openai_client,
            context_store=context_store,
            poll_timeout=10,
        )

        app.handle_update(
            {
                "update_id": 26,
                "message": {
                    "message_id": 13,
                    "chat": {"id": 1},
                    "from": {"id": 2},
                    "caption": "Сделай краткую сводку по таблице",
                    "document": {
                        "file_id": "xlsx-file",
                        "file_name": "report.xlsx",
                        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    },
                },
            }
        )

        user_message = openai_client.calls[0]["messages"][0]
        self.assertEqual(user_message.content[0]["text"], "Сделай краткую сводку по таблице")
        self.assertEqual(user_message.content[1]["type"], "input_file")
        self.assertEqual(user_message.content[1]["filename"], "report.xlsx")
        self.assertTrue(
            user_message.content[1]["file_data"].startswith(
                "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,"
            )
        )


if __name__ == "__main__":
    unittest.main()

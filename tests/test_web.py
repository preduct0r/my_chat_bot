import base64
import json
import tempfile
import unittest
from pathlib import Path
from time import time

from my_chat_bot.memory import MemoryService, SQLiteMemoryRepository
from my_chat_bot.web_server import WebChatApp, WebServerConfig
from my_chat_bot.web_transport import WebRequest


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.reply_calls = []
        self.summary_calls = []

    def generate_reply(self, messages, correlation_id, user_reference, instructions=None):
        self.reply_calls.append(
            {
                "messages": list(messages),
                "correlation_id": correlation_id,
                "user_reference": user_reference,
                "instructions": instructions,
            }
        )
        return "web reply"

    def summarize_dialogue(self, transcript, existing_personal_memory, correlation_id, user_reference):
        self.summary_calls.append(transcript)
        return {
            "personal": [],
            "dialog_summary": {
                "summary": "summary",
                "key_points": [],
                "documents": [],
                "open_questions": [],
            },
        }


class WebChatAppTests(unittest.TestCase):
    def _build_app(self, temp_dir: str) -> WebChatApp:
        repo = SQLiteMemoryRepository(str(Path(temp_dir) / "memory.sqlite3"))
        openai_client = FakeOpenAIClient()
        memory_service = MemoryService(
            repository=repo,
            openai_client=openai_client,
            context_size=5,
            summary_count=3,
            memory_budget=1000,
            session_timeout_seconds=3600,
            base_system_prompt="system prompt",
        )
        return WebChatApp(
            memory_service=memory_service,
            openai_client=openai_client,
            config=WebServerConfig(host="127.0.0.1", port=8081, static_dir=temp_dir),
        )

    def test_anonymous_web_identity_gets_separate_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = self._build_app(temp_dir)

            identity = app.get_or_create_identity(None)
            response = app.handle_chat(identity, "привет из web")
            state = app.get_state(identity)

        self.assertLess(identity.memory_user_id, 0)
        self.assertIsNone(identity.linked_telegram_user_id)
        self.assertEqual(response["reply"], "web reply")
        self.assertEqual(state["messages"][-1]["text"], "web reply")

    def test_linked_web_identity_uses_same_memory_as_telegram_user(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = SQLiteMemoryRepository(str(Path(temp_dir) / "memory.sqlite3"))
            openai_client = FakeOpenAIClient()
            memory_service = MemoryService(
                repository=repo,
                openai_client=openai_client,
                context_size=5,
                summary_count=3,
                memory_budget=1000,
                session_timeout_seconds=3600,
                base_system_prompt="system prompt",
            )
            app = WebChatApp(
                memory_service=memory_service,
                openai_client=openai_client,
                config=WebServerConfig(host="127.0.0.1", port=8081, static_dir=temp_dir),
            )

            now_ts = int(time())
            repo.ensure_user(123, now_ts)
            link_code = memory_service.create_telegram_link_code(123, now_ts=now_ts)
            identity = app.get_or_create_identity(None)
            linked = app.link_identity(identity, link_code)
            app.handle_chat(linked, "вопрос из web")
            state = app.get_state(linked)

        self.assertEqual(linked.linked_telegram_user_id, 123)
        self.assertEqual(linked.memory_user_id, 123)
        self.assertEqual(state["memoryUserId"], 123)
        self.assertEqual(state["linkedTelegramUserId"], 123)

    def test_request_handler_uses_explicit_session_token_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = self._build_app(temp_dir)

            state_response = app.handle_request(WebRequest(method="GET", path="/api/state"))
            state_payload = json.loads(state_response.body.decode("utf-8"))

            chat_response = app.handle_request(
                WebRequest(
                    method="POST",
                    path="/api/chat",
                    headers={"X-Session-Token": state_payload["sessionToken"]},
                    body=json.dumps({"message": "привет"}).encode("utf-8"),
                )
            )
            chat_payload = json.loads(chat_response.body.decode("utf-8"))

            follow_up_state = app.handle_request(
                WebRequest(
                    method="GET",
                    path="/api/state",
                    headers={"X-Session-Token": state_payload["sessionToken"]},
                )
            )
            follow_up_payload = json.loads(follow_up_state.body.decode("utf-8"))

        self.assertEqual(chat_response.status_code, 200)
        self.assertEqual(chat_payload["reply"], "web reply")
        self.assertEqual(chat_payload["sessionToken"], state_payload["sessionToken"])
        self.assertEqual(follow_up_payload["memoryUserId"], state_payload["memoryUserId"])
        self.assertEqual(follow_up_payload["messages"][-1]["text"], "web reply")

    def test_request_handler_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = self._build_app(temp_dir)

            response = app.handle_request(
                WebRequest(
                    method="POST",
                    path="/api/chat",
                    body=b"{not-json",
                )
            )
            payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["error"], "invalid JSON body")
        self.assertIn("sessionToken", payload)

    def test_request_handler_supports_text_file_uploads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = self._build_app(temp_dir)
            state_response = app.handle_request(WebRequest(method="GET", path="/api/state"))
            state_payload = json.loads(state_response.body.decode("utf-8"))

            response = app.handle_request(
                WebRequest(
                    method="POST",
                    path="/api/chat",
                    headers={"X-Session-Token": state_payload["sessionToken"]},
                    body=json.dumps(
                        {
                            "message": "Кратко перескажи",
                            "attachments": [
                                {
                                    "filename": "notes.txt",
                                    "mimeType": "text/plain",
                                    "dataBase64": base64.b64encode("строка 1\nстрока 2".encode("utf-8")).decode("ascii"),
                                }
                            ],
                        }
                    ).encode("utf-8"),
                )
            )
            payload = json.loads(response.body.decode("utf-8"))
            openai_call = app.openai_client.reply_calls[0]
            user_message = openai_call["messages"][-1]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["reply"], "web reply")
        self.assertEqual(user_message.role, "user")
        self.assertEqual(user_message.content[0]["text"], "Кратко перескажи")
        self.assertIn("Содержимое файла notes.txt:\nстрока 1\nстрока 2", user_message.content[1]["text"])

    def test_request_handler_supports_binary_file_uploads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = self._build_app(temp_dir)
            state_response = app.handle_request(WebRequest(method="GET", path="/api/state"))
            state_payload = json.loads(state_response.body.decode("utf-8"))

            response = app.handle_request(
                WebRequest(
                    method="POST",
                    path="/api/chat",
                    headers={"X-Session-Token": state_payload["sessionToken"]},
                    body=json.dumps(
                        {
                            "message": "",
                            "attachments": [
                                {
                                    "filename": "spec.pdf",
                                    "mimeType": "application/pdf",
                                    "dataBase64": base64.b64encode(b"%PDF-1.4").decode("ascii"),
                                }
                            ],
                        }
                    ).encode("utf-8"),
                )
            )
            payload = json.loads(response.body.decode("utf-8"))
            openai_call = app.openai_client.reply_calls[0]
            user_message = openai_call["messages"][-1]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["reply"], "web reply")
        self.assertEqual(user_message.content[0]["text"], "Опиши вложение и ответь по нему.")
        self.assertEqual(user_message.content[1]["type"], "input_file")
        self.assertEqual(user_message.content[1]["filename"], "spec.pdf")
        self.assertTrue(user_message.content[1]["file_data"].startswith("data:application/pdf;base64,"))

    def test_request_handler_rejects_unsupported_web_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app = self._build_app(temp_dir)

            response = app.handle_request(
                WebRequest(
                    method="POST",
                    path="/api/chat",
                    body=json.dumps(
                        {
                            "attachments": [
                                {
                                    "filename": "archive.zip",
                                    "mimeType": "application/zip",
                                    "dataBase64": base64.b64encode(b"PK\x03\x04").decode("ascii"),
                                }
                            ],
                        }
                    ).encode("utf-8"),
                )
            )
            payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            payload["error"],
            "Поддерживаются текстовые сообщения, изображения, PDF, DOC, DOCX, XLSX и текстовые файлы.",
        )


if __name__ == "__main__":
    unittest.main()

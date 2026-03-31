import json
import tempfile
import threading
import unittest
from pathlib import Path
from time import time
from urllib import error, request

from my_chat_bot.chat_inputs import DEFAULT_ATTACHMENT_PROMPT
from my_chat_bot.web_server import (
    WebChatHTTPServer,
    WebChatApp,
    WebServerConfig,
    _build_handler,
    parse_multipart_form_data,
)
from my_chat_bot.attachments import create_attachment
from my_chat_bot.memory import MemoryService, SQLiteMemoryRepository


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
    def test_text_attachment_without_message_uses_default_prompt(self) -> None:
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

            identity = app.get_or_create_identity(None)
            attachment = create_attachment("notes.txt", "text/plain", "строка 1\nстрока 2".encode("utf-8"))
            app.handle_chat(identity, "", attachments=[attachment])

        user_message = openai_client.reply_calls[0]["messages"][-1]
        self.assertEqual(user_message.content[0]["text"], DEFAULT_ATTACHMENT_PROMPT)
        self.assertIn("Содержимое файла notes.txt:\nстрока 1\nстрока 2", user_message.content[1]["text"])

    def test_anonymous_web_identity_gets_separate_memory(self) -> None:
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

    def test_parse_multipart_form_data_reads_fields_and_files(self) -> None:
        boundary = "----CodexBoundary"
        raw_body = _build_multipart_body(
            boundary=boundary,
            fields={"message": "разбери файл", "code": "ABCD-1234"},
            files=[
                {
                    "field_name": "files",
                    "filename": "notes.txt",
                    "content_type": "text/plain",
                    "data": "строка".encode("utf-8"),
                }
            ],
        )

        form_data = parse_multipart_form_data(f"multipart/form-data; boundary={boundary}", raw_body)

        self.assertEqual(form_data.fields["message"], "разбери файл")
        self.assertEqual(form_data.fields["code"], "ABCD-1234")
        self.assertEqual(form_data.files[0].filename, "notes.txt")
        self.assertEqual(form_data.files[0].content_type, "text/plain")
        self.assertEqual(form_data.files[0].data, "строка".encode("utf-8"))

    def test_chat_endpoint_accepts_multipart_uploads(self) -> None:
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
                config=WebServerConfig(host="127.0.0.1", port=0, static_dir=temp_dir),
            )
            server = WebChatHTTPServer(("127.0.0.1", 0), _build_handler(), app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                boundary = "----CodexBoundary"
                raw_body = _build_multipart_body(
                    boundary=boundary,
                    fields={"message": "суммаризируй"},
                    files=[
                        {
                            "field_name": "files",
                            "filename": "report.pdf",
                            "content_type": "application/pdf",
                            "data": b"%PDF-1.4",
                        }
                    ],
                )
                response = request.urlopen(
                    request.Request(
                        url=f"http://127.0.0.1:{server.server_port}/api/chat",
                        data=raw_body,
                        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                        method="POST",
                    )
                )
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(payload["reply"], "web reply")
        user_message = openai_client.reply_calls[0]["messages"][-1]
        self.assertEqual(user_message.content[0]["text"], "суммаризируй")
        self.assertEqual(user_message.content[1]["type"], "input_file")
        self.assertEqual(user_message.content[1]["filename"], "report.pdf")

    def test_chat_endpoint_rejects_unsupported_uploads(self) -> None:
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
                config=WebServerConfig(host="127.0.0.1", port=0, static_dir=temp_dir),
            )
            server = WebChatHTTPServer(("127.0.0.1", 0), _build_handler(), app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                boundary = "----CodexBoundary"
                raw_body = _build_multipart_body(
                    boundary=boundary,
                    fields={"message": "что внутри"},
                    files=[
                        {
                            "field_name": "files",
                            "filename": "archive.zip",
                            "content_type": "application/zip",
                            "data": b"PK\x03\x04zip",
                        }
                    ],
                )
                with self.assertRaises(error.HTTPError) as raised:
                    request.urlopen(
                        request.Request(
                            url=f"http://127.0.0.1:{server.server_port}/api/chat",
                            data=raw_body,
                            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                            method="POST",
                        )
                    )
                payload = json.loads(raised.exception.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(raised.exception.code, 400)
        self.assertIn("Поддерживаются", payload["error"])


def _build_multipart_body(boundary: str, fields, files) -> bytes:
    chunks = []
    for field_name, value in fields.items():
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    for file_item in files:
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{file_item["field_name"]}"; '
                f'filename="{file_item["filename"]}"\r\n'
                f'Content-Type: {file_item["content_type"]}\r\n\r\n'
            ).encode("utf-8")
            + file_item["data"]
            + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks)


if __name__ == "__main__":
    unittest.main()

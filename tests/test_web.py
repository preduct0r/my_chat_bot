import tempfile
import unittest
from pathlib import Path
from time import time

from my_chat_bot.memory import MemoryService, SQLiteMemoryRepository
from my_chat_bot.web_server import WebChatApp, WebServerConfig


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


if __name__ == "__main__":
    unittest.main()

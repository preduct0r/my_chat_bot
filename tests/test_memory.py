import tempfile
import unittest
from pathlib import Path

from my_chat_bot.context_store import ChatMessage
from my_chat_bot.memory import MemoryService, SQLiteMemoryRepository
from my_chat_bot.prompt_builder import select_memory_with_budget


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.summary_calls = []

    def summarize_dialogue(self, transcript, existing_personal_memory, correlation_id, user_reference):
        self.summary_calls.append(
            {
                "transcript": transcript,
                "existing_personal_memory": list(existing_personal_memory),
                "correlation_id": correlation_id,
                "user_reference": user_reference,
            }
        )
        return {
            "personal": [{"category": "language", "fact": "Пользователь предпочитает русский язык"}],
            "dialog_summary": {
                "summary": "Пользователь обсуждал документ и задал вопросы по нему.",
                "key_points": ["Обсудили структуру документа"],
                "documents": ["spec.pdf"],
                "open_questions": ["Нужно продолжить внедрение"],
            },
        }


class StringSessionRepository:
    def __init__(self) -> None:
        self.messages = []
        self.open_session = {
            "id": "01774708147637930233-0627",
            "telegram_user_id": 77,
            "status": "open",
            "started_at": 100,
            "last_activity_at": 100,
            "closed_at": None,
            "summarized_at": None,
        }

    def ensure_user(self, telegram_user_id, now_ts) -> None:
        return None

    def get_open_session(self, telegram_user_id):
        return dict(self.open_session)

    def create_session(self, telegram_user_id, now_ts):
        raise AssertionError("create_session should not be called when an open string session exists")

    def update_session_activity(self, session_id, now_ts) -> None:
        self.open_session["last_activity_at"] = now_ts

    def close_session(self, session_id, now_ts) -> None:
        self.open_session["status"] = "closed_pending_summary"

    def mark_session_summarized(self, session_id, now_ts) -> None:
        self.open_session["status"] = "summarized"

    def discard_open_session(self, telegram_user_id) -> None:
        self.open_session = None

    def add_message(self, session_id, message, summary_text, now_ts) -> None:
        self.messages.append((session_id, message))

    def get_recent_messages(self, session_id, limit):
        return [message for stored_session_id, message in self.messages if stored_session_id == session_id][-limit:]

    def get_session_summary_transcript(self, session_id):
        return ""

    def get_expired_open_sessions(self, cutoff_ts, limit=20):
        return []

    def get_personal_memory(self, telegram_user_id):
        return []

    def save_personal_memory(self, telegram_user_id, personal_memory, now_ts) -> None:
        return None

    def get_recent_summaries(self, telegram_user_id, limit):
        return []

    def save_session_summary(self, session_id, telegram_user_id, summary_payload, now_ts) -> None:
        return None

    def get_web_client(self, session_token):
        return None

    def create_web_client(self, session_token, memory_user_id, linked_telegram_user_id, now_ts) -> None:
        return None

    def update_web_client_link(self, session_token, memory_user_id, linked_telegram_user_id, now_ts) -> None:
        return None

    def get_next_anonymous_user_id(self):
        return -1

    def create_link_code(self, code, telegram_user_id, created_at, expires_at) -> None:
        return None

    def consume_link_code(self, code, now_ts):
        return None

    def get_active_session_messages_for_user(self, telegram_user_id, limit):
        return []


class MemoryServiceTests(unittest.TestCase):
    def test_memory_persists_between_service_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "memory.sqlite3")
            openai_client = FakeOpenAIClient()
            service1 = MemoryService(
                repository=SQLiteMemoryRepository(db_path=db_path),
                openai_client=openai_client,
                context_size=3,
                summary_count=2,
                memory_budget=1000,
                session_timeout_seconds=3600,
                base_system_prompt="system prompt",
            )
            prepared1 = service1.prepare_conversation(
                telegram_user_id=10,
                message=ChatMessage.from_text(role="user", text="привет"),
                summary_text="Пользователь: привет",
                correlation_id="c1",
                now_ts=100,
            )
            service1.store_assistant_reply(prepared1.session_id, "Здравствуйте", now_ts=101)

            service2 = MemoryService(
                repository=SQLiteMemoryRepository(db_path=db_path),
                openai_client=openai_client,
                context_size=3,
                summary_count=2,
                memory_budget=1000,
                session_timeout_seconds=3600,
                base_system_prompt="system prompt",
            )
            prepared2 = service2.prepare_conversation(
                telegram_user_id=10,
                message=ChatMessage.from_text(role="user", text="как дела"),
                summary_text="Пользователь: как дела",
                correlation_id="c2",
                now_ts=102,
            )

        self.assertEqual(
            prepared2.input_messages,
            [
                ChatMessage.from_text(role="user", text="привет"),
                ChatMessage.from_text(role="assistant", text="Здравствуйте"),
                ChatMessage.from_text(role="user", text="как дела"),
            ],
        )

    def test_summarization_uses_full_dialogue_not_only_last_n_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "memory.sqlite3")
            openai_client = FakeOpenAIClient()
            service = MemoryService(
                repository=SQLiteMemoryRepository(db_path=db_path),
                openai_client=openai_client,
                context_size=2,
                summary_count=3,
                memory_budget=1000,
                session_timeout_seconds=3600,
                base_system_prompt="system prompt",
            )

            first = service.prepare_conversation(
                telegram_user_id=20,
                message=ChatMessage.from_text(role="user", text="первый вопрос"),
                summary_text="Пользователь: первый вопрос",
                correlation_id="s1",
                now_ts=100,
            )
            service.store_assistant_reply(first.session_id, "первый ответ", now_ts=101)
            second = service.prepare_conversation(
                telegram_user_id=20,
                message=ChatMessage.from_text(role="user", text="второй вопрос"),
                summary_text="Пользователь: второй вопрос",
                correlation_id="s2",
                now_ts=102,
            )
            service.store_assistant_reply(second.session_id, "второй ответ", now_ts=103)

            prepared = service.prepare_conversation(
                telegram_user_id=20,
                message=ChatMessage.from_text(role="user", text="новая сессия"),
                summary_text="Пользователь: новая сессия",
                correlation_id="s3",
                now_ts=5000,
            )

        self.assertEqual(len(openai_client.summary_calls), 1)
        transcript = openai_client.summary_calls[0]["transcript"]
        self.assertIn("Пользователь: первый вопрос", transcript)
        self.assertIn("Ассистент: первый ответ", transcript)
        self.assertIn("Пользователь: второй вопрос", transcript)
        self.assertIn("Ассистент: второй ответ", transcript)
        self.assertIn("Пользователь предпочитает русский язык", prepared.instructions)
        self.assertIn("Пользователь обсуждал документ", prepared.instructions)

    def test_memory_budget_limits_personal_and_summaries(self) -> None:
        personal, summaries, info = select_memory_with_budget(
            personal_memory=[
                {"category": "name", "fact": "Пользователя зовут Денис"},
                {"category": "language", "fact": "Пользователь предпочитает русский язык"},
            ],
            summaries=[
                {
                    "session_id": 1,
                    "dialog_summary": {
                        "summary": "Очень длинная суммаризация, которая съедает бюджет.",
                        "key_points": [],
                        "documents": [],
                        "open_questions": [],
                    },
                }
            ],
            memory_budget=25,
        )

        self.assertEqual(len(personal), 1)
        self.assertEqual(summaries, [])
        self.assertLessEqual(info["total_tokens"], 25)

    def test_prepare_conversation_accepts_string_session_ids_from_repository(self) -> None:
        service = MemoryService(
            repository=StringSessionRepository(),
            openai_client=FakeOpenAIClient(),
            context_size=3,
            summary_count=2,
            memory_budget=1000,
            session_timeout_seconds=3600,
            base_system_prompt="system prompt",
        )

        prepared = service.prepare_conversation(
            telegram_user_id=77,
            message=ChatMessage.from_text(role="user", text="привет"),
            summary_text="Пользователь: привет",
            correlation_id="string-session",
            now_ts=101,
        )

        self.assertEqual(prepared.session_id, "01774708147637930233-0627")
        self.assertEqual(prepared.input_messages[-1], ChatMessage.from_text(role="user", text="привет"))


if __name__ == "__main__":
    unittest.main()

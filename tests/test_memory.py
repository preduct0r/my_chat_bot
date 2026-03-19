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


if __name__ == "__main__":
    unittest.main()

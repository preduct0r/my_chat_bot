import unittest

from my_chat_bot.context_store import ChatMessage
from my_chat_bot.http_utils import ExternalServiceError, HttpResponse
from my_chat_bot.openai_client import OpenAIResponsesClient, extract_output_text


class OpenAIResponsesClientTests(unittest.TestCase):
    def test_generate_reply_sends_messages_to_responses_api(self) -> None:
        captured = {}

        def fake_transport(url, payload, headers, timeout):
            captured["url"] = url
            captured["payload"] = payload
            captured["headers"] = headers
            captured["timeout"] = timeout
            return HttpResponse(
                status_code=200,
                body={
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "Привет!"}],
                        }
                    ]
                },
                headers={"x-request-id": "req_123"},
            )

        client = OpenAIResponsesClient(
            api_key="secret",
            model="gpt-4.1-mini",
            api_url="https://api.openai.com/v1/responses",
            system_prompt="system prompt",
            transport=fake_transport,
        )

        reply = client.generate_reply(
            messages=[
                ChatMessage.from_text(role="assistant", text="Старый ответ"),
                ChatMessage(
                    role="user",
                    content=(
                        {"type": "input_text", "text": "Новый вопрос"},
                        {"type": "input_image", "image_url": "data:image/png;base64,AAA"},
                    ),
                ),
            ],
            correlation_id="tg-10",
            user_reference="42",
            instructions="final instructions",
        )

        self.assertEqual(reply, "Привет!")
        self.assertEqual(captured["url"], "https://api.openai.com/v1/responses")
        self.assertEqual(captured["payload"]["model"], "gpt-4.1-mini")
        self.assertEqual(captured["payload"]["instructions"], "final instructions")
        self.assertEqual(
            captured["payload"]["input"],
            [
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Старый ответ"}],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Новый вопрос"},
                        {"type": "input_image", "image_url": "data:image/png;base64,AAA"},
                    ],
                },
            ],
        )
        self.assertEqual(captured["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(captured["headers"]["X-Client-Request-Id"], "tg-10")

    def test_extract_output_text_raises_on_missing_text(self) -> None:
        with self.assertRaises(ExternalServiceError):
            extract_output_text({"output": [{"type": "message", "content": []}]})

    def test_summarize_dialogue_uses_structured_output_schema(self) -> None:
        captured = {}

        def fake_transport(url, payload, headers, timeout):
            captured["payload"] = payload
            return HttpResponse(
                status_code=200,
                body={
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"personal":[{"fact":"Предпочитает русский","category":"language"}],'
                                        '"dialog_summary":{"summary":"Итог","key_points":["A"],"documents":["doc.pdf"],"open_questions":[]}}'
                                    ),
                                }
                            ],
                        }
                    ]
                },
                headers={},
            )

        client = OpenAIResponsesClient(
            api_key="secret",
            model="gpt-4.1-mini",
            api_url="https://api.openai.com/v1/responses",
            system_prompt="system prompt",
            transport=fake_transport,
        )

        payload = client.summarize_dialogue(
            transcript="Пользователь: привет\nАссистент: здравствуйте",
            existing_personal_memory=[{"category": "name", "fact": "Денис"}],
            correlation_id="sum-1",
            user_reference="42",
        )

        self.assertEqual(payload["personal"][0]["fact"], "Предпочитает русский")
        self.assertEqual(captured["payload"]["text"]["format"]["type"], "json_schema")
        self.assertEqual(captured["payload"]["text"]["format"]["name"], "dialogue_memory_summary")


if __name__ == "__main__":
    unittest.main()

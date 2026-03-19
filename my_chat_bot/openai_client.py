from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .context_store import ChatMessage
from .http_utils import ExternalServiceError, Transport, post_json

SUMMARIZATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "personal": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "fact": {"type": "string"},
                    "category": {"type": "string"},
                },
                "required": ["fact", "category"],
            },
        },
        "dialog_summary": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "key_points": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "documents": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "open_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["summary", "key_points", "documents", "open_questions"],
        },
    },
    "required": ["personal", "dialog_summary"],
}


class OpenAIResponsesClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        api_url: str,
        system_prompt: str,
        timeout: float = 30.0,
        transport: Optional[Transport] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.api_url = api_url
        self.system_prompt = system_prompt
        self.timeout = timeout
        self.transport = transport or post_json
        self.logger = logger or logging.getLogger(__name__)

    def generate_reply(
        self,
        messages: Iterable[ChatMessage],
        correlation_id: str,
        user_reference: str,
        instructions: Optional[str] = None,
    ) -> str:
        payload = {
            "model": self.model,
            "instructions": instructions or self.system_prompt,
            "input": [message.to_openai_input() for message in messages],
        }
        self.logger.debug(
            "Calling OpenAI responses API correlation_id=%s model=%s message_count=%s user_reference=%s",
            correlation_id,
            self.model,
            len(payload["input"]),
            user_reference,
        )
        response = self.transport(
            self.api_url,
            payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "X-Client-Request-Id": correlation_id,
            },
            timeout=self.timeout,
        )
        self.logger.debug(
            "Received OpenAI response correlation_id=%s status=%s x_request_id=%s",
            correlation_id,
            response.status_code,
            response.headers.get("x-request-id") or response.headers.get("X-Request-Id"),
        )
        return extract_output_text(response.body)

    def summarize_dialogue(
        self,
        transcript: str,
        existing_personal_memory: Sequence[Dict[str, str]],
        correlation_id: str,
        user_reference: str,
    ) -> Dict[str, Any]:
        existing_personal_json = json.dumps(list(existing_personal_memory), ensure_ascii=False)
        payload = {
            "model": self.model,
            "instructions": (
                "Ты суммаризируешь завершенный диалог пользователя. "
                "Извлекай только устойчивые факты о пользователе в поле personal. "
                "В dialog_summary фиксируй только информацию этого конкретного завершенного диалога. "
                "Суммаризация должна строиться только по тексту переданного transcript."
            ),
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Текущая personal memory пользователя:\n"
                                f"{existing_personal_json}\n\n"
                                "Ниже полный текстовый transcript завершенного диалога. "
                                "Сами документы уже описаны внутри текста и повторно анализироваться не должны.\n\n"
                                f"{transcript}"
                            ),
                        }
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "dialogue_memory_summary",
                    "strict": True,
                    "schema": SUMMARIZATION_SCHEMA,
                }
            },
        }
        self.logger.debug(
            "Calling OpenAI summarization correlation_id=%s model=%s transcript_chars=%s user_reference=%s",
            correlation_id,
            self.model,
            len(transcript),
            user_reference,
        )
        response = self.transport(
            self.api_url,
            payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "X-Client-Request-Id": correlation_id,
            },
            timeout=self.timeout,
        )
        text = extract_output_text(response.body)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExternalServiceError(f"Structured summary is not valid JSON: {text}") from exc
        if not isinstance(parsed, dict):
            raise ExternalServiceError("Structured summary must be a JSON object")
        return parsed


def extract_output_text(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ExternalServiceError("OpenAI response body must be a JSON object")

    output = payload.get("output")
    if not isinstance(output, list):
        raise ExternalServiceError("OpenAI response does not contain an output list")

    chunks: List[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                chunks.append(part["text"])

    text = "\n".join(chunk.strip() for chunk in chunks if chunk.strip()).strip()
    if not text:
        raise ExternalServiceError("OpenAI response did not contain assistant text")
    return text

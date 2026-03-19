from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from .context_store import ChatMessage
from .http_utils import ExternalServiceError, Transport, post_json


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
    ) -> str:
        payload = {
            "model": self.model,
            "instructions": self.system_prompt,
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


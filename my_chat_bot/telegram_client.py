from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .http_utils import ExternalServiceError, Transport, get_bytes, post_json


class TelegramClient:
    def __init__(
        self,
        bot_token: str,
        timeout: float = 35.0,
        transport: Optional[Transport] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.file_base_url = f"https://api.telegram.org/file/bot{bot_token}"
        self.timeout = timeout
        self.transport = transport or post_json
        self.logger = logger or logging.getLogger(__name__)

    def get_updates(self, offset: Optional[int], poll_timeout: int) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "timeout": poll_timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset

        response = self.transport(
            f"{self.base_url}/getUpdates",
            payload,
            headers={},
            timeout=self.timeout + poll_timeout,
        )
        body = _ensure_telegram_ok(response.body)
        result = body.get("result", [])
        if not isinstance(result, list):
            raise ExternalServiceError("Telegram getUpdates returned invalid result")
        return result

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: Optional[int] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id

        self.logger.debug("Sending Telegram message chat_id=%s reply_to=%s", chat_id, reply_to_message_id)
        response = self.transport(
            f"{self.base_url}/sendMessage",
            payload,
            headers={},
            timeout=self.timeout,
        )
        _ensure_telegram_ok(response.body)

    def get_file(self, file_id: str) -> Dict[str, Any]:
        response = self.transport(
            f"{self.base_url}/getFile",
            {"file_id": file_id},
            headers={},
            timeout=self.timeout,
        )
        body = _ensure_telegram_ok(response.body)
        result = body.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("file_path"), str):
            raise ExternalServiceError("Telegram getFile returned invalid result")
        return result

    def download_file(self, file_path: str) -> bytes:
        self.logger.debug("Downloading Telegram file file_path=%s", file_path)
        return get_bytes(f"{self.file_base_url}/{file_path}", timeout=self.timeout)


def _ensure_telegram_ok(payload: object) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ExternalServiceError("Telegram response body must be a JSON object")
    if payload.get("ok") is not True:
        raise ExternalServiceError(f"Telegram API returned an error: {payload}")
    return payload

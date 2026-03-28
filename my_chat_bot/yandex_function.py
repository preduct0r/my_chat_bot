from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from .memory import MemoryService
from .openai_client import OpenAIResponsesClient
from .web_server import WebChatApp, WebServerConfig
from .web_transport import WebRequest
from .ydb_repository import YDBMemoryRepository

_APP: Optional[WebChatApp] = None


@dataclass(frozen=True)
class YandexFunctionConfig:
    openai_api_key: str
    openai_model: str
    openai_api_url: str
    openai_system_prompt: str
    context_size: int
    summary_count: int
    memory_budget: int
    session_timeout_seconds: int
    log_level: str
    ydb_endpoint: str
    ydb_database: str
    static_dir: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "YandexFunctionConfig":
        return cls(
            openai_api_key=_required(env, "OPENAI_API_KEY"),
            openai_model=_required(env, "OPENAI_MODEL"),
            openai_api_url=env.get("OPENAI_API_URL", "https://api.openai.com/v1/responses"),
            openai_system_prompt=env.get(
                "OPENAI_SYSTEM_PROMPT",
                "Ты полезный web-ассистент. Отвечай кратко, по делу и на языке пользователя.",
            ),
            context_size=_positive_int(env.get("CONTEXT_SIZE", "20"), "CONTEXT_SIZE"),
            summary_count=_non_negative_int(env.get("SUMMARY_COUNT", "10"), "SUMMARY_COUNT"),
            memory_budget=_positive_int(env.get("MEMORY_BUDGET", "2000"), "MEMORY_BUDGET"),
            session_timeout_seconds=_positive_int(
                env.get("SESSION_TIMEOUT_SECONDS", "3600"),
                "SESSION_TIMEOUT_SECONDS",
            ),
            log_level=env.get("LOG_LEVEL", "INFO").upper(),
            ydb_endpoint=_required(env, "YDB_ENDPOINT"),
            ydb_database=_required(env, "YDB_DATABASE"),
            static_dir=env.get(
                "STATIC_DIR",
                str(Path(__file__).resolve().parent.parent / "web"),
            ),
        )


def handler(event: Mapping[str, Any], context: Any) -> Mapping[str, Any]:
    try:
        app = _get_app()
        request = _request_from_event(event)
        logging.getLogger(__name__).info(
            "Yandex function request method=%s path=%s static_dir=%s",
            request.method,
            request.path,
            getattr(app, "static_dir", "<unknown>"),
        )
        response = app.handle_request(request)
        return {
            "statusCode": response.status_code,
            "headers": response.headers,
            "body": response.body.decode("utf-8"),
            "isBase64Encoded": False,
        }
    except Exception:
        logging.getLogger(__name__).exception("Unhandled Yandex Cloud Function error")
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            "body": json.dumps({"error": "internal server error"}, ensure_ascii=False),
            "isBase64Encoded": False,
        }


def _get_app() -> WebChatApp:
    global _APP
    if _APP is not None:
        return _APP

    config = YandexFunctionConfig.from_env(os.environ)
    _configure_logging(config.log_level)

    openai_client = OpenAIResponsesClient(
        api_key=config.openai_api_key,
        model=config.openai_model,
        api_url=config.openai_api_url,
        system_prompt=config.openai_system_prompt,
    )
    memory_service = MemoryService(
        repository=YDBMemoryRepository(
            endpoint=config.ydb_endpoint,
            database=config.ydb_database,
        ),
        openai_client=openai_client,
        context_size=config.context_size,
        summary_count=config.summary_count,
        memory_budget=config.memory_budget,
        session_timeout_seconds=config.session_timeout_seconds,
        base_system_prompt=config.openai_system_prompt,
    )
    _APP = WebChatApp(
        memory_service=memory_service,
        openai_client=openai_client,
        config=WebServerConfig(host="0.0.0.0", port=8080, static_dir=config.static_dir),
    )
    logging.getLogger(__name__).info(
        "Initialized Yandex function app static_dir=%s exists=%s",
        _APP.static_dir,
        _APP.static_dir.exists(),
    )
    return _APP


def _request_from_event(event: Mapping[str, Any]) -> WebRequest:
    headers = event.get("headers") or {}
    if not isinstance(headers, Mapping):
        headers = {}

    body = event.get("body") or ""
    if isinstance(body, str):
        if event.get("isBase64Encoded"):
            body_bytes = base64.b64decode(body)
        else:
            body_bytes = body.encode("utf-8")
    elif isinstance(body, bytes):
        body_bytes = body
    else:
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

    path = _extract_path(event)
    method = _extract_method(event)
    return WebRequest(
        method=method,
        path=path,
        headers={str(key): str(value) for key, value in headers.items()},
        body=body_bytes,
    )


def _configure_logging(log_level: str) -> None:
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=getattr(logging, log_level.upper(), logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        return
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {key}")
    return value


def _positive_int(value: str, key: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return parsed


def _non_negative_int(value: str, key: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{key} must be zero or a positive integer")
    return parsed


def _extract_path(event: Mapping[str, Any]) -> str:
    for candidate in (
        event.get("rawPath"),
        event.get("path"),
        event.get("url"),
    ):
        normalized = _normalize_path(candidate)
        if normalized is not None:
            return normalized

    request_context = event.get("requestContext")
    if isinstance(request_context, Mapping):
        http_context = request_context.get("http")
        if isinstance(http_context, Mapping):
            normalized = _normalize_path(http_context.get("path"))
            if normalized is not None:
                return normalized

    return "/"


def _extract_method(event: Mapping[str, Any]) -> str:
    http_method = event.get("httpMethod")
    if isinstance(http_method, str) and http_method.strip():
        return http_method.upper()

    request_context = event.get("requestContext")
    if isinstance(request_context, Mapping):
        http_context = request_context.get("http")
        if isinstance(http_context, Mapping):
            method = http_context.get("method")
            if isinstance(method, str) and method.strip():
                return method.upper()

    return "GET"


def _normalize_path(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    without_query = raw.split("?", 1)[0]
    if without_query.startswith("http://") or without_query.startswith("https://"):
        slash_index = without_query.find("/", without_query.find("://") + 3)
        without_query = without_query[slash_index:] if slash_index >= 0 else "/"
    if not without_query.startswith("/"):
        without_query = "/" + without_query
    return without_query

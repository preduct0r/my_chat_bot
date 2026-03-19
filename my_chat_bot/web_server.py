from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from .context_store import ChatMessage
from .http_utils import ExternalServiceError
from .memory import MemoryService, WebIdentity
from .openai_client import OpenAIResponsesClient

SESSION_COOKIE_NAME = "my_chat_bot_web_session"


@dataclass(frozen=True)
class WebServerConfig:
    host: str
    port: int
    static_dir: str


class WebChatHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address,
        request_handler_class,
        app: "WebChatApp",
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.app = app


class WebChatApp:
    def __init__(
        self,
        memory_service: MemoryService,
        openai_client: OpenAIResponsesClient,
        config: WebServerConfig,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.memory_service = memory_service
        self.openai_client = openai_client
        self.config = config
        self.static_dir = Path(config.static_dir)
        self.logger = logger or logging.getLogger(__name__)
        self._last_maintenance_ts = 0.0

    def serve_forever(self) -> None:
        server = WebChatHTTPServer((self.config.host, self.config.port), _build_handler(), self)
        self.logger.info(
            "Starting web chat server host=%s port=%s static_dir=%s",
            self.config.host,
            self.config.port,
            self.static_dir,
        )
        server.serve_forever()

    def maybe_run_maintenance(self) -> None:
        now = time.time()
        if now - self._last_maintenance_ts >= 60:
            self.memory_service.summarize_expired_sessions()
            self._last_maintenance_ts = now

    def get_or_create_identity(self, session_token: Optional[str]) -> WebIdentity:
        return self.memory_service.get_or_create_web_identity(session_token)

    def get_state(self, identity: WebIdentity) -> Dict[str, Any]:
        messages = [
            {"role": message.role, "text": message.to_preview_text()}
            for message in self.memory_service.get_active_dialogue_messages(identity.memory_user_id)
        ]
        return {
            "linkedTelegramUserId": identity.linked_telegram_user_id,
            "memoryUserId": identity.memory_user_id,
            "messages": messages,
        }

    def link_identity(self, identity: WebIdentity, code: str) -> Optional[WebIdentity]:
        return self.memory_service.link_web_identity(identity.session_token, code.strip().upper())

    def handle_chat(self, identity: WebIdentity, text: str) -> Dict[str, Any]:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("message must not be empty")

        correlation_id = f"web-{int(time.time() * 1000)}"
        prepared = self.memory_service.prepare_conversation(
            telegram_user_id=identity.memory_user_id,
            message=ChatMessage.from_text(role="user", text=clean_text),
            summary_text=f"Пользователь: {clean_text}",
            correlation_id=correlation_id,
        )
        reply = self.openai_client.generate_reply(
            messages=prepared.input_messages,
            correlation_id=correlation_id,
            user_reference=str(identity.memory_user_id),
            instructions=prepared.instructions,
        )
        self.memory_service.store_assistant_reply(prepared.session_id, reply)
        return {
            "reply": reply,
            "linkedTelegramUserId": identity.linked_telegram_user_id,
            "memoryUserId": identity.memory_user_id,
            "promptPreview": prepared.prompt_preview,
        }


def _build_handler():
    class Handler(BaseHTTPRequestHandler):
        server: WebChatHTTPServer

        def do_GET(self) -> None:
            self.server.app.maybe_run_maintenance()
            parsed = urlparse(self.path)
            if parsed.path == "/api/state":
                self._handle_state()
                return
            if parsed.path == "/":
                self._serve_static("index.html", content_type="text/html; charset=utf-8")
                return
            if parsed.path == "/app.js":
                self._serve_static("app.js", content_type="application/javascript; charset=utf-8")
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            self.server.app.maybe_run_maintenance()
            parsed = urlparse(self.path)
            if parsed.path == "/api/link":
                self._handle_link()
                return
            if parsed.path == "/api/chat":
                self._handle_chat()
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: Any) -> None:
            self.server.app.logger.info("web %s - %s", self.address_string(), format % args)

        def _handle_state(self) -> None:
            identity, is_new = self._resolve_identity()
            self._write_json(HTTPStatus.OK, self.server.app.get_state(identity), session_token=identity.session_token if is_new else None)

        def _handle_link(self) -> None:
            identity, is_new = self._resolve_identity()
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._write_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": str(exc)},
                    session_token=identity.session_token if is_new else None,
                )
                return
            code = str(payload.get("code", "")).strip()
            if not code:
                self._write_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "code is required"},
                    session_token=identity.session_token if is_new else None,
                )
                return
            linked = self.server.app.link_identity(identity, code)
            if linked is None:
                self._write_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid or expired code"},
                    session_token=identity.session_token if is_new else None,
                )
                return
            self._write_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "linkedTelegramUserId": linked.linked_telegram_user_id,
                    "memoryUserId": linked.memory_user_id,
                },
                session_token=linked.session_token if is_new else None,
            )

        def _handle_chat(self) -> None:
            identity, is_new = self._resolve_identity()
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._write_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": str(exc)},
                    session_token=identity.session_token if is_new else None,
                )
                return
            code = str(payload.get("code", "")).strip()
            if code:
                linked = self.server.app.link_identity(identity, code)
                if linked is None:
                    self._write_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "invalid or expired code"},
                        session_token=identity.session_token if is_new else None,
                    )
                    return
                identity = linked

            try:
                response_payload = self.server.app.handle_chat(identity, str(payload.get("message", "")))
            except ValueError as exc:
                self._write_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": str(exc)},
                    session_token=identity.session_token if is_new else None,
                )
                return
            except ExternalServiceError as exc:
                self.server.app.logger.exception("Web OpenAI request failed")
                self._write_json(
                    HTTPStatus.BAD_GATEWAY,
                    {"error": str(exc)},
                    session_token=identity.session_token if is_new else None,
                )
                return

            self._write_json(
                HTTPStatus.OK,
                response_payload,
                session_token=identity.session_token if is_new else None,
            )

        def _resolve_identity(self) -> tuple[WebIdentity, bool]:
            session_token = self._read_session_cookie()
            identity = self.server.app.get_or_create_identity(session_token)
            return identity, session_token != identity.session_token

        def _read_session_cookie(self) -> Optional[str]:
            raw_cookie = self.headers.get("Cookie")
            if not raw_cookie:
                return None
            cookie = SimpleCookie()
            cookie.load(raw_cookie)
            morsel = cookie.get(SESSION_COOKIE_NAME)
            if morsel is None:
                return None
            return morsel.value

        def _read_json_body(self) -> Dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                raise ValueError("invalid JSON body")
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def _serve_static(self, filename: str, content_type: str) -> None:
            path = self.server.app.static_dir / filename
            if not path.exists():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            contents = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(contents)))
            self.end_headers()
            self.wfile.write(contents)

        def _write_json(
            self,
            status: HTTPStatus,
            payload: Dict[str, Any],
            session_token: Optional[str] = None,
        ) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            if session_token:
                cookie = SimpleCookie()
                cookie[SESSION_COOKIE_NAME] = session_token
                cookie[SESSION_COOKIE_NAME]["path"] = "/"
                cookie[SESSION_COOKIE_NAME]["httponly"] = True
                cookie[SESSION_COOKIE_NAME]["samesite"] = "Lax"
                self.send_header("Set-Cookie", cookie.output(header="").strip())
            self.end_headers()
            self.wfile.write(raw)

    return Handler

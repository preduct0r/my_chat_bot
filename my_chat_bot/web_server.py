from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from .attachments import (
    DEFAULT_ATTACHMENT_PROMPT,
    SUPPORTED_ATTACHMENT_MESSAGE,
    IncomingAttachment,
    build_user_message,
    build_user_summary_text,
    incoming_attachment_from_web_payload,
)
from .http_utils import ExternalServiceError
from .memory import MemoryService, WebIdentity
from .openai_client import OpenAIResponsesClient
from .web_transport import WebRequest, WebResponse

SESSION_TOKEN_HEADER = "X-Session-Token"


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
        return self.handle_chat_with_attachments(identity=identity, text=text, attachments=[])

    def handle_chat_with_attachments(
        self,
        identity: WebIdentity,
        text: str,
        attachments: list[IncomingAttachment],
    ) -> Dict[str, Any]:
        clean_text = text.strip()
        if not clean_text and not attachments:
            raise ValueError("message must not be empty")

        prompt_text = clean_text or DEFAULT_ATTACHMENT_PROMPT
        correlation_id = f"web-{int(time.time() * 1000)}"
        prepared = self.memory_service.prepare_conversation(
            telegram_user_id=identity.memory_user_id,
            message=build_user_message(prompt_text, attachments),
            summary_text=build_user_summary_text(prompt_text, attachments),
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

    def handle_request(self, request: WebRequest) -> WebResponse:
        self.maybe_run_maintenance()

        if request.method == "GET" and request.path == "/api/state":
            identity = self._resolve_identity(request)
            return self._json_response(HTTPStatus.OK, self._with_session_token(self.get_state(identity), identity))

        if request.method == "POST" and request.path == "/api/link":
            return self._handle_link_request(request)

        if request.method == "POST" and request.path == "/api/chat":
            return self._handle_chat_request(request)

        if request.method == "GET" and request.path == "/":
            return self._static_response("index.html", "text/html; charset=utf-8")

        if request.method == "GET" and request.path == "/app.js":
            return self._static_response("app.js", "application/javascript; charset=utf-8")

        return self._json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _handle_link_request(self, request: WebRequest) -> WebResponse:
        identity = self._resolve_identity(request)
        try:
            payload = _read_json_body(request.body)
        except ValueError as exc:
            return self._json_response(HTTPStatus.BAD_REQUEST, self._with_session_token({"error": str(exc)}, identity))

        code = str(payload.get("code", "")).strip()
        if not code:
            return self._json_response(
                HTTPStatus.BAD_REQUEST,
                self._with_session_token({"error": "code is required"}, identity),
            )

        linked = self.link_identity(identity, code)
        if linked is None:
            return self._json_response(
                HTTPStatus.BAD_REQUEST,
                self._with_session_token({"error": "invalid or expired code"}, identity),
            )

        return self._json_response(
            HTTPStatus.OK,
            self._with_session_token(
                {
                    "ok": True,
                    "linkedTelegramUserId": linked.linked_telegram_user_id,
                    "memoryUserId": linked.memory_user_id,
                },
                linked,
            ),
        )

    def _handle_chat_request(self, request: WebRequest) -> WebResponse:
        identity = self._resolve_identity(request)
        try:
            payload = _read_json_body(request.body)
        except ValueError as exc:
            return self._json_response(HTTPStatus.BAD_REQUEST, self._with_session_token({"error": str(exc)}, identity))

        code = str(payload.get("code", "")).strip()
        if code:
            linked = self.link_identity(identity, code)
            if linked is None:
                return self._json_response(
                    HTTPStatus.BAD_REQUEST,
                    self._with_session_token({"error": "invalid or expired code"}, identity),
                )
            identity = linked

        try:
            attachments = _read_attachments_from_payload(payload)
            response_payload = self.handle_chat_with_attachments(
                identity,
                str(payload.get("message", "")),
                attachments,
            )
        except UnsupportedAttachmentError:
            return self._json_response(
                HTTPStatus.BAD_REQUEST,
                self._with_session_token({"error": SUPPORTED_ATTACHMENT_MESSAGE}, identity),
            )
        except ValueError as exc:
            return self._json_response(HTTPStatus.BAD_REQUEST, self._with_session_token({"error": str(exc)}, identity))
        except ExternalServiceError as exc:
            self.logger.exception("Web OpenAI request failed")
            return self._json_response(HTTPStatus.BAD_GATEWAY, self._with_session_token({"error": str(exc)}, identity))

        return self._json_response(HTTPStatus.OK, self._with_session_token(response_payload, identity))

    def _resolve_identity(self, request: WebRequest) -> WebIdentity:
        return self.get_or_create_identity(request.header(SESSION_TOKEN_HEADER))

    def _with_session_token(self, payload: Dict[str, Any], identity: WebIdentity) -> Dict[str, Any]:
        response_payload = dict(payload)
        response_payload["sessionToken"] = identity.session_token
        return response_payload

    def _static_response(self, filename: str, content_type: str) -> WebResponse:
        path = self.static_dir / filename
        if not path.exists():
            return self._json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})
        return WebResponse(
            status_code=int(HTTPStatus.OK),
            headers={
                "Content-Type": content_type,
                "Cache-Control": "no-store",
            },
            body=path.read_bytes(),
        )

    def _json_response(self, status: HTTPStatus, payload: Dict[str, Any]) -> WebResponse:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return WebResponse(
            status_code=int(status),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            body=raw,
        )


def _read_json_body(body: bytes) -> Dict[str, Any]:
    raw = body or b"{}"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


class UnsupportedAttachmentError(ValueError):
    pass


def _read_attachments_from_payload(payload: Dict[str, Any]) -> list[IncomingAttachment]:
    raw_attachments = payload.get("attachments", [])
    if raw_attachments in (None, ""):
        return []
    if not isinstance(raw_attachments, list):
        raise ValueError("attachments must be an array")

    attachments: list[IncomingAttachment] = []
    for raw_attachment in raw_attachments:
        if not isinstance(raw_attachment, dict):
            raise ValueError("each attachment must be an object")
        try:
            attachments.append(incoming_attachment_from_web_payload(raw_attachment))
        except ValueError as exc:
            if "Unsupported attachment type" in str(exc):
                raise UnsupportedAttachmentError(str(exc)) from exc
            raise
    return attachments


def _build_handler():
    class Handler(BaseHTTPRequestHandler):
        server: WebChatHTTPServer

        def do_GET(self) -> None:
            self._dispatch_request()

        def do_POST(self) -> None:
            self._dispatch_request()

        def log_message(self, format: str, *args: Any) -> None:
            self.server.app.logger.info("web %s - %s", self.address_string(), format % args)

        def _dispatch_request(self) -> None:
            parsed = urlparse(self.path)
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length) if content_length > 0 else b""
            request = WebRequest(
                method=self.command,
                path=parsed.path,
                headers={key: value for key, value in self.headers.items()},
                body=body,
            )
            response = self.server.app.handle_request(request)
            self._write_response(response)

        def _write_response(self, response: WebResponse) -> None:
            self.send_response(response.status_code)
            has_content_length = False
            for key, value in response.headers.items():
                if key.lower() == "content-length":
                    has_content_length = True
                self.send_header(key, value)
            if not has_content_length:
                self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            if response.body:
                self.wfile.write(response.body)

    return Handler

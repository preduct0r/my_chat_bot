from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default as default_email_policy
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .attachments import IncomingAttachment, create_attachment
from .chat_inputs import (
    DEFAULT_ATTACHMENT_PROMPT,
    SUPPORTED_ATTACHMENT_MESSAGE,
    build_user_message,
    build_user_summary_text,
)
from .http_utils import ExternalServiceError
from .memory import MemoryService, WebIdentity
from .openai_client import OpenAIResponsesClient

SESSION_COOKIE_NAME = "my_chat_bot_web_session"


@dataclass(frozen=True)
class WebServerConfig:
    host: str
    port: int
    static_dir: str


@dataclass(frozen=True)
class MultipartFile:
    field_name: str
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class MultipartFormData:
    fields: Dict[str, str]
    files: List[MultipartFile]


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

    def handle_chat(
        self,
        identity: WebIdentity,
        text: str,
        attachments: Optional[List[IncomingAttachment]] = None,
    ) -> Dict[str, Any]:
        incoming_attachments = list(attachments or ())
        clean_text = text.strip()
        if not clean_text and not incoming_attachments:
            raise ValueError("message must not be empty")

        correlation_id = f"web-{int(time.time() * 1000)}"
        prompt_text = clean_text or DEFAULT_ATTACHMENT_PROMPT
        user_message = build_user_message(prompt_text, incoming_attachments)
        user_summary_text = build_user_summary_text(prompt_text, incoming_attachments)
        self.logger.info(
            "Received web chat correlation_id=%s memory_user_id=%s attachments=%s",
            correlation_id,
            identity.memory_user_id,
            len(incoming_attachments),
        )
        prepared = self.memory_service.prepare_conversation(
            telegram_user_id=identity.memory_user_id,
            message=user_message,
            summary_text=user_summary_text,
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
            if parsed.path == "/app_logic.js":
                self._serve_static("app_logic.js", content_type="application/javascript; charset=utf-8")
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
                payload, attachments = self._read_chat_payload()
            except UnsupportedAttachmentError as exc:
                self.server.app.logger.warning("Web upload rejected error=%s", exc)
                self._write_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": SUPPORTED_ATTACHMENT_MESSAGE},
                    session_token=identity.session_token if is_new else None,
                )
                return
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
                response_payload = self.server.app.handle_chat(
                    identity,
                    str(payload.get("message", "")),
                    attachments=attachments,
                )
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

        def _read_chat_payload(self) -> tuple[Dict[str, Any], List[IncomingAttachment]]:
            content_type = self.headers.get("Content-Type", "")
            if content_type.lower().startswith("multipart/form-data"):
                form_data = self._read_multipart_form_data()
                return (
                    {
                        "message": form_data.fields.get("message", ""),
                        "code": form_data.fields.get("code", ""),
                    },
                    _attachments_from_multipart_files(form_data.files),
                )
            return self._read_json_body(), []

        def _read_json_body(self) -> Dict[str, Any]:
            raw = self._read_body_bytes(default=b"{}")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                raise ValueError("invalid JSON body")
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def _read_multipart_form_data(self) -> MultipartFormData:
            content_type = self.headers.get("Content-Type", "")
            raw = self._read_body_bytes(default=b"")
            return parse_multipart_form_data(content_type, raw)

        def _read_body_bytes(self, default: bytes) -> bytes:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0:
                return default
            return self.rfile.read(content_length)

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


class UnsupportedAttachmentError(Exception):
    """Raised when an uploaded file type is not supported."""


def parse_multipart_form_data(content_type: str, raw_body: bytes) -> MultipartFormData:
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("expected multipart/form-data request")

    message = BytesParser(policy=default_email_policy).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + raw_body
    )
    if not message.is_multipart():
        raise ValueError("invalid multipart/form-data body")

    fields: Dict[str, str] = {}
    files: List[MultipartFile] = []
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        field_name = part.get_param("name", header="content-disposition")
        if not isinstance(field_name, str) or not field_name:
            continue
        filename = part.get_filename()
        if isinstance(filename, str) and filename:
            files.append(
                MultipartFile(
                    field_name=field_name,
                    filename=filename,
                    content_type=part.get_content_type(),
                    data=part.get_payload(decode=True) or b"",
                )
            )
            continue
        charset = part.get_content_charset() or "utf-8"
        fields[field_name] = (part.get_payload(decode=True) or b"").decode(charset, errors="replace")
    return MultipartFormData(fields=fields, files=files)


def _attachments_from_multipart_files(files: List[MultipartFile]) -> List[IncomingAttachment]:
    attachments: List[IncomingAttachment] = []
    for file_item in files:
        if not file_item.filename:
            continue
        try:
            attachments.append(
                create_attachment(
                    filename=file_item.filename,
                    mime_type=file_item.content_type,
                    data=file_item.data,
                )
            )
        except ValueError as exc:
            raise UnsupportedAttachmentError(str(exc)) from exc
    return attachments

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping

from .context_store import ChatMessage

TEXT_FILE_EXTENSIONS = {
    ".c",
    ".cpp",
    ".css",
    ".csv",
    ".go",
    ".html",
    ".java",
    ".js",
    ".json",
    ".md",
    ".py",
    ".rb",
    ".sh",
    ".tex",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
TEXT_FILE_MIME_PREFIXES = ("text/",)
TEXT_FILE_MIME_TYPES = {
    "application/json",
    "application/xml",
    "application/x-sh",
}
IMAGE_MIME_PREFIX = "image/"
PDF_MIME_TYPE = "application/pdf"
RICH_DOCUMENT_MIME_TYPES = {
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
SPREADSHEET_MIME_TYPES = {
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
DEFAULT_ATTACHMENT_PROMPT = "Опиши вложение и ответь по нему."
SUPPORTED_ATTACHMENT_MESSAGE = (
    "Поддерживаются текстовые сообщения, изображения, PDF, DOC, DOCX, XLSX и текстовые файлы."
)


@dataclass(frozen=True)
class IncomingAttachment:
    kind: str
    filename: str
    mime_type: str
    data: bytes

    def summary_description(self) -> str:
        kind_label = {
            "image": "изображение",
            "pdf": "PDF",
            "rich_document": "документ",
            "spreadsheet": "таблицу",
            "text": "текстовый файл",
        }.get(self.kind, "файл")
        return f'Пользователь прикрепил {kind_label} "{self.filename}".'

    def to_content_parts(self) -> List[Dict[str, str]]:
        if self.kind == "image":
            encoded = base64.b64encode(self.data).decode("ascii")
            return [
                {
                    "type": "input_image",
                    "image_url": f"data:{self.mime_type};base64,{encoded}",
                }
            ]

        if self.kind in {"pdf", "rich_document", "spreadsheet"}:
            encoded = base64.b64encode(self.data).decode("ascii")
            return [
                {
                    "type": "input_file",
                    "filename": self.filename,
                    "file_data": f"data:{self.mime_type};base64,{encoded}",
                }
            ]

        if self.kind == "text":
            return [
                {
                    "type": "input_text",
                    "text": f"Содержимое файла {self.filename}:\n{decode_text_attachment(self.data)}",
                }
            ]

        raise ValueError(f"Unsupported attachment kind: {self.kind}")


def classify_attachment(filename: str, mime_type: str) -> str:
    normalized_mime = (mime_type or "").lower()
    suffix = Path(filename).suffix.lower()

    if normalized_mime == PDF_MIME_TYPE or suffix == ".pdf":
        return "pdf"
    if normalized_mime in RICH_DOCUMENT_MIME_TYPES or suffix in {".doc", ".docx"}:
        return "rich_document"
    if normalized_mime in SPREADSHEET_MIME_TYPES or suffix in {".xls", ".xlsx"}:
        return "spreadsheet"
    if normalized_mime.startswith(IMAGE_MIME_PREFIX) or suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return "image"
    if (
        normalized_mime.startswith(TEXT_FILE_MIME_PREFIXES)
        or normalized_mime in TEXT_FILE_MIME_TYPES
        or suffix in TEXT_FILE_EXTENSIONS
    ):
        return "text"
    raise ValueError(f"Unsupported attachment type: filename={filename} mime_type={mime_type}")


def decode_text_attachment(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "ascii"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def incoming_attachment_from_web_payload(payload: Mapping[str, Any]) -> IncomingAttachment:
    filename = str(payload.get("filename", "")).strip()
    mime_type = str(payload.get("mimeType", "")).strip()
    data_base64 = str(payload.get("dataBase64", "")).strip()

    if not filename:
        raise ValueError("attachment filename is required")
    if not data_base64:
        raise ValueError(f'attachment "{filename}" must include dataBase64')

    try:
        data = base64.b64decode(data_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'attachment "{filename}" contains invalid base64 data') from exc

    kind = classify_attachment(filename=filename, mime_type=mime_type)
    return IncomingAttachment(
        kind=kind,
        filename=filename,
        mime_type=_normalize_mime_type(kind, mime_type),
        data=data,
    )


def build_user_message(prompt_text: str, attachments: List[IncomingAttachment]) -> ChatMessage:
    content_parts: List[Dict[str, str]] = [{"type": "input_text", "text": prompt_text}]
    for attachment in attachments:
        content_parts.extend(attachment.to_content_parts())
    return ChatMessage(role="user", content=tuple(content_parts))


def build_user_summary_text(prompt_text: str, attachments: List[IncomingAttachment]) -> str:
    attachment_descriptions = [attachment.summary_description() for attachment in attachments]
    lines = [f"Пользователь: {prompt_text}"]
    lines.extend(attachment_descriptions)
    return "\n".join(lines)


def _normalize_mime_type(kind: str, mime_type: str) -> str:
    clean_mime_type = (mime_type or "").strip()
    if clean_mime_type:
        return clean_mime_type
    if kind == "image":
        return "image/jpeg"
    if kind == "pdf":
        return "application/pdf"
    if kind == "rich_document":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if kind == "spreadsheet":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return "text/plain"

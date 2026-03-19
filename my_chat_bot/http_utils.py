from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional


class ExternalServiceError(RuntimeError):
    """Raised when an external HTTP service returns an invalid response."""


@dataclass
class HttpResponse:
    status_code: int
    body: Any
    headers: Dict[str, str]


Transport = Callable[[str, Mapping[str, Any], Mapping[str, str], float], HttpResponse]


def post_json(
    url: str,
    payload: Mapping[str, Any],
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = 30.0,
) -> HttpResponse:
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if headers:
        request_headers.update(headers)

    request_body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url=url,
        data=request_body,
        headers=request_headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8")
            parsed_body = json.loads(raw_body) if raw_body else {}
            return HttpResponse(
                status_code=response.getcode(),
                body=parsed_body,
                headers=dict(response.headers.items()),
            )
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8")
        parsed_body = _safe_parse_json(raw_body)
        raise ExternalServiceError(
            f"HTTP {exc.code} returned by external service: {parsed_body or raw_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ExternalServiceError(f"Failed to reach external service: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ExternalServiceError("External service returned invalid JSON") from exc


def get_bytes(
    url: str,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = 30.0,
) -> bytes:
    request = urllib.request.Request(
        url=url,
        headers=dict(headers or {}),
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        raise ExternalServiceError(
            f"HTTP {exc.code} returned by external service while downloading bytes: {raw_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ExternalServiceError(f"Failed to reach external service: {exc}") from exc


def _safe_parse_json(raw_body: str) -> Any:
    if not raw_body:
        return None
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError:
        return raw_body

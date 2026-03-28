from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict


class ConfigError(ValueError):
    """Raised when application configuration is invalid."""


@dataclass(frozen=True)
class AppConfig:
    telegram_bot_token: str
    openai_api_key: str
    openai_model: str
    openai_api_url: str
    openai_system_prompt: str
    app_url: str
    app_name: str
    context_size: int
    summary_count: int
    memory_budget: int
    session_timeout_seconds: int
    memory_db_path: str
    poll_timeout: int
    log_level: str

    @classmethod
    def from_env_file(
        cls,
        env_path: str,
        context_size: int,
        summary_count: int,
        memory_budget: int,
        session_timeout_seconds: int,
        memory_db_path: str,
        poll_timeout: int,
        log_level: str,
        require_telegram_bot_token: bool = True,
    ) -> "AppConfig":
        if context_size <= 0:
            raise ConfigError("context_size must be a positive integer")
        if summary_count < 0:
            raise ConfigError("summary_count must be zero or a positive integer")
        if memory_budget <= 0:
            raise ConfigError("memory_budget must be a positive integer")
        if session_timeout_seconds <= 0:
            raise ConfigError("session_timeout_seconds must be a positive integer")
        if poll_timeout <= 0:
            raise ConfigError("poll_timeout must be a positive integer")

        env = load_dotenv_file(env_path)
        missing_keys = _missing_llm_keys(env)
        if require_telegram_bot_token and not env.get("TELEGRAM_BOT_TOKEN"):
            missing_keys.insert(0, "TELEGRAM_BOT_TOKEN")
        if missing_keys:
            raise ConfigError("Missing required variables in .env: " + ", ".join(missing_keys))

        return cls(
            telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN", ""),
            openai_api_key=resolve_llm_api_key(env),
            openai_model=resolve_llm_model(env),
            openai_api_url=resolve_llm_api_url(env),
            openai_system_prompt=env.get(
                "OPENAI_SYSTEM_PROMPT",
                "Ты полезный Telegram-бот. Отвечай кратко, по делу и на языке пользователя.",
            ),
            app_url=resolve_app_url(env),
            app_name=resolve_app_name(env),
            context_size=context_size,
            summary_count=summary_count,
            memory_budget=memory_budget,
            session_timeout_seconds=session_timeout_seconds,
            memory_db_path=memory_db_path,
            poll_timeout=poll_timeout,
            log_level=log_level.upper(),
        )


def load_dotenv_file(env_path: str) -> Dict[str, str]:
    path = Path(env_path)
    if not path.exists():
        raise ConfigError(f".env file was not found: {env_path}")

    env: Dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"Invalid .env line {line_number}: {raw_line}")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        env[key] = _strip_quotes(value)
    return env


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def resolve_llm_api_key(env: Dict[str, str]) -> str:
    return env.get("OPENROUTER_API_KEY") or env.get("OPENAI_API_KEY", "")


def resolve_llm_model(env: Dict[str, str]) -> str:
    return env.get("OPENROUTER_MODEL") or env.get("OPENAI_MODEL", "")


def resolve_llm_api_url(env: Dict[str, str]) -> str:
    explicit_url = env.get("OPENROUTER_API_URL") or env.get("OPENAI_API_URL")
    if explicit_url:
        return explicit_url
    if env.get("OPENROUTER_API_KEY"):
        return "https://openrouter.ai/api/v1/responses"
    return "https://api.openai.com/v1/responses"


def resolve_app_url(env: Dict[str, str]) -> str:
    raw = env.get("OPENAI_APP_URL") or env.get("OPENROUTER_APP_URL") or env.get("APP_DOMAIN", "")
    return _normalize_app_url(raw)


def resolve_app_name(env: Dict[str, str]) -> str:
    return (
        env.get("OPENAI_APP_NAME")
        or env.get("OPENROUTER_APP_NAME")
        or env.get("APP_NAME")
        or env.get("APP_DOMAIN")
        or "my-chat-bot"
    )


def _missing_llm_keys(env: Dict[str, str]) -> list[str]:
    missing: list[str] = []
    if not resolve_llm_api_key(env):
        missing.append("OPENAI_API_KEY or OPENROUTER_API_KEY")
    if not resolve_llm_model(env):
        missing.append("OPENAI_MODEL or OPENROUTER_MODEL")
    return missing


def _normalize_app_url(raw: str) -> str:
    clean = raw.strip()
    if not clean:
        return ""
    if clean.startswith("http://") or clean.startswith("https://"):
        return clean
    return f"https://{clean}"

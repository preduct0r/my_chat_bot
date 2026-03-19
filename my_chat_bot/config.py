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
        required_keys = [
            "TELEGRAM_BOT_TOKEN",
            "OPENAI_API_KEY",
            "OPENAI_MODEL",
        ]
        missing_keys = [key for key in required_keys if not env.get(key)]
        if missing_keys:
            raise ConfigError(
                "Missing required variables in .env: " + ", ".join(sorted(missing_keys))
            )

        return cls(
            telegram_bot_token=env["TELEGRAM_BOT_TOKEN"],
            openai_api_key=env["OPENAI_API_KEY"],
            openai_model=env["OPENAI_MODEL"],
            openai_api_url=env.get("OPENAI_API_URL", "https://api.openai.com/v1/responses"),
            openai_system_prompt=env.get(
                "OPENAI_SYSTEM_PROMPT",
                "Ты полезный Telegram-бот. Отвечай кратко, по делу и на языке пользователя.",
            ),
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

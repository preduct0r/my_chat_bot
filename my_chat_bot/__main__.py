from __future__ import annotations

import argparse
import logging

from .bot import TelegramBotApp
from .config import AppConfig, ConfigError
from .memory import MemoryService, SQLiteMemoryRepository
from .openai_client import OpenAIResponsesClient
from .telegram_client import TelegramClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple Telegram bot with OpenAI integration")
    parser.add_argument(
        "--context-size",
        type=int,
        required=True,
        help="How many last messages from the active dialogue should be sent to the model",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the .env file with bot and OpenAI credentials",
    )
    parser.add_argument(
        "--summary-count",
        type=int,
        default=3,
        help="How many recent dialogue summaries can be included in long-term memory",
    )
    parser.add_argument(
        "--memory-budget",
        type=int,
        default=1200,
        help="Approximate token budget for personal memory and previous dialogue summaries",
    )
    parser.add_argument(
        "--session-timeout-seconds",
        type=int,
        default=3600,
        help="How many seconds of inactivity close the current dialogue session",
    )
    parser.add_argument(
        "--memory-db-path",
        default="data/bot_memory.sqlite3",
        help="Path to the SQLite file used for persistent memory",
    )
    parser.add_argument(
        "--poll-timeout",
        type=int,
        default=30,
        help="Telegram long polling timeout in seconds",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level, for example DEBUG, INFO, WARNING",
    )
    return parser


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        config = AppConfig.from_env_file(
            env_path=args.env_file,
            context_size=args.context_size,
            summary_count=args.summary_count,
            memory_budget=args.memory_budget,
            session_timeout_seconds=args.session_timeout_seconds,
            memory_db_path=args.memory_db_path,
            poll_timeout=args.poll_timeout,
            log_level=args.log_level,
        )
    except ConfigError as exc:
        parser.error(str(exc))

    configure_logging(config.log_level)

    telegram_client = TelegramClient(bot_token=config.telegram_bot_token)
    openai_client = OpenAIResponsesClient(
        api_key=config.openai_api_key,
        model=config.openai_model,
        api_url=config.openai_api_url,
        system_prompt=config.openai_system_prompt,
    )
    memory_repository = SQLiteMemoryRepository(db_path=config.memory_db_path)
    memory_service = MemoryService(
        repository=memory_repository,
        openai_client=openai_client,
        context_size=config.context_size,
        summary_count=config.summary_count,
        memory_budget=config.memory_budget,
        session_timeout_seconds=config.session_timeout_seconds,
        base_system_prompt=config.openai_system_prompt,
    )

    app = TelegramBotApp(
        telegram_client=telegram_client,
        openai_client=openai_client,
        memory_service=memory_service,
        poll_timeout=config.poll_timeout,
    )
    app.run_forever()


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import logging

from .bot import TelegramBotApp
from .config import AppConfig, ConfigError
from .context_store import RecentMessageStore
from .openai_client import OpenAIResponsesClient
from .telegram_client import TelegramClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple Telegram bot with OpenAI integration")
    parser.add_argument(
        "--context-size",
        type=int,
        required=True,
        help="How many last messages should be stored in context for each chat",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the .env file with bot and OpenAI credentials",
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
    context_store = RecentMessageStore(max_messages=config.context_size)

    app = TelegramBotApp(
        telegram_client=telegram_client,
        openai_client=openai_client,
        context_store=context_store,
        poll_timeout=config.poll_timeout,
    )
    app.run_forever()


if __name__ == "__main__":
    main()


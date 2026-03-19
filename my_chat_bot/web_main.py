from __future__ import annotations

import argparse
import logging

from .config import AppConfig, ConfigError
from .memory import MemoryService, SQLiteMemoryRepository
from .openai_client import OpenAIResponsesClient
from .web_server import WebChatApp, WebServerConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple web chat server with OpenAI integration")
    parser.add_argument("--context-size", type=int, required=True)
    parser.add_argument("--summary-count", type=int, default=3)
    parser.add_argument("--memory-budget", type=int, default=1200)
    parser.add_argument("--session-timeout-seconds", type=int, default=3600)
    parser.add_argument("--memory-db-path", default="data/bot_memory.sqlite3")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--static-dir", default="web")
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
            poll_timeout=30,
            log_level=args.log_level,
        )
    except ConfigError as exc:
        parser.error(str(exc))

    configure_logging(config.log_level)

    openai_client = OpenAIResponsesClient(
        api_key=config.openai_api_key,
        model=config.openai_model,
        api_url=config.openai_api_url,
        system_prompt=config.openai_system_prompt,
    )
    memory_service = MemoryService(
        repository=SQLiteMemoryRepository(config.memory_db_path),
        openai_client=openai_client,
        context_size=config.context_size,
        summary_count=config.summary_count,
        memory_budget=config.memory_budget,
        session_timeout_seconds=config.session_timeout_seconds,
        base_system_prompt=config.openai_system_prompt,
    )
    app = WebChatApp(
        memory_service=memory_service,
        openai_client=openai_client,
        config=WebServerConfig(host=args.host, port=args.port, static_dir=args.static_dir),
    )
    app.serve_forever()


if __name__ == "__main__":
    main()

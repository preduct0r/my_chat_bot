import tempfile
import unittest
from pathlib import Path

from my_chat_bot.config import AppConfig, ConfigError, load_dotenv_file


class ConfigTests(unittest.TestCase):
    def test_load_dotenv_file_supports_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                'TELEGRAM_BOT_TOKEN="tg-token"\n'
                "OPENAI_API_KEY='openai-key'\n"
                "OPENAI_MODEL=gpt-4.1-mini\n",
                encoding="utf-8",
            )

            env = load_dotenv_file(str(env_path))

        self.assertEqual(env["TELEGRAM_BOT_TOKEN"], "tg-token")
        self.assertEqual(env["OPENAI_API_KEY"], "openai-key")
        self.assertEqual(env["OPENAI_MODEL"], "gpt-4.1-mini")

    def test_app_config_reads_required_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "TELEGRAM_BOT_TOKEN=tg-token",
                        "OPENAI_API_KEY=openai-key",
                        "OPENAI_MODEL=gpt-4.1-mini",
                    ]
                ),
                encoding="utf-8",
            )

            config = AppConfig.from_env_file(
                env_path=str(env_path),
                context_size=6,
                poll_timeout=25,
                log_level="debug",
            )

        self.assertEqual(config.telegram_bot_token, "tg-token")
        self.assertEqual(config.openai_api_key, "openai-key")
        self.assertEqual(config.openai_model, "gpt-4.1-mini")
        self.assertEqual(config.context_size, 6)
        self.assertEqual(config.poll_timeout, 25)
        self.assertEqual(config.log_level, "DEBUG")

    def test_missing_required_env_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text("TELEGRAM_BOT_TOKEN=tg-token\n", encoding="utf-8")

            with self.assertRaises(ConfigError):
                AppConfig.from_env_file(
                    env_path=str(env_path),
                    context_size=5,
                    poll_timeout=30,
                    log_level="INFO",
                )

    def test_invalid_context_size_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "TELEGRAM_BOT_TOKEN=tg-token",
                        "OPENAI_API_KEY=openai-key",
                        "OPENAI_MODEL=gpt-4.1-mini",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                AppConfig.from_env_file(
                    env_path=str(env_path),
                    context_size=0,
                    poll_timeout=30,
                    log_level="INFO",
                )


if __name__ == "__main__":
    unittest.main()


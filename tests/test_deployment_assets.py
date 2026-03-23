import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class DeploymentAssetsTests(unittest.TestCase):
    def test_dockerfile_installs_application(self) -> None:
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("FROM python:3.11-slim", dockerfile)
        self.assertIn("COPY my_chat_bot /app/my_chat_bot", dockerfile)
        self.assertIn("COPY web /app/web", dockerfile)
        self.assertIn("python -m pip install --no-cache-dir .", dockerfile)

    def test_docker_compose_exposes_https_via_traefik(self) -> None:
        compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("traefik:latest", compose)
        self.assertIn("--entrypoints.web.address=:80", compose)
        self.assertIn("--entrypoints.websecure.address=:443", compose)
        self.assertIn("--certificatesresolvers.letsencrypt.acme.httpchallenge=true", compose)
        self.assertIn("traefik.http.routers.my-chat-bot-web.rule=Host(`${APP_DOMAIN}`) || Host(`www.${APP_DOMAIN}`)", compose)
        self.assertIn("traefik.http.routers.my-chat-bot-web.tls.certresolver=letsencrypt", compose)
        self.assertIn("./.env:/app/.env:ro", compose)
        self.assertIn("./data:/app/data", compose)
        self.assertIn('${WEB_CONTEXT_SIZE:-20}', compose)
        self.assertIn('${WEB_SUMMARY_COUNT:-5}', compose)
        self.assertIn('${WEB_MEMORY_BUDGET:-2500}', compose)
        self.assertIn("- 0.0.0.0", compose)

    def test_env_example_documents_traefik_settings(self) -> None:
        env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn("APP_DOMAIN=thefem.ru", env_example)
        self.assertIn("TRAEFIK_ACME_EMAIL=you@example.com", env_example)


if __name__ == "__main__":
    unittest.main()

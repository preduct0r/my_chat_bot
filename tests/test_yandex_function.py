import base64
import json
import unittest

from my_chat_bot.web_transport import WebResponse
import my_chat_bot.yandex_function as yandex_function


class FakeApp:
    def __init__(self) -> None:
        self.requests = []

    def handle_request(self, request):
        self.requests.append(request)
        return WebResponse(
            status_code=201,
            headers={"Content-Type": "application/json; charset=utf-8"},
            body=json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8"),
        )


class YandexFunctionTests(unittest.TestCase):
    def tearDown(self) -> None:
        yandex_function._APP = None

    def test_request_from_event_supports_base64_body(self) -> None:
        request = yandex_function._request_from_event(
            {
                "httpMethod": "POST",
                "path": "/api/chat",
                "headers": {"X-Test": "1"},
                "body": base64.b64encode(b'{"message":"hello"}').decode("ascii"),
                "isBase64Encoded": True,
            }
        )

        self.assertEqual(request.method, "POST")
        self.assertEqual(request.path, "/api/chat")
        self.assertEqual(request.header("x-test"), "1")
        self.assertEqual(request.body, b'{"message":"hello"}')

    def test_handler_uses_cached_app_and_returns_http_shape(self) -> None:
        fake_app = FakeApp()
        yandex_function._APP = fake_app

        response = yandex_function.handler(
            {
                "httpMethod": "GET",
                "path": "/api/state",
                "headers": {"X-Session-Token": "abc"},
            },
            context=None,
        )

        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(json.loads(response["body"]), {"ok": True})
        self.assertEqual(fake_app.requests[0].path, "/api/state")
        self.assertEqual(fake_app.requests[0].header("x-session-token"), "abc")

    def test_function_config_does_not_require_telegram_token(self) -> None:
        config = yandex_function.YandexFunctionConfig.from_env(
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_MODEL": "gpt-4.1-mini",
                "YDB_ENDPOINT": "grpcs://example.net:2135",
                "YDB_DATABASE": "/ru-central1/folder/db",
            }
        )

        self.assertEqual(config.openai_api_key, "openai-key")
        self.assertEqual(config.openai_model, "gpt-4.1-mini")
        self.assertEqual(config.ydb_endpoint, "grpcs://example.net:2135")
        self.assertEqual(config.ydb_database, "/ru-central1/folder/db")

    def test_function_config_supports_openrouter_aliases(self) -> None:
        config = yandex_function.YandexFunctionConfig.from_env(
            {
                "OPENROUTER_API_KEY": "openrouter-key",
                "OPENROUTER_MODEL": "openai/gpt-4o-mini",
                "APP_DOMAIN": "thefem.ru",
                "YDB_ENDPOINT": "grpcs://example.net:2135",
                "YDB_DATABASE": "/ru-central1/folder/db",
            }
        )

        self.assertEqual(config.openai_api_key, "openrouter-key")
        self.assertEqual(config.openai_model, "openai/gpt-4o-mini")
        self.assertEqual(config.openai_api_url, "https://openrouter.ai/api/v1/responses")
        self.assertEqual(config.app_url, "https://thefem.ru")

    def test_request_from_event_supports_v2_raw_path(self) -> None:
        request = yandex_function._request_from_event(
            {
                "version": "2.0",
                "rawPath": "/",
                "headers": {},
                "requestContext": {"http": {"method": "GET", "path": "/"}},
            }
        )

        self.assertEqual(request.method, "GET")
        self.assertEqual(request.path, "/")

    def test_request_from_event_uses_actual_url_when_path_is_template(self) -> None:
        request = yandex_function._request_from_event(
            {
                "httpMethod": "GET",
                "path": "/{path+}",
                "url": "/app.js?cache=1",
                "headers": {},
            }
        )

        self.assertEqual(request.path, "/app.js")

    def test_normalize_path_supports_full_url(self) -> None:
        self.assertEqual(
            yandex_function._normalize_path("https://example.org/api/state?x=1"),
            "/api/state",
        )

    def test_request_from_event_uses_path_params_for_greedy_route(self) -> None:
        request = yandex_function._request_from_event(
            {
                "httpMethod": "GET",
                "path": "/{path+}",
                "pathParams": {"path": "api/state"},
                "headers": {},
            }
        )

        self.assertEqual(request.path, "/api/state")


if __name__ == "__main__":
    unittest.main()

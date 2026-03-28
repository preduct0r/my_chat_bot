import unittest

from my_chat_bot.ydb_repository import YDBMemoryRepository


class FakeRow(dict):
    def __getattr__(self, name):
        return self[name]


class FakeResultSet:
    def __init__(self, rows):
        self.rows = rows


class FakePool:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def execute_with_retries(self, query, params=None):
        self.calls.append({"query": query, "params": params})
        if "CREATE TABLE IF NOT EXISTS" in query:
            return []
        if self.responses:
            return self.responses.pop(0)
        return []


class YDBMemoryRepositoryTests(unittest.TestCase):
    def test_get_open_session_maps_rows_to_repository_shape(self) -> None:
        pool = FakePool(
            responses=[
                [
                    FakeResultSet(
                        [
                            FakeRow(
                                id="session-1",
                                telegram_user_id=42,
                                status="open",
                                started_at=100,
                                last_activity_at=101,
                                closed_at=0,
                                summarized_at=0,
                            )
                        ]
                    )
                ],
            ]
        )

        repo = YDBMemoryRepository(endpoint="e", database="d", pool=pool)
        result = repo.get_open_session(42)

        self.assertEqual(result["id"], "session-1")
        self.assertEqual(result["telegram_user_id"], 42)
        self.assertEqual(result["status"], "open")
        self.assertIsNone(result["closed_at"])
        self.assertEqual(pool.calls[-1]["params"]["$telegram_user_id"], 42)

    def test_consume_link_code_marks_code_as_used(self) -> None:
        pool = FakePool(
            responses=[
                [
                    FakeResultSet(
                        [
                            FakeRow(
                                code="ABCD-1234",
                                telegram_user_id=99,
                                created_at=100,
                                expires_at=500,
                                used_at=0,
                            )
                        ]
                    )
                ],
                [],
            ]
        )

        repo = YDBMemoryRepository(endpoint="e", database="d", pool=pool)
        telegram_user_id = repo.consume_link_code("ABCD-1234", now_ts=200)

        self.assertEqual(telegram_user_id, 99)
        self.assertEqual(pool.calls[-1]["params"]["$used_at"], 200)

    def test_get_next_anonymous_user_id_returns_negative_value(self) -> None:
        repo = YDBMemoryRepository(endpoint="e", database="d", pool=FakePool())

        self.assertLess(repo.get_next_anonymous_user_id(), 0)


if __name__ == "__main__":
    unittest.main()

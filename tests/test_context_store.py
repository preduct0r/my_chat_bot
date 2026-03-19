import unittest

from my_chat_bot.context_store import ChatMessage, RecentMessageStore


class RecentMessageStoreTests(unittest.TestCase):
    def test_store_keeps_only_last_n_messages(self) -> None:
        store = RecentMessageStore(max_messages=3)

        store.append(1, ChatMessage(role="user", content="1"))
        store.append(1, ChatMessage(role="assistant", content="2"))
        store.append(1, ChatMessage(role="user", content="3"))
        store.append(1, ChatMessage(role="assistant", content="4"))

        self.assertEqual(
            store.get(1),
            [
                ChatMessage(role="assistant", content="2"),
                ChatMessage(role="user", content="3"),
                ChatMessage(role="assistant", content="4"),
            ],
        )

    def test_store_isolated_per_chat(self) -> None:
        store = RecentMessageStore(max_messages=2)

        store.append(1, ChatMessage(role="user", content="a"))
        store.append(2, ChatMessage(role="user", content="b"))

        self.assertEqual(store.get(1), [ChatMessage(role="user", content="a")])
        self.assertEqual(store.get(2), [ChatMessage(role="user", content="b")])

    def test_clear_removes_chat_history(self) -> None:
        store = RecentMessageStore(max_messages=2)
        store.append(10, ChatMessage(role="user", content="hello"))

        store.clear(10)

        self.assertEqual(store.get(10), [])


if __name__ == "__main__":
    unittest.main()


import unittest

from my_chat_bot.context_store import ChatMessage, RecentMessageStore


class RecentMessageStoreTests(unittest.TestCase):
    def test_from_text_uses_output_text_for_assistant_role(self) -> None:
        message = ChatMessage.from_text(role="assistant", text="hello")

        self.assertEqual(message.content, ({"type": "output_text", "text": "hello"},))

    def test_store_keeps_only_last_n_messages(self) -> None:
        store = RecentMessageStore(max_messages=3)

        store.append(1, ChatMessage.from_text(role="user", text="1"))
        store.append(1, ChatMessage.from_text(role="assistant", text="2"))
        store.append(1, ChatMessage.from_text(role="user", text="3"))
        store.append(1, ChatMessage.from_text(role="assistant", text="4"))

        self.assertEqual(
            store.get(1),
            [
                ChatMessage.from_text(role="assistant", text="2"),
                ChatMessage.from_text(role="user", text="3"),
                ChatMessage.from_text(role="assistant", text="4"),
            ],
        )

    def test_store_isolated_per_chat(self) -> None:
        store = RecentMessageStore(max_messages=2)

        store.append(1, ChatMessage.from_text(role="user", text="a"))
        store.append(2, ChatMessage.from_text(role="user", text="b"))

        self.assertEqual(store.get(1), [ChatMessage.from_text(role="user", text="a")])
        self.assertEqual(store.get(2), [ChatMessage.from_text(role="user", text="b")])

    def test_clear_removes_chat_history(self) -> None:
        store = RecentMessageStore(max_messages=2)
        store.append(10, ChatMessage.from_text(role="user", text="hello"))

        store.clear(10)

        self.assertEqual(store.get(10), [])


if __name__ == "__main__":
    unittest.main()

import importlib.util
import io
import sys
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).with_name("send_to_wechat.py")
if not SOURCE.is_file():
    SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "send_to_wechat.py"
if not SOURCE.is_file():
    SOURCE = Path(__file__).resolve().parents[1] / "send_to_wechat.py"
spec = importlib.util.spec_from_file_location("sender_under_test", SOURCE)
sender = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sender)


class FakeDB:
    def __init__(self, hits=(), messages=()):
        self.hits = list(hits)
        self.messages = list(messages)

    def search_contact(self, query):
        return self.hits

    def get_messages(self, user, limit=20, offset=0):
        return self.messages[offset:offset + limit]

    def get_nickname(self, username):
        return {"member_a": "成员 A"}.get(username, username)


class SenderTests(unittest.TestCase):
    def test_partial_contact_rejected_and_duplicate_blocked(self):
        bot = sender.WeChatAssistant("Ali")
        bot.db = FakeDB(hits=[{"username": "wxid_1", "nick_name": "Alice", "remark": ""}])
        self.assertFalse(bot.resolve_contact("Ali")[0])
        bot.db = FakeDB(hits=[
            {"username": "wxid_1", "nick_name": "Alice", "remark": ""},
            {"username": "wxid_2", "nick_name": "Alice", "remark": ""},
        ])
        self.assertFalse(bot.resolve_contact("Alice")[0])

    def test_same_visible_name_blocks_send_even_with_exact_account(self):
        bot = sender.WeChatAssistant("wxid_1")
        bot.db = FakeDB(hits=[
            {"username": "wxid_1", "nick_name": "Alice", "remark": ""},
            {"username": "wxid_2", "nick_name": "Alice", "remark": ""},
        ])
        self.assertTrue(bot.resolve_contact("wxid_1")[0])
        self.assertFalse(bot._unique_visible_name())

    def test_history_uses_database_without_connect_and_names_group_sender(self):
        bot = sender.WeChatAssistant("Study@chatroom")
        bot.db = FakeDB(hits=[{"username": "Study@chatroom", "nick_name": "Study", "remark": ""}],
                        messages=[{"type": "文本", "content": "Hello", "sender_id": 12,
                                   "sender_username": "member_a", "create_time": 1}])
        with patch.object(bot, "connect", side_effect=AssertionError("UI must not run")):
            result = bot.read_recent_messages(1)
        self.assertEqual(result[0]["sender"], "成员 A")
        self.assertEqual(result[0]["content"], "Hello")

    def test_old_text_and_unrelated_file_type_do_not_verify(self):
        bot = sender.WeChatAssistant()
        bot.db = FakeDB(messages=[{"sort_seq": 1, "sender_id": 2,
                                   "create_time": int(time.time()) - 100,
                                   "type": "文本", "content": "same"}])
        self.assertFalse(bot._verify_new({1}, time.time() - 1,
                                          lambda row: row.get("content") == "same", timeout=0.01))
        bot.db = FakeDB(messages=[{"sort_seq": 2, "sender_id": 2,
                                   "create_time": int(time.time()),
                                   "type": "文本", "content": "unrelated"}])
        self.assertFalse(bot._verify_new({1}, time.time() - 1,
                                          lambda row: row.get("type") == "文件/链接/卡片", timeout=0.01))

    def test_cli_rejects_missing_file_before_connect(self):
        with patch.object(sender.WeChatAssistant, "connect", side_effect=AssertionError("UI must not run")):
            with redirect_stderr(io.StringIO()):
                self.assertEqual(sender.main(["-f", r"Z:\missing-wechat-test.pdf"]), 1)

    def test_batch_preserves_order_and_natural_directory_sort(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            for name in ("10.txt", "2.txt", "1.txt"):
                Path(folder, name).write_text("x", encoding="utf-8")
            args = sender.argparse.Namespace(batch_json=None, text=None, files=None,
                                             dir=folder, filter="*.txt", file_text=None)
            actual = [Path(path).name for _, path in sender._actions(args)]
            self.assertEqual(actual, ["1.txt", "2.txt", "10.txt"])

    def test_context_manager_alias_and_failed_item_exit_status(self):
        self.assertTrue(hasattr(sender.WeChatFileHelperSender, "__enter__"))

        class Bot:
            def __init__(self, *args, **kwargs):
                self.display_name = "文件传输助手"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def send_text(self, *args, **kwargs):
                return False

            def close(self):
                pass

        with patch.object(sender, "WeChatAssistant", Bot):
            with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()):
                code = sender.main(["-t", "test"])
        self.assertEqual(code, 1)
        self.assertNotIn("1 项已提交", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()

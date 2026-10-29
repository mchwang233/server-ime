"""Behavioral checks against the real bundled backend (no conversion mocks)."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from server_ime_engine import Engine, EngineError
from server_ime_engine.platform_adapter import PlatformSession
from server_ime_engine.protocol import Service


class ConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = Engine()

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def setUp(self):
        self.s = self.engine.create_session()

    def tearDown(self):
        self.s.close()

    def error(self, code, call, *args, **kwargs):
        with self.assertRaises(EngineError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def choose_text(self, text):
        total = self.s.state()["candidates"]["total"]
        for page in range((total + self.s.config.page_size - 1) // self.s.config.page_size):
            for candidate in self.s.candidates(page)["items"]:
                if candidate["text"] == text:
                    return self.s.select(candidate["id"])
        self.fail("candidate not found: " + text)

    def test_whole_sentence_and_exactly_once_commit(self):
        state = self.s.input("woaibeijingtiananmen")
        self.assertEqual("我爱北京天安门", state["candidates"]["items"][0]["text"])
        result = self.s.commit()
        self.assertEqual("我爱北京天安门", result["commits"][0]["text"])
        self.assertEqual([], self.s.state()["commits"])
        self.assertEqual([], self.s.commit()["commits"])
        self.assertFalse(result["preedit"]["visible"])

    def assertWorld(self):
        # libime's model ranks 你好时节 just ahead of 你好世界 (libpinyin had them the
        # other way round); the preview is the first candidate, 你好世界 one of the first two.
        state = self.s.state()
        texts = [item["text"] for item in state["candidates"]["items"][:2]]
        self.assertIn("你好世界", texts)
        self.assertEqual(texts[0], state["preedit"]["preview"])

    def test_continuous_edit_insert_delete_and_cancel(self):
        for key in "nihaoshijie":
            self.s.key(key)
        self.assertWorld()
        self.s.key("Home")
        self.s.input("wo")
        self.assertEqual("wonihaoshijie", self.s.state()["input"]["text"])
        self.s.key("BackSpace")
        self.s.key("BackSpace")
        self.assertEqual("nihaoshijie", self.s.state()["input"]["text"])
        self.s.key("Delete")
        self.assertEqual("ihaoshijie", self.s.state()["input"]["text"])
        self.s.edit(0, 1, "ni")
        self.assertWorld()
        state = self.s.key("Escape")
        self.assertFalse(state["preedit"]["visible"])
        self.assertEqual([], state["commits"])
        self.assertEqual(0, state["candidates"]["total"])

    def test_partial_selection_composes_without_duplicate_prefix(self):
        self.s.set_input("nihaoshijie")
        chosen = self.choose_text("你好")
        self.assertEqual([], chosen["commits"])
        self.assertEqual("你好shijie", chosen["preedit"]["text"])
        self.assertEqual("世界", chosen["candidates"]["items"][0]["text"])
        result = self.s.select(chosen["candidates"]["items"][0]["id"])
        self.assertEqual("你好世界", result["commits"][0]["text"])

    def test_nonfirst_candidate_and_partial_edit(self):
        self.s.set_input("nihaoshijie")
        result = self.choose_text("你好时节")
        self.assertEqual("你好时节", result["commits"][0]["text"])
        self.s.set_input("nihaoshijie")
        self.choose_text("你好")
        state = self.s.edit(5, 11, "zhongguo")
        self.assertEqual("nihaozhongguo", state["preedit"]["text"])
        self.assertEqual(0, state["input"]["selected_length"])

    def test_ids_reject_stale_cross_session_and_recreated_session(self):
        state = self.s.input("nihao")
        cid = state["candidates"]["items"][0]["id"]
        self.s.key("BackSpace")
        self.error("stale_candidate", self.s.select, cid)
        other = self.engine.create_session(session_id="reuse")
        other.input("nihao")
        self.error("stale_candidate", other.select, cid)
        old = other.state()["candidates"]["items"][0]["id"]
        other.close()
        other = self.engine.create_session(session_id="reuse")
        other.input("nihao")
        self.error("stale_candidate", other.select, old)
        other.close()

    def test_independent_sessions_config_and_threads(self):
        other = self.engine.create_session({"incomplete": False, "page_size": 9})
        self.s.input("n")
        other.input("n")
        self.assertGreater(self.s.state()["candidates"]["total"], 0)
        self.assertEqual(0, other.state()["candidates"]["total"])
        other.close()
        cases = [("nihao", "你好"), ("shurufa", "输入法"), ("zhongwen", "中文"), ("fuwuqi", "服务器")]
        def run(case):
            raw, expected = case
            with self.engine.create_session() as session:
                for _ in range(30):
                    state = session.set_input(raw)
                    self.assertEqual(expected, state["candidates"]["items"][0]["text"])
                    self.assertEqual(expected, session.commit()["commits"][0]["text"])
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(run, cases))

    def test_pages_digit_selection_and_result_snapshots(self):
        snapshot = self.s.input("ni")
        second = self.s.candidates(1)
        self.s.key("Page_Down")
        self.assertEqual(second, self.s.state()["candidates"])
        selected = self.s.key("2")
        self.assertEqual(second["items"][1]["text"], selected["commits"][0]["text"])
        self.assertEqual("ni", snapshot["input"]["text"])
        self.error("invalid_argument", self.s.candidates, -1)

    def test_invalid_input_is_atomic_and_unparsed_suffix_is_preserved(self):
        state = self.s.set_input("nihao")
        for bad in ["ni3hao3", "\x00", "hello world", "中文", 123, "a" * 129]:
            with self.assertRaises(EngineError):
                self.s.input(bad)
            self.assertEqual(state, self.s.state())
        self.s.set_input("nihaovv")
        self.error("incomplete_input", self.s.commit)
        self.choose_text("你好")
        self.assertEqual("你好vv", self.s.state()["preedit"]["text"])
        self.assertEqual("你好vv", self.s.commit("literal")["commits"][0]["text"])

    def test_config_errors_do_not_modify_state(self):
        before = self.s.set_input("nihao")
        for patch in [{"schema": "unsupported_schema"}, {"learning": True}, {"page_size": True},
                      {"page_size": 10}, {"fuzzy": True}, {"incomplete": "yes"}]:
            with self.assertRaises(EngineError):
                self.s.configure(patch)
            self.assertEqual(before, self.s.state())
        self.assertEqual(9, self.s.configure({"page_size": 9})["config"]["page_size"])

    def test_normalization_delimiters_and_long_input(self):
        self.assertEqual("lüse".replace("ü", "v"), self.s.set_input("LÜSE")["input"]["text"])
        self.assertEqual("西安", self.s.set_input("xi'an")["candidates"]["items"][0]["text"])
        for text in ["'", "''", "vv", "a''b", "nihao'", "a" * 128]:
            state = self.s.set_input(text)
            self.assertEqual(text, state["input"]["text"])
            if state["candidates"]["total"]:
                self.s.select(state["candidates"]["items"][0]["id"])
            self.s.reset()

    def test_seeded_edit_sequences(self):
        rng = random.Random(20261028)
        expected, cursor = "", 0
        for _ in range(500):
            action = rng.choice(["insert", "insert", "back", "delete", "move", "reset"])
            if action == "insert":
                text = rng.choice(["ni", "hao", "shi", "jie", "'", "v"])
                expected = expected[:cursor] + text + expected[cursor:]
                cursor += len(text)
                state = self.s.input(text)
            elif action == "back":
                start = max(0, cursor - 1)
                expected = expected[:start] + expected[cursor:]
                cursor = start
                state = self.s.key("BackSpace")
            elif action == "delete":
                expected = expected[:cursor] + expected[cursor + 1:]
                state = self.s.key("Delete")
            elif action == "move":
                cursor = rng.randrange(len(expected) + 1)
                state = self.s.set_input(expected, cursor)
            else:
                expected, cursor = "", 0
                state = self.s.reset()
            self.assertEqual((expected, cursor), (state["input"]["text"], state["input"]["cursor"]))
            self.assertEqual([], state["commits"])

    def test_close_releases_session_and_is_idempotent(self):
        sid = self.s.session_id
        self.s.close()
        self.s.close()
        self.error("closed", self.s.state)
        self.error("unknown_session", self.engine.session, sid)


class BoundaryTests(unittest.TestCase):
    def test_platform_port_conversion_selection_and_partial_commit(self):
        session = PlatformSession()
        try:
            session.set_context(type("Context", (), {"private": True})())
            conversion = session.convert("nihaoshijie", 11)
            chosen = next(c for c in conversion.candidates if c.text == "你好")
            selected = session.select(chosen.id)
            self.assertEqual(("你好", "shijie"), (selected.commit, selected.remaining))
            conversion = session.convert(selected.remaining, selected.cursor)
            self.assertEqual("世界", session.select(conversion.candidates[0].id).commit)
            session.reset()
            self.assertEqual(200, len(session.convert("xian", 4).candidates))
        finally:
            session.close()

    def test_jsonl_client_and_bad_messages_keep_service_alive(self):
        requests = [b'{bad json}\n', b'[]\n', b'\xff\n',
                    json.dumps({"api_version": "1.0", "id": "\ud800", "op": "capabilities"}).encode()+b'\n',
                    b'x' * 65538 + b'\n',
                    b'{"api_version":"1.0","op":"create","args":{"session_id":"pipe"}}\n',
                    b'{"api_version":"1.0","op":"input","session_id":"pipe","args":{"text":"nihao"}}\n',
                    b'{"api_version":"1.0","op":"commit","session_id":"pipe"}\n']
        result = subprocess.run([str(ROOT / "bin/server-ime-engine")], input=b''.join(requests),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
        replies = [json.loads(x) for x in result.stdout.splitlines()]
        self.assertEqual(len(requests), len(replies))
        self.assertFalse(replies[0]["ok"])
        self.assertTrue(replies[3]["ok"])
        self.assertFalse(replies[4]["ok"])
        self.assertEqual("你好", replies[-1]["result"]["commits"][0]["text"])

    def test_protocol_errors_are_structured(self):
        service = Service()
        try:
            for request, code in [({}, "unsupported_version"),
                                  ({"api_version": "1.0", "op": "unknown"}, "unknown_operation"),
                                  ({"api_version": "1.0", "op": "create", "args": {"extra": 1}}, "invalid_argument"),
                                  ({"api_version": "1.0", "op": "state", "session_id": "absent"}, "unknown_session")]:
                self.assertEqual(code, service.handle(request)["error"]["code"])
        finally:
            service.close()

    def test_missing_dependency_reports_path(self):
        with self.assertRaises(EngineError) as result:
            Engine(data_dir=ROOT / "checks/does-not-exist")
        self.assertEqual("dependency_missing", result.exception.code)
        self.assertIn("table.conf", str(result.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)

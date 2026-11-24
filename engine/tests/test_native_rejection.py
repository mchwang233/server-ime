"""Personal entries libpinyin refuses must not take the engine down.

Regression: a learned 这些侧 read as zhei'xie'ce (libime reads 这 as zhei, the
syllable list accepts zhei, libpinyin's table only has zhe) made every engine
start fail with "native dictionary rejected a validated entry".
"""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from server_ime_engine import Engine, EngineError
from server_ime_engine import lexicon_adapter as lexicon

BAD = ("这些侧", "zhei'xie'ce")


class NativeRejection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ime-native-reject-")
        self.path = Path(self.tmp.name) / "user"
        with Engine(user_data_dir=self.path) as e:
            e.create_session({"learning": True}).close()
        store = lexicon.UserStore(self.path, base_manifest=None)
        store.record_commit(*BAD, event_id="bad", source="engine.candidate")
        store.record_commit("项目", "xiang'mu", event_id="good", source="engine.candidate")

    def tearDown(self):
        self.tmp.cleanup()

    def test_store_with_refused_entry_still_starts_and_converts(self):
        with Engine(user_data_dir=self.path) as e:
            s = e.create_session({"learning": True})
            status = e.learning_status()
            self.assertEqual(2, status["entries"])
            self.assertEqual(1, status["native_rejected"])
            state = s.set_input("nihao")
            self.assertEqual("你好", state["candidates"]["items"][0]["text"])

    def test_learning_skips_readings_libpinyin_lacks(self):
        with Engine(user_data_dir=self.path) as e:
            self.assertFalse(e._native_accepts(*BAD))
            self.assertTrue(e._native_accepts("这些", "zhe'xie"))
            s = e.create_session({"learning": True})
            s.set_input("zheixiece")
            event = s._finish("这些侧", "candidate", reading=BAD[1])["commits"][0]
            self.assertEqual({"recorded": False, "reason": "reading_not_in_native_dictionary"},
                             event["learning"])

    def test_refused_custom_phrase_is_still_rejected_up_front(self):
        with Engine(user_data_dir=self.path) as e:
            with self.assertRaises(EngineError):
                e.add_phrase("这些侧", "zhei'xie'ce")


if __name__ == "__main__":
    unittest.main()

"""Next-word prediction (employee_id: engine).

Run: python3 -B engine/tests/test_prediction.py
The 0.1.2 prediction kept suggestions as session state and was withdrawn. Its
replacement is stateless: Engine.predict(history) asks libime's model for the
words after the committed texts, and the platform controller keeps the history
(product_controller.py). Sessions still hold no prediction state, and the JSON
contract still has no prediction operations.
SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from server_ime_engine import Engine
from server_ime_engine.platform_adapter import PlatformSession


RETIRED_METHODS = ("get_predictions", "select_prediction", "clear_predictions")


class PredictionWithdrawalTests(unittest.TestCase):
    def assert_no_prediction_state(self, obj):
        self.assertFalse([name for name in vars(obj) if "predict" in name])
        for name in RETIRED_METHODS:
            self.assertFalse(hasattr(obj, name), name)

    def test_next_words_follow_committed_text(self):
        with Engine() as engine:
            self.assertIn("的", engine.predict(["我们"]))
            self.assertIn("预报", engine.predict(["今天", "天气"]))
            # A sentence is followed by what follows its last known word.
            self.assertTrue(engine.predict(["明天上午开会"]))
            words = engine.predict(["谢谢"], 5)
            self.assertLessEqual(len(words), 5)
            self.assertFalse(any(set(word) & set("，。！？、") for word in words))
            self.assertEqual([], engine.predict([]))
            self.assertEqual([], engine.predict("我们"))
        port = PlatformSession()
        try:
            self.assertTrue(port.predict(["我们"]))
            port.set_context(type("Context", (), {"private": True, "purpose": 8, "hints": 0})())
            self.assertEqual([], port.predict(["我们"]))
        finally:
            port.close()

    def test_python_session_and_platform_no_longer_retain_predictions(self):
        with Engine() as engine:
            caps = engine.capabilities()
            self.assertEqual("0.4.0", caps["component_version"])
            self.assertNotIn("prediction", caps)
            self.assertNotIn("prediction", caps["features"])
            for name in ("guess_predicted_candidates", "prediction_context", "predictions"):
                self.assertFalse(hasattr(engine._native, name), name)
            with engine.create_session() as session:
                session.set_input("zhongguo")
                self.assertEqual(["中国"], [event["text"] for event in session.commit()["commits"]])
                self.assertEqual([], session.state()["commits"])
                self.assertEqual([], session.candidates()["items"])
                self.assert_no_prediction_state(session)
                session.set_context(private=True)
                session.set_input("beijing")
                event = session.commit()["commits"][0]
                self.assertEqual("北京", event["text"])
                self.assertFalse(event["learning_eligible"])
                self.assertFalse(event["learning"]["recorded"])
                self.assert_no_prediction_state(session)
            self.assert_no_prediction_state(engine)
        port = PlatformSession()
        try:
            conversion = port.convert("zhongguo", 8)
            self.assertEqual("中国", port.select(conversion.candidates[0].id).commit)
            self.assertEqual((), port.convert("", 0).candidates)
            self.assert_no_prediction_state(port)
            self.assert_no_prediction_state(port._session)
        finally:
            port.close()

    def test_json_contract_has_no_prediction_operations_or_replayed_commits(self):
        requests = [
            {"op": "capabilities"},
            {"op": "create", "args": {"session_id": "withdrawal"}},
            {"op": "set_input", "args": {"text": "zhongguo"}},
            {"op": "commit"},
            {"op": "state"},
            {"op": "get_predictions"},
            {"op": "select_prediction", "args": {"candidate_id": "old:prediction:0:0"}},
            {"op": "clear_predictions"},
            {"op": "state"},
        ]
        for request in requests:
            request.update(api_version="1.0", session_id="withdrawal")
        child = subprocess.run(
            [str(ROOT / "bin/server-ime-engine")],
            input="".join(json.dumps(request) + "\n" for request in requests),
            text=True, capture_output=True, timeout=15,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(0, child.returncode, child.stderr)
        responses = [json.loads(line) for line in child.stdout.splitlines()]
        self.assertEqual(len(requests), len(responses))
        self.assertTrue(all(responses[index]["ok"] for index in (0, 1, 2, 3, 4, 8)))
        self.assertNotIn("prediction", responses[0]["result"]["features"])
        self.assertNotIn("prediction", responses[0]["result"])
        self.assertEqual("中国", responses[3]["result"]["commits"][0]["text"])
        for index in (4, 8):
            self.assertEqual([], responses[index]["result"]["commits"])
            self.assertEqual([], responses[index]["result"]["candidates"]["items"])
        for index in (5, 6, 7):
            self.assertFalse(responses[index]["ok"])
            self.assertEqual("unknown_operation", responses[index]["error"]["code"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

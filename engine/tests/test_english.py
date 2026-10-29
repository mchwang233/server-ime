"""English words typed in Chinese mode (composition.py, english.py).

Run: python3 -B engine/tests/test_english.py
SPDX-License-Identifier: GPL-3.0-or-later
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from server_ime_engine import english
from server_ime_engine.composition import Composer
from server_ime_engine.platform_adapter import PlatformSession


class EnglishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = PlatformSession(config={"page_size": 5, "learning": False})

    @classmethod
    def tearDownClass(cls):
        cls.session.close()

    def texts(self, raw):
        self.session.reset()
        return [c.text for c in self.session.convert(raw, len(raw)).candidates]

    def test_word_that_cannot_be_pinyin_comes_first(self):
        self.assertEqual("hello", self.texts("hello")[0])
        self.assertEqual("GitHub", self.texts("github")[0])
        self.assertEqual("the", self.texts("the")[1])

    def test_pinyin_keeps_its_chinese_first(self):
        texts = self.texts("women")
        self.assertEqual("我们", texts[0])
        self.assertEqual("women", texts[4])
        self.assertEqual("你好", self.texts("nihao")[0])
        # A single syllable spelt as an English word stays Chinese only.
        self.assertNotIn("Wang", self.texts("wang")[:5])
        # Mid-syllable input is not corrected into English ("wansh" is not "wash").
        self.assertNotIn("wash", self.texts("wansh")[:5])

    def test_typo_of_a_common_word(self):
        self.assertIn("Python", self.texts("pyhton")[:3])
        self.assertIn("receive", self.texts("recieve")[:3])
        self.assertEqual(["receive", "relieve"], english.corrections("recieve"))
        self.assertEqual("你好", self.texts("nihoa")[0])

    def test_words_inside_a_sentence(self):
        self.assertEqual("我用Docker部署项目", self.texts("woyongdockerbushuxiangmu")[0])
        self.assertEqual("将JSON转换成XML", self.texts("jiangjsonzhuanhuanchengxml")[0])
        self.assertIsNone(Composer.english_pieces("zhongguoren"))

    def test_selecting_the_word_commits_it(self):
        self.session.reset()
        conversion = self.session.convert("github", 6)
        self.assertEqual("GitHub", self.session.select(conversion.candidates[0].id).commit)


if __name__ == "__main__":
    unittest.main(verbosity=2)

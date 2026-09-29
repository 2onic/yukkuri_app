"""
Unit tests for G2P and phonetic mapping
"""

import unittest
from yukkuri.g2p import text_to_yukkuri_polyglot, PolyglotG2P

class TestPolyglotG2P(unittest.TestCase):
    def test_chinese_mapping(self):
        result = text_to_yukkuri_polyglot("你好")
        self.assertEqual(result, "にー/はお")

    def test_yukkuri_special_case(self):
        result = text_to_yukkuri_polyglot("油库里")
        self.assertEqual(result, "ゆっくり")

    def test_english_high_freq(self):
        result = text_to_yukkuri_polyglot("hello world")
        self.assertEqual(result, "へろー/わーるど")

    def test_english_acronym(self):
        self.assertEqual(text_to_yukkuri_polyglot("CPU"), "しーぴーゆー")
        self.assertEqual(text_to_yukkuri_polyglot("KFC"), "けー/えふ/しー")

    def test_digits_chinese(self):
        result = text_to_yukkuri_polyglot("123", current_lang="zh")
        self.assertEqual(result, "いー/あー/さん")

    def test_digits_japanese(self):
        result = text_to_yukkuri_polyglot("123", current_lang="ja")
        self.assertEqual(result, "イチ/ニ/サン")

    def test_digits_english(self):
        result = text_to_yukkuri_polyglot("1234", current_lang="en")
        self.assertEqual(result, "わん/つー/すりー/ふぉー")

    def test_custom_rule(self):
        g2p = PolyglotG2P()
        g2p.add_custom_rule("bilibili", "びりびり")
        result = g2p.convert("bilibili")
        self.assertEqual(result, "びりびり")

if __name__ == "__main__":
    unittest.main()

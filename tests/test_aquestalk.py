"""
Unit tests for AquesTalk multi-voice support and library resolution
"""

import unittest
from yukkuri.config import AppConfig, AQUESTALK_VOICES
from yukkuri.tts.aquestalk1 import AquesTalk1Engine
from yukkuri.model_downloader import check_model_status

class TestAquesTalkMultiVoice(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig()

    def test_voice_catalog(self):
        self.assertIn("f1", AQUESTALK_VOICES)
        self.assertIn("f2", AQUESTALK_VOICES)
        self.assertIn("m1", AQUESTALK_VOICES)

    def test_library_resolution(self):
        # f1 and f2 should resolve if present
        f1_path = self.config.find_aquestalk_library("f1")
        if f1_path:
            self.assertTrue(f1_path.endswith(".so"))

        f2_path = self.config.find_aquestalk_library("f2")
        if f2_path:
            self.assertTrue(f2_path.endswith(".so"))

    def test_model_status_includes_aquestalk(self):
        status = check_model_status()
        self.assertIn("aquestalk", status)
        self.assertIn("aquestalk_voices", status)

    def test_engine_dynamic_voice_switch(self):
        avail = self.config.get_available_voices()
        if len(avail) >= 2:
            v_keys = list(avail.keys())
            v1, v2 = v_keys[0], v_keys[1]

            engine = AquesTalk1Engine(voice=v1, voice_resolver=self.config.find_aquestalk_library)
            self.assertEqual(engine.current_voice, v1)
            wav1 = engine.synthesize("テスト")
            self.assertIsNotNone(wav1)

            switched = engine.set_voice(v2)
            self.assertTrue(switched)
            self.assertEqual(engine.current_voice, v2)
            wav2 = engine.synthesize("テスト")
            self.assertIsNotNone(wav2)

            self.assertNotEqual(wav1, wav2)

    def test_dev_key_options_passed(self):
        """测试 AquesTalk1Engine 能够正确接收 dev_key 与 usr_key 配置"""
        import io
        import contextlib
        with contextlib.redirect_stderr(io.StringIO()):
            engine = AquesTalk1Engine(
                voice="f1",
                voice_resolver=self.config.find_aquestalk_library,
                dev_key="TEST_DEV_KEY",
                usr_key="TEST_USR_KEY",
            )
        self.assertEqual(engine.dev_key, "TEST_DEV_KEY")
        self.assertEqual(engine.usr_key, "TEST_USR_KEY")

if __name__ == "__main__":
    unittest.main()

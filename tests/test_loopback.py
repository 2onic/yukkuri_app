"""
Unit tests for LoopbackManager and loopback configuration
"""

import unittest
from yukkuri.config import AppConfig
from yukkuri.audio.loopback import LoopbackManager
from yukkuri.pipeline import YukkuriPipeline
from yukkuri.asr.base import BaseASREngine
from yukkuri.tts.base import BaseTTSEngine

class DummyASR(BaseASREngine):
    def decode(self, samples, sample_rate=16000):
        return ""
    def close(self):
        pass

class DummyTTS(BaseTTSEngine):
    def synthesize(self, koe, speed=100):
        return None
    def close(self):
        pass

class TestLoopback(unittest.TestCase):
    def test_config_loopback_field(self):
        cfg = AppConfig(enable_loopback=True)
        self.assertTrue(cfg.enable_loopback)
        self.assertEqual(cfg.source_name, "yukkuri_source")

    def test_loopback_manager_instance(self):
        lm = LoopbackManager(source_name="yukkuri_source")
        self.assertFalse(lm.is_running())

    def test_pipeline_loopback_toggle(self):
        cfg = AppConfig(enable_loopback=False)
        pipeline = YukkuriPipeline(config=cfg, asr=DummyASR(), tts=DummyTTS())
        self.assertFalse(pipeline.config.enable_loopback)

        pipeline.set_loopback(True)
        self.assertTrue(pipeline.config.enable_loopback)

        pipeline.set_loopback(False)
        self.assertFalse(pipeline.config.enable_loopback)

if __name__ == "__main__":
    unittest.main()

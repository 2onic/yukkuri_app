"""
Unit tests for YukkuriPipeline end-to-end orchestration
"""

import unittest
import queue
import numpy as np
from unittest.mock import MagicMock

from yukkuri.config import AppConfig
from yukkuri.asr.base import BaseASREngine
from yukkuri.tts.base import BaseTTSEngine
from yukkuri.pipeline import YukkuriPipeline


class MockASREngine(BaseASREngine):
    def decode(self, samples: np.ndarray, sample_rate: int = 16000) -> str:
        return "你好"


class MockTTSEngine(BaseTTSEngine):
    def synthesize(self, koe: str, speed: int = 100):
        return b"RIFFfake_wav_data"


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig()
        self.mock_asr = MockASREngine()
        self.mock_tts = MockTTSEngine()

    def test_process_segment(self):
        callback_results = []

        def on_segment(text, koe, stats):
            callback_results.append((text, koe, stats))

        pipeline = YukkuriPipeline(
            config=self.config,
            asr=self.mock_asr,
            tts=self.mock_tts,
            on_segment_processed=on_segment,
        )
        pipeline.player = MagicMock()

        # 传入有效长度样本 (>= vad_min_sample_duration * 16000)
        samples = np.zeros(16000, dtype=np.float32)
        pipeline.process_segment(samples)

        self.assertEqual(len(callback_results), 1)
        text, koe, stats = callback_results[0]
        self.assertEqual(text, "你好")
        self.assertEqual(koe, "にー/はお")
        self.assertFalse(stats["manual"])
        pipeline.player.play.assert_called_once_with(b"RIFFfake_wav_data")

    def test_speak_text_manual(self):
        callback_results = []

        def on_segment(text, koe, stats):
            callback_results.append((text, koe, stats))

        pipeline = YukkuriPipeline(
            config=self.config,
            asr=self.mock_asr,
            tts=self.mock_tts,
            on_segment_processed=on_segment,
        )
        pipeline.player = MagicMock()

        pipeline.speak_text("女人")
        self.assertEqual(len(callback_results), 1)
        text, koe, stats = callback_results[0]
        self.assertEqual(text, "女人")
        self.assertEqual(koe, "にゅー/れん")
        self.assertTrue(stats["manual"])
        pipeline.player.play.assert_called_once_with(b"RIFFfake_wav_data")

    def test_pipeline_stop_and_cleanup(self):
        mock_mic = MagicMock()
        pipeline = YukkuriPipeline(
            config=self.config,
            asr=self.mock_asr,
            tts=self.mock_tts,
            mic_manager=mock_mic,
        )
        pipeline.player = MagicMock()
        pipeline.mic_stream = MagicMock()

        pipeline.stop()
        self.assertTrue(pipeline.stop_event.is_set())
        pipeline.mic_stream.stop.assert_called_once()
        pipeline.player.stop.assert_called_once()
        mock_mic.cleanup.assert_called_once()


if __name__ == "__main__":
    unittest.main()

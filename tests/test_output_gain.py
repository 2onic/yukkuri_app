"""
输出音量增益功能单元测试：
- apply_wav_gain 增益放大、衰减、削顶防溢出与边界测试
- AudioPlayer / WindowsWASAPIPlayer / LinuxPipeWirePlayer 增益支持与动态 set_gain
- YukkuriPipeline 动态 set_output_gain
- CLI --output-gain 命令行参数解析
"""

import io
import wave
import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from yukkuri.config import AppConfig
from yukkuri.cli import parse_args
from yukkuri.audio.player import apply_wav_gain, AudioPlayer, LinuxPipeWirePlayer, WindowsWASAPIPlayer
from yukkuri.pipeline import YukkuriPipeline
from yukkuri.asr.base import BaseASREngine
from yukkuri.tts.base import BaseTTSEngine


def _create_sine_wav(sample_rate: int = 8000, duration: float = 0.1, amplitude: int = 5000) -> bytes:
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    samples = (amplitude * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


class MockASR(BaseASREngine):
    def decode(self, samples: np.ndarray, sample_rate: int = 16000) -> str:
        return "增益测试"


class MockTTS(BaseTTSEngine):
    def synthesize(self, koe: str, speed: int = 100):
        return _create_sine_wav(amplitude=1000)


class TestOutputGain(unittest.TestCase):
    def test_apply_wav_gain_identity(self):
        """增益为 1.0 时原样返回零开销"""
        raw_wav = _create_sine_wav(amplitude=3000)
        out = apply_wav_gain(raw_wav, 1.0)
        self.assertIs(out, raw_wav)

        empty_out = apply_wav_gain(b"", 2.0)
        self.assertEqual(empty_out, b"")

    def test_apply_wav_gain_boost_and_attenuate(self):
        """测试放大与衰减倍数计算精准"""
        raw_wav = _create_sine_wav(amplitude=2000)

        # 2.0x 放大
        boosted = apply_wav_gain(raw_wav, 2.0)
        with wave.open(io.BytesIO(boosted), "rb") as wf:
            boosted_samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        with wave.open(io.BytesIO(raw_wav), "rb") as wf:
            orig_samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)

        np.testing.assert_allclose(boosted_samples, orig_samples * 2, atol=2)

        # 0.5x 衰减
        attenuated = apply_wav_gain(raw_wav, 0.5)
        with wave.open(io.BytesIO(attenuated), "rb") as wf:
            att_samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        np.testing.assert_allclose(att_samples, (orig_samples * 0.5).astype(np.int16), atol=2)

    def test_apply_wav_gain_clipping_no_wrap(self):
        """测试过大增益时在 int16 边界 (-32768, 32767) 饱和截断，防止环绕溢出"""
        raw_wav = _create_sine_wav(amplitude=20000)
        boosted = apply_wav_gain(raw_wav, 5.0)

        with wave.open(io.BytesIO(boosted), "rb") as wf:
            samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)

        self.assertLessEqual(np.max(samples), 32767)
        self.assertGreaterEqual(np.min(samples), -32768)
        self.assertEqual(np.max(samples), 32767)
        self.assertEqual(np.min(samples), -32768)

    def test_apply_wav_gain_zero_silence(self):
        """测试增益为 0.0 时输出完全静音"""
        raw_wav = _create_sine_wav(amplitude=5000)
        silent = apply_wav_gain(raw_wav, 0.0)
        with wave.open(io.BytesIO(silent), "rb") as wf:
            samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        self.assertEqual(np.max(np.abs(samples)), 0)

    def test_player_gain_and_dynamic_tuning(self):
        """测试 AudioPlayer 实例化的初始增益与动态 set_gain"""
        player = AudioPlayer(gain=1.5)
        self.assertEqual(player.impl.gain, 1.5)

        player.set_gain(2.2)
        self.assertEqual(player.impl.gain, 2.2)

        # 验证 play 投递到底层队列时应用了增益
        raw_wav = _create_sine_wav(amplitude=1000)
        player.play(raw_wav)

        queued_item = player.impl.queue.get(timeout=1.0)
        queued_wav, _ = queued_item
        with wave.open(io.BytesIO(queued_wav), "rb") as wf:
            samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)

        # 1000 * 2.2 = 2200
        self.assertAlmostEqual(float(np.max(samples)), 2200, delta=20)
        player.stop()

    def test_pipeline_set_output_gain(self):
        """测试 Pipeline 动态调节输出增益接口"""
        config = AppConfig(output_gain=1.2)
        pipeline = YukkuriPipeline(
            config=config,
            asr=MockASR(),
            tts=MockTTS(),
        )
        self.assertEqual(pipeline.config.output_gain, 1.2)
        self.assertEqual(pipeline.player.impl.gain, 1.2)

        pipeline.set_output_gain(2.5)
        self.assertEqual(pipeline.config.output_gain, 2.5)
        self.assertEqual(pipeline.player.impl.gain, 2.5)
        pipeline.stop()

    def test_cli_output_gain_parsing(self):
        """测试 CLI 参数 --output-gain 解析"""
        with patch("sys.argv", ["yukkuri", "--output-gain", "1.8"]):
            args = parse_args()
            self.assertEqual(args.output_gain, 1.8)


if __name__ == "__main__":
    unittest.main()

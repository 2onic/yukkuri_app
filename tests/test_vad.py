"""
Silero-VAD 语音活动检测、防长语音缓冲截断保护与用户设置单元测试
"""

import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from yukkuri.config import AppConfig
from yukkuri.cli import parse_args
from yukkuri.audio.vad import SileroVAD
from yukkuri.pipeline import YukkuriPipeline

class TestVAD(unittest.TestCase):
    def test_vad_config_and_cli_arguments(self):
        """测试 AppConfig 默认截断时间与 CLI 参数解析"""
        cfg = AppConfig()
        self.assertEqual(cfg.vad_max_speech, 6.0)
        self.assertTrue(cfg.vad_enable_max_speech)
        self.assertEqual(cfg.get_effective_max_speech_duration(), 6.0)

        # 禁用截断测试
        cfg.vad_enable_max_speech = False
        self.assertEqual(cfg.get_effective_max_speech_duration(), 0.0)

        cfg_zero = AppConfig(vad_max_speech=0.0)
        self.assertEqual(cfg_zero.get_effective_max_speech_duration(), 0.0)

        with patch("sys.argv", ["yukkuri", "--max-speech-duration", "8.5"]):
            args = parse_args()
            self.assertEqual(args.max_speech_duration, 8.5)
            self.assertFalse(args.no_max_speech)

        with patch("sys.argv", ["yukkuri", "--no-max-speech"]):
            args = parse_args()
            self.assertTrue(args.no_max_speech)

        with patch("sys.argv", ["yukkuri", "--mic-gain", "1.8"]):
            args = parse_args()
            self.assertEqual(args.mic_gain, 1.8)

    @patch("yukkuri.audio.vad.sherpa_onnx")
    @patch("os.path.exists", return_value=True)
    def test_silerovad_init_and_parameter_updates(self, mock_exists, mock_sherpa):
        """测试 SileroVAD 初始化配置以及运行时动态调整参数"""
        mock_vad_config = MagicMock()
        mock_sherpa.VadModelConfig.return_value = mock_vad_config
        mock_detector = MagicMock()
        mock_sherpa.VoiceActivityDetector.return_value = mock_detector

        vad = SileroVAD(
            vad_model_path="dummy.onnx",
            sample_rate=16000,
            min_silence_duration=0.35,
            min_speech_duration=0.15,
            max_speech_duration=5.0,
            threshold=0.5
        )

        self.assertEqual(mock_vad_config.silero_vad.max_speech_duration, 5.0)
        self.assertEqual(vad.max_speech_duration, 5.0)

        # 动态更新截断时间与停顿时长
        vad.set_max_speech_duration(8.0)
        self.assertEqual(vad.max_speech_duration, 8.0)
        self.assertEqual(mock_detector.config.silero_vad.max_speech_duration, 8.0)

        vad.set_min_silence_duration(0.5)
        self.assertEqual(vad.min_silence_duration, 0.5)
        self.assertEqual(mock_detector.config.silero_vad.min_silence_duration, 0.5)

        # 状态检测与重置调用
        mock_detector.is_speech_detected.return_value = True
        self.assertTrue(vad.is_speech_detected())
        vad.reset()
        mock_detector.reset.assert_called_once()

    @patch("yukkuri.audio.vad.sherpa_onnx")
    @patch("os.path.exists", return_value=True)
    def test_silerovad_forces_flush_when_exceeding_max_duration(self, mock_exists, mock_sherpa):
        """测试当连续说话时长超过用户设置的最大阈值时，自动触发 flush 强制截断防长缓冲"""
        mock_detector = MagicMock()
        mock_sherpa.VoiceActivityDetector.return_value = mock_detector

        vad = SileroVAD(
            vad_model_path="dummy.onnx",
            sample_rate=16000,
            max_speech_duration=2.0
        )

        # 模拟持续检测到人声，且当前段样本数达到 2.1 秒 (33600 samples)
        mock_detector.is_speech_detected.return_value = True
        mock_detector.current_segment.samples = [0.1] * 33600

        # empty() 初次为 False 返回一个截断片段，随后为 True
        mock_seg = MagicMock()
        mock_seg.samples = [0.1] * 33600
        mock_detector.empty.side_effect = [False, True]
        mock_detector.front = mock_seg

        chunk = np.zeros(800, dtype=np.float32)
        segments = vad.accept_waveform(chunk)

        # 必须触发了 flush() 并且产出了截断切片
        mock_detector.flush.assert_called_once()
        self.assertEqual(len(segments), 1)
        self.assertEqual(len(segments[0]), 33600)

    @patch("yukkuri.audio.vad.sherpa_onnx")
    @patch("os.path.exists", return_value=True)
    def test_silerovad_manually_disabled_does_not_flush(self, mock_exists, mock_sherpa):
        """测试手动关闭截断保护时，即使长语音也不会强制调用 flush 截断"""
        mock_detector = MagicMock()
        mock_sherpa.VoiceActivityDetector.return_value = mock_detector

        # max_speech_duration 传 0.0 表示关闭截断
        vad = SileroVAD(
            vad_model_path="dummy.onnx",
            sample_rate=16000,
            max_speech_duration=0.0
        )
        self.assertEqual(vad.max_speech_duration, 0.0)

        # 模拟长语音持续检测到人声
        mock_detector.is_speech_detected.return_value = True
        mock_detector.current_segment.samples = [0.1] * 160000 # 10 秒语音
        mock_detector.empty.return_value = True

        chunk = np.zeros(800, dtype=np.float32)
        segments = vad.accept_waveform(chunk)

        # 绝不能调用 flush()，保持整段语音完整
        mock_detector.flush.assert_not_called()
        self.assertEqual(len(segments), 0)

        # 动态关闭测试：原来开启，后来设为 0
        vad.set_max_speech_duration(5.0)
        self.assertEqual(vad.max_speech_duration, 5.0)
        vad.set_max_speech_duration(0.0)
        self.assertEqual(vad.max_speech_duration, 0.0)
        self.assertEqual(mock_detector.config.silero_vad.max_speech_duration, 99999.0)

    def test_pipeline_is_speech_detected(self):
        """测试 pipeline.is_speech_detected 正确代理 VAD 状态"""
        mock_vad = MagicMock()
        mock_vad.is_speech_detected.return_value = True

        pipeline = YukkuriPipeline(
            config=AppConfig(),
            asr=MagicMock(),
            tts=MagicMock(),
            vad=mock_vad
        )
        self.assertTrue(pipeline.is_speech_detected)

        pipeline.vad = None
        self.assertFalse(pipeline.is_speech_detected)

if __name__ == "__main__":
    unittest.main()

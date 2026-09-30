"""
麦克风采集与硬件自适应重采样单元测试
"""

import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from yukkuri.audio.capture import MicrophoneStream
from yukkuri.gui.devices import get_input_devices, is_virtual_device

class TestAudioCapture(unittest.TestCase):
    def test_resolve_input_parameters_direct_support(self):
        """测试硬件原生支持 16000Hz/1ch 时直接采用目标配置"""
        with patch("sounddevice.check_input_settings", return_value=None):
            stream = MicrophoneStream(sample_rate=16000, channels=1, device=1)
            sr, ch = stream._resolve_input_parameters()
            self.assertEqual(sr, 16000)
            self.assertEqual(ch, 1)

    def test_resolve_input_parameters_fallback(self):
        """测试硬件仅支持 48000Hz/2ch 时自动协商自适应参数"""
        def mock_check(device, samplerate, channels):
            if samplerate == 16000:
                raise RuntimeError("Invalid sample rate")
            if samplerate == 48000 and channels in (1, 2):
                return None
            raise RuntimeError("Unsupported")

        with patch("sounddevice.check_input_settings", side_effect=mock_check):
            with patch("sounddevice.query_devices", return_value={"default_samplerate": 48000, "max_input_channels": 2}):
                stream = MicrophoneStream(sample_rate=16000, channels=1, device=1)
                sr, ch = stream._resolve_input_parameters()
                self.assertEqual(sr, 48000)
                self.assertIn(ch, [1, 2])

    def test_audio_callback_downmix_gain_and_resampling(self):
        """测试音频回调中立体声下混单声道、软件增益与 48kHz->16kHz 重采样"""
        stream = MicrophoneStream(sample_rate=16000, channels=1, gain=2.0)
        stream.actual_sample_rate = 48000
        stream.actual_channels = 2

        # 模拟 48000Hz 立体声 2400 个样本 (50ms)
        fake_stereo = np.ones((2400, 2), dtype=np.float32) * 0.2
        stream._audio_callback(fake_stereo, 2400, None, None)

        self.assertFalse(stream.queue.empty())
        mono_resampled = stream.queue.get_nowait()

        # 采样率从 48000Hz 重采样到 16000Hz，样本数应变为 2400 * (16000/48000) = 800
        self.assertEqual(len(mono_resampled), 800)
        # 增益 2.0x，输入 0.2，输出应接近 0.4
        np.testing.assert_allclose(mono_resampled, 0.4, atol=1e-3)
        # 实时音量 level 应该大于 0
        self.assertGreater(stream.current_level, 0.0)

    def test_dynamic_gain_adjustment(self):
        """测试动态调整软件增益倍数"""
        stream = MicrophoneStream(sample_rate=16000, channels=1, gain=1.0)
        self.assertEqual(stream.gain, 1.0)
        stream.set_gain(2.5)
        self.assertEqual(stream.gain, 2.5)
        # 测试防过低下限保护
        stream.set_gain(0.01)
        self.assertEqual(stream.gain, 0.1)

    def test_pipeline_set_mic_gain(self):
        """测试流水线级动态调节麦克风增益"""
        from yukkuri.config import AppConfig
        from yukkuri.pipeline import YukkuriPipeline
        pipeline = YukkuriPipeline(
            config=AppConfig(mic_gain=1.2),
            asr=MagicMock(),
            tts=MagicMock(),
        )
        self.assertEqual(pipeline.mic_stream.gain, 1.2)
        pipeline.set_mic_gain(1.8)
        self.assertEqual(pipeline.config.mic_gain, 1.8)
        self.assertEqual(pipeline.mic_stream.gain, 1.8)

    def test_is_virtual_device(self):
        """测试虚拟声卡关键字识别"""
        self.assertTrue(is_virtual_device("yukkuri_sink.monitor"))
        self.assertTrue(is_virtual_device("CABLE Output"))
        self.assertTrue(is_virtual_device("Null Output"))
        self.assertFalse(is_virtual_device("Realtek High Definition Audio"))
        self.assertFalse(is_virtual_device("USB Microphone"))

    def test_get_input_devices_tags_virtual(self):
        """测试设备列表中虚拟声卡被添加 [虚拟声卡] 标签，首项为系统默认"""
        mock_devices = [
            {"name": "Built-in Microphone", "max_input_channels": 2},
            {"name": "yukkuri_sink.monitor", "max_input_channels": 2},
            {"name": "CABLE Output", "max_input_channels": 2},
        ]
        with patch("sounddevice.query_devices", return_value=mock_devices):
            devices = get_input_devices()
            self.assertEqual(devices[0], (None, "系统默认 (Default)"))
            self.assertEqual(devices[1], (0, "[0] Built-in Microphone"))
            self.assertIn("[虚拟声卡]", devices[2][1])
            self.assertIn("[虚拟声卡]", devices[3][1])

if __name__ == "__main__":
    unittest.main()

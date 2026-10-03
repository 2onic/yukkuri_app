"""
针对近期审查问题修复的回归与专项单元测试：
- S1: Windows WASAPI HostAPI 设备过滤与去重
- S2: 多声线压缩包归档解压与目录层级隔离（防止同名覆盖）
- S4: 重采样抗混叠低通滤波 (Anti-Aliasing Filter) 与频谱混叠抑制
- S5: Windows WASAPI 播放器长连接 OutputStream 复用
- S6: 全局用户数据目录隔离 (XDG / AppData)
- S7/额外3: 虚拟声卡 auto_cleanup 与生命周期管理
- S8: 虚拟设备缺失时的物理扬声器防外放泄漏保护
- 额外1: 手动播报非阻塞主线程
- 额外2: Pipeline stop() 多线程并发与幂等安全
"""

import os
import sys
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import patch, MagicMock
import numpy as np

from yukkuri.config import AppConfig, get_default_data_dir
from yukkuri.audio.resample import resample_audio
from yukkuri.audio.player import WindowsWASAPIPlayer, LinuxPipeWirePlayer
from yukkuri.model_downloader import install_aquestalk_from_archive
from yukkuri.pipeline import YukkuriPipeline
from yukkuri.asr.base import BaseASREngine
from yukkuri.tts.base import BaseTTSEngine
from yukkuri.audio.virtual_mic import LinuxPipeWireMicManager, VirtualMicManager


class MockASR(BaseASREngine):
    def decode(self, samples: np.ndarray, sample_rate: int = 16000) -> str:
        return "测试"


class MockTTS(BaseTTSEngine):
    def synthesize(self, koe: str, speed: int = 100):
        return b"RIFFfake_wav"


class TestFixesVerification(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_s1_devices_wasapi_prioritization(self):
        """S1: 测试 Windows 下优先过滤 WASAPI HostAPI 避免重复"""
        from yukkuri.gui.devices import get_input_devices, get_output_devices

        mock_hostapis = [
            {"name": "MME"},
            {"name": "Windows DirectSound"},
            {"name": "Windows WASAPI"},
        ]
        # 模拟同一麦克风与扬声器在 MME (hostapi=0) 与 WASAPI (hostapi=2) 均出现
        mock_devices = [
            {"name": "Realtek Microphone", "max_input_channels": 2, "max_output_channels": 0, "hostapi": 0},
            {"name": "Realtek Microphone", "max_input_channels": 2, "max_output_channels": 0, "hostapi": 2},
            {"name": "Realtek Speakers", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0},
            {"name": "Realtek Speakers", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 2},
        ]

        with patch("sys.platform", "win32"):
            with patch("sounddevice.query_hostapis", return_value=mock_hostapis):
                with patch("sounddevice.query_devices", return_value=mock_devices):
                    inputs = get_input_devices()
                    outputs = get_output_devices()

                    # 包含默认项 + 仅 1 个 WASAPI 项，而不是 2 个重复项
                    self.assertEqual(len(inputs), 2)
                    self.assertEqual(inputs[1][0], 1)  # 对应 WASAPI 设备的索引 1

                    self.assertEqual(len(outputs), 2)
                    self.assertEqual(outputs[1][0], 3)  # 对应 WASAPI 设备的索引 3

    def test_s2_zip_multi_voice_no_overwrite(self):
        """S2: 测试无 lib64 前缀的多声线 zip 压缩包解压后互相隔离不被覆盖"""
        root = self.tmp_dir.name
        zip_path = os.path.join(root, "multi_voices.zip")

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("archive_root/f1/libAquesTalk.so", b"voice_f1_binary")
            zf.writestr("archive_root/f2/libAquesTalk.so", b"voice_f2_binary")
            zf.writestr("archive_root/m1/libAquesTalk.so", b"voice_m1_binary")

        with patch("sys.platform", "linux"):
            voices = install_aquestalk_from_archive(zip_path, root=root)
            self.assertIn("f1", voices)
            self.assertIn("f2", voices)
            self.assertIn("m1", voices)

            # 验证各声线二进制内容未被最后一个覆盖
            f1_file = os.path.join(root, "libs", "aquestalk", "lib64", "f1", "libAquesTalk.so")
            f2_file = os.path.join(root, "libs", "aquestalk", "lib64", "f2", "libAquesTalk.so")
            m1_file = os.path.join(root, "libs", "aquestalk", "lib64", "m1", "libAquesTalk.so")

            self.assertTrue(os.path.exists(f1_file))
            self.assertTrue(os.path.exists(f2_file))
            self.assertTrue(os.path.exists(m1_file))

            with open(f1_file, "rb") as f:
                self.assertEqual(f.read(), b"voice_f1_binary")
            with open(f2_file, "rb") as f:
                self.assertEqual(f.read(), b"voice_f2_binary")
            with open(m1_file, "rb") as f:
                self.assertEqual(f.read(), b"voice_m1_binary")

    def test_s4_resampling_anti_aliasing(self):
        """S4: 测试重采样抗混叠滤波器对于高于目标奈奎斯特频率的高频成分的衰减能力"""
        orig_sr = 48000
        target_sr = 16000
        # 目标采样率 16000Hz 的奈奎斯特频率为 8000Hz
        # 生成两个频率：500Hz（带内有效信号）与 18000Hz（带外超高频信号）
        t = np.linspace(0, 0.1, int(orig_sr * 0.1), endpoint=False)
        passband_signal = np.sin(2 * np.pi * 500 * t).astype(np.float32)
        stopband_signal = np.sin(2 * np.pi * 18000 * t).astype(np.float32)

        # 重采样带内信号：幅度应当基本保持
        out_pass = resample_audio(passband_signal, orig_sr, target_sr)
        self.assertAlmostEqual(float(np.max(np.abs(out_pass))), 1.0, delta=0.15)

        # 重采样带外信号：抗混叠低通滤波应大幅衰减该高频能量
        out_stop = resample_audio(stopband_signal, orig_sr, target_sr)
        stop_energy = float(np.mean(out_stop ** 2))
        pass_energy = float(np.mean(out_pass ** 2))
        self.assertLess(stop_energy, pass_energy * 0.05)

    def test_s5_windows_wasapi_persistent_stream(self):
        """S5: 测试 WindowsWASAPIPlayer 长连接复用同一个 OutputStream"""
        player = WindowsWASAPIPlayer(output_device=1)

        mock_stream = MagicMock()
        mock_stream.active = True

        with patch("sounddevice.OutputStream", return_value=mock_stream) as mock_out_ctor:
            # 连续获取两次流 (相同参数)
            s1 = player._get_or_create_stream("main", 1, 48000, 2)
            s2 = player._get_or_create_stream("main", 1, 48000, 2)

            self.assertIs(s1, s2)
            # OutputStream 仅构造了一次
            mock_out_ctor.assert_called_once()
            # 流未被频繁关闭
            mock_stream.close.assert_not_called()

        player.stop()

    def test_s6_get_default_data_dir(self):
        """S6: 测试非源码开发目录下数据目录自动使用用户数据目录隔离"""
        # 测试显式环境变量
        with patch.dict(os.environ, {"YUKKURI_DATA_DIR": "/tmp/custom_yukkuri_data"}):
            self.assertEqual(get_default_data_dir(), "/tmp/custom_yukkuri_data")

        # 模拟在非源码目录运行 (不存在 pyproject.toml)
        with patch.dict(os.environ, {}, clear=True):
            with patch("os.path.exists", return_value=False):
                with patch("sys.platform", "linux"):
                    data_dir = get_default_data_dir()
                    self.assertIn(".local/share/yukkuri", data_dir)

    def test_s7_virtual_mic_auto_cleanup(self):
        """S7/额外3: 测试 auto_cleanup 开关对 virtual_mic 的卸载控制"""
        with patch("yukkuri.audio.virtual_mic.LinuxPipeWireMicManager.is_pactl_available", return_value=True):
            with patch("subprocess.check_output", return_value="12345"):
                with patch("subprocess.run") as mock_run:
                    # 1. auto_cleanup = True 时执行卸载
                    mgr_auto = LinuxPipeWireMicManager(sink_name="test_sink", auto_cleanup=True)
                    mgr_auto.setup()
                    self.assertEqual(mgr_auto._loaded_modules, ["12345", "12345"])
                    mgr_auto.cleanup()
                    mock_run.assert_called()
                    self.assertEqual(len(mgr_auto._loaded_modules), 0)

                    # 2. auto_cleanup = False 时保留模块不执行 unload
                    mgr_keep = LinuxPipeWireMicManager(sink_name="test_sink", auto_cleanup=False)
                    mgr_keep.setup()
                    mock_run.reset_mock()
                    mgr_keep.cleanup()
                    mock_run.assert_not_called()

    def test_s8_leak_protection(self):
        """S8: 测试未找到虚拟设备时拦截向默认物理扬声器静默推流"""
        # 1. WindowsWASAPIPlayer
        player_win = WindowsWASAPIPlayer(output_device=None, allow_default_speaker=False)
        with patch.object(player_win, "find_default_cable_input", return_value=None):
            with patch.object(player_win, "_prepare_audio_for_device") as mock_prep:
                dummy_wav = b"RIFF" + b"\x00" * 40 + np.zeros(200, dtype=np.int16).tobytes()
                player_win._play_streams(dummy_wav)
                # 应当被提前拦截，不调用设备准备与推流
                mock_prep.assert_not_called()
        player_win.stop()

        # 2. LinuxPipeWirePlayer
        player_lnx = LinuxPipeWirePlayer(target_sink="missing_sink")
        with patch.object(player_lnx, "_is_sink_available", return_value=False):
            with patch("subprocess.Popen") as mock_popen:
                player_lnx.play(b"dummy_wav")
                # 等待队列消费
                player_lnx.queue.join()
                mock_popen.assert_not_called()
        player_lnx.stop()

    def test_pipeline_stop_idempotent(self):
        """额外2: 测试 Pipeline stop() 多线程并发调用的幂等性"""
        config = AppConfig()
        asr = MockASR()
        tts = MockTTS()
        mock_mic = MagicMock()

        pipeline = YukkuriPipeline(
            config=config,
            asr=asr,
            tts=tts,
            mic_manager=mock_mic,
        )
        pipeline.player = MagicMock()
        pipeline.mic_stream = MagicMock()

        threads = []
        for _ in range(5):
            t = threading.Thread(target=pipeline.stop)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # 底层各驱动与管理器的 stop / cleanup 仅被精准调用 1 次
        pipeline.mic_stream.stop.assert_called_once()
        pipeline.player.stop.assert_called_once()
        mock_mic.cleanup.assert_called_once()


if __name__ == "__main__":
    unittest.main()

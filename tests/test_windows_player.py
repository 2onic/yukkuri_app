"""
Windows WASAPI 音频播放推流与格式重采样单元测试
"""

import sys
import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from yukkuri.audio.player import (
    AudioPlayer,
    LinuxPipeWirePlayer,
    WindowsWASAPIPlayer,
)

class TestWindowsPlayer(unittest.TestCase):
    def test_audio_player_platform_dispatch(self):
        """测试 AudioPlayer 根据平台或 backend 参数隔离分发"""
        # Linux 平台下默认分发为 LinuxPipeWirePlayer
        with patch("sys.platform", "linux"):
            player = AudioPlayer()
            self.assertIsInstance(player.impl, LinuxPipeWirePlayer)
            player.stop()

        # Windows 平台下默认分发为 WindowsWASAPIPlayer
        with patch("sys.platform", "win32"):
            player = AudioPlayer()
            self.assertIsInstance(player.impl, WindowsWASAPIPlayer)
            player.stop()

        # 显式指定 backend="wasapi"
        player = AudioPlayer(backend="wasapi")
        self.assertIsInstance(player.impl, WindowsWASAPIPlayer)
        player.stop()

    def test_prepare_audio_for_device_resample_and_stereo(self):
        """测试 AquesTalk 8000Hz 单声道数据重采样并升混为 Windows 48000Hz 双声道立体声"""
        # 模拟 8000Hz 800 个样本 (100ms 单声道)
        mono_int16 = np.full(800, 1000, dtype=np.int16)

        def mock_check(device, samplerate, channels):
            # 模拟 Windows WASAPI: 8000Hz 不支持，只支持 48000Hz 2ch
            if samplerate == 48000 and channels == 2:
                return None
            raise RuntimeError("WASAPI format not supported")

        mock_dev_info = {"default_samplerate": 48000, "max_output_channels": 2}

        with patch("sounddevice.check_output_settings", side_effect=mock_check):
            with patch("sounddevice.query_devices", return_value=mock_dev_info):
                out_data, out_sr, out_ch = WindowsWASAPIPlayer._prepare_audio_for_device(
                    mono_int16=mono_int16,
                    src_sample_rate=8000,
                    device_id=3
                )

                self.assertEqual(out_sr, 48000)
                self.assertEqual(out_ch, 2)
                # 采样率 6 倍，样本行数应为 800 * 6 = 4800
                self.assertEqual(out_data.shape, (4800, 2))
                # 左右声道数据一致
                np.testing.assert_array_equal(out_data[:, 0], out_data[:, 1])

    def test_find_default_cable_input(self):
        """测试自动查找 VB-CABLE Input 设备索引"""
        mock_devices = [
            {"name": "Speakers (Realtek)", "max_output_channels": 2},
            {"name": "CABLE Input (VB-Audio Virtual Cable)", "max_output_channels": 2},
            {"name": "Headphones (USB Audio)", "max_output_channels": 2},
        ]
        with patch("sounddevice.query_devices", return_value=mock_devices):
            cable_idx = WindowsWASAPIPlayer.find_default_cable_input()
            self.assertEqual(cable_idx, 1)

    def test_set_monitor(self):
        """测试动态开启和关闭监听"""
        player = WindowsWASAPIPlayer(output_device=1)
        self.assertFalse(player.enable_monitor)
        player.set_monitor(True, device_id=5)
        self.assertTrue(player.enable_monitor)
        self.assertEqual(player.monitor_device, 5)
        player.set_monitor(False)
        self.assertFalse(player.enable_monitor)
        player.stop()

    def test_windows_vb_cable_manager(self):
        """测试 Windows VB-CABLE 驱动检测与状态管理"""
        from yukkuri.audio.virtual_mic import WindowsVBCableManager, VirtualMicManager

        mock_devices_installed = [
            {"name": "CABLE Input (VB-Audio)", "max_output_channels": 2, "max_input_channels": 0},
            {"name": "CABLE Output (VB-Audio)", "max_output_channels": 0, "max_input_channels": 2},
        ]
        with patch("sounddevice.query_devices", return_value=mock_devices_installed):
            self.assertTrue(WindowsVBCableManager.is_driver_installed())
            mgr = WindowsVBCableManager()
            self.assertTrue(mgr.setup())
            self.assertTrue(mgr._is_active)
            mgr.cleanup()
            self.assertFalse(mgr._is_active)

        mock_devices_missing = [
            {"name": "Speakers", "max_output_channels": 2, "max_input_channels": 0},
        ]
        with patch("sounddevice.query_devices", return_value=mock_devices_missing):
            self.assertFalse(WindowsVBCableManager.is_driver_installed())
            mgr = WindowsVBCableManager()
            self.assertFalse(mgr.setup())

        # 测试 VirtualMicManager 根据平台分派
        with patch("sys.platform", "win32"):
            v_mgr = VirtualMicManager()
            self.assertIsInstance(v_mgr.impl, WindowsVBCableManager)

    def test_get_output_devices(self):
        """测试获取系统输出设备并标记虚拟声卡"""
        from yukkuri.gui.devices import get_output_devices

        mock_devices = [
            {"name": "Speakers (Realtek High Definition Audio)", "max_output_channels": 2, "max_input_channels": 0},
            {"name": "CABLE Input (VB-Audio Virtual Cable)", "max_output_channels": 2, "max_input_channels": 0},
            {"name": "Headphones (USB Audio Device)", "max_output_channels": 2, "max_input_channels": 0},
            {"name": "Microphone (Realtek)", "max_output_channels": 0, "max_input_channels": 2},
        ]
        with patch("sounddevice.query_devices", return_value=mock_devices):
            devs = get_output_devices()
            # 应该包含一个默认项 + 3 个输出设备
            self.assertEqual(len(devs), 4)
            self.assertEqual(devs[0], (None, "系统默认 (Default)"))
            # CABLE Input 应该被标记为虚拟声卡
            self.assertIn("[虚拟声卡]", devs[2][1])
            # Speakers 和 Headphones 不应该有虚拟声卡标记
            self.assertNotIn("[虚拟声卡]", devs[1][1])
            self.assertNotIn("[虚拟声卡]", devs[3][1])

if __name__ == "__main__":
    unittest.main()

"""
麦克风音频采集流封装，支持硬件采样率自适应重采样与声道下混
"""

import sys
import queue
from typing import Optional, Callable, Tuple
import sounddevice as sd
import numpy as np
from yukkuri.audio.resample import resample_audio

class MicrophoneStream:
    """基于 sounddevice 的非阻塞麦克风采样流，具备硬件格式自适应与重采样能力"""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        blocksize: int = 800,
        device: Optional[int] = None,
        dtype: str = 'float32',
        gain: float = 1.0,
    ):
        self.sample_rate = sample_rate       # 目标采样率 (16000Hz 供 VAD 与 ASR)
        self.channels = channels             # 目标声道数 (1, 单声道)
        self.blocksize = blocksize           # 目标每块样本数 (800)
        self.device = device
        self.dtype = dtype
        self.gain = gain                     # 麦克风增益倍数 (默认 1.0)

        self.queue: queue.Queue = queue.Queue()
        self._stream: Optional[sd.InputStream] = None

        # 硬件自适应参数
        self.actual_sample_rate = sample_rate
        self.actual_channels = channels
        self.current_level: float = 0.0      # 实时 RMS 音量指示 (0.0 ~ 1.0)

    def set_gain(self, gain: float):
        """动态调整软件增益倍数"""
        self.gain = max(0.1, float(gain))

    @staticmethod
    def _get_wasapi_extra_settings(device_id: Optional[int]):
        """在 Windows 下为 WASAPI 设备配置 Shared Mode (共享模式)，避免独占模式引发底层驱动或占用冲突"""
        if sys.platform == "win32" and hasattr(sd, "WasapiSettings"):
            try:
                dev_id = device_id
                if dev_id is None:
                    def_dev = sd.default.device
                    dev_id = def_dev[0] if isinstance(def_dev, (list, tuple)) else def_dev
                if dev_id is not None and dev_id >= 0:
                    dev_info = sd.query_devices(dev_id, 'input')
                    hostapis = sd.query_hostapis()
                    dev_hostapi = hostapis[dev_info["hostapi"]]["name"].lower()
                    if "wasapi" in dev_hostapi:
                        return sd.WasapiSettings(exclusive=False)
            except Exception:
                pass
        return None

    def _resolve_input_parameters(self, device: Optional[int] = None) -> Tuple[int, int]:
        """探测并返回声卡硬件支持的 (sample_rate, channels)"""
        target_device = self.device if device is None else device
        extra_settings = self._get_wasapi_extra_settings(target_device)

        # 1. 优先尝试直接支持目标配置 (如 16000Hz, 1ch)
        try:
            sd.check_input_settings(
                device=target_device,
                samplerate=self.sample_rate,
                channels=self.channels,
                extra_settings=extra_settings
            )
            return self.sample_rate, self.channels
        except Exception:
            pass

        # 2. 查询设备推荐硬件参数
        default_sr = 48000
        max_ch = 2
        try:
            dev_info = sd.query_devices(target_device, 'input')
            default_sr = int(dev_info.get('default_samplerate', 48000))
            max_ch = int(dev_info.get('max_input_channels', 2))
        except Exception:
            pass

        # 候选采样率按优先级测试
        candidate_srs = [self.sample_rate, default_sr, 48000, 44100, 32000]
        candidate_srs = list(dict.fromkeys(candidate_srs))

        candidate_chs = [self.channels]
        if max_ch >= 2 and self.channels != 2:
            candidate_chs.append(2)
        if max_ch > 2 and max_ch not in candidate_chs:
            candidate_chs.append(max_ch)

        for sr in candidate_srs:
            for ch in candidate_chs:
                try:
                    sd.check_input_settings(
                        device=target_device,
                        samplerate=sr,
                        channels=ch,
                        extra_settings=extra_settings
                    )
                    return sr, ch
                except Exception:
                    continue

        return default_sr, min(2, max(1, max_ch))

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            if not hasattr(self, "_last_status_warned") or self._last_status_warned != str(status):
                self._last_status_warned = str(status)
                print(f"[麦克风状态警告]: {status}", file=sys.stderr)

        # 1. 多声道转换为单声道
        if indata.ndim == 2:
            if indata.shape[1] == 1:
                mono = indata[:, 0].copy()
            else:
                mono = np.mean(indata, axis=1, dtype=np.float32)
        else:
            mono = indata.flatten().copy()

        # 2. 增益调节
        if self.gain != 1.0:
            mono = np.clip(mono * self.gain, -1.0, 1.0)

        # 3. 计算 RMS 动态音量指标 (平滑衰减，供 UI 实时跳动)
        if len(mono) > 0:
            rms = float(np.sqrt(np.mean(mono ** 2)))
            target_level = min(1.0, rms * 8.0)
            self.current_level = 0.7 * self.current_level + 0.3 * target_level
        else:
            self.current_level = 0.0

        # 4. 采样率重采样至 self.sample_rate (16000Hz)（具备低通抗混叠滤波）
        if self.actual_sample_rate != self.sample_rate and len(mono) > 0:
            resampled = resample_audio(mono, self.actual_sample_rate, self.sample_rate).astype(np.float32)
        else:
            resampled = mono.astype(np.float32)

        # 5. 过滤非有限数值并投递队列
        if len(resampled) > 0:
            clean_samples = np.nan_to_num(resampled, copy=False)
            self.queue.put(clean_samples)

    def _open_and_start_stream(self, device: Optional[int]) -> bool:
        """尝试打开并启动指定设备的音频采集流，若失败则安全释放资源"""
        actual_sr, actual_ch = self._resolve_input_parameters(device)
        self.actual_sample_rate = actual_sr
        self.actual_channels = actual_ch

        extra_settings = self._get_wasapi_extra_settings(device)

        # 计算自适应硬件 blocksize (保持 50ms 左右切片)
        if actual_sr == self.sample_rate:
            hw_blocksize = self.blocksize
        else:
            hw_blocksize = int(round(actual_sr * 0.05))

        # 优先尝试指定块大小打开
        try:
            self._stream = sd.InputStream(
                samplerate=actual_sr,
                channels=actual_ch,
                dtype=self.dtype,
                blocksize=hw_blocksize,
                device=device,
                extra_settings=extra_settings,
                callback=self._audio_callback
            )
            self._stream.start()
            if actual_sr != self.sample_rate or actual_ch != self.channels:
                print(f"[麦克风采集已自适应]: 硬件格式 {actual_sr}Hz/{actual_ch}ch -> 自动重采样为 {self.sample_rate}Hz/单声道")
            return True
        except Exception:
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

        # 若失败，回退到系统自适应缓冲区大小尝试
        try:
            self._stream = sd.InputStream(
                samplerate=actual_sr,
                channels=actual_ch,
                dtype=self.dtype,
                device=device,
                extra_settings=extra_settings,
                callback=self._audio_callback
            )
            self._stream.start()
            if actual_sr != self.sample_rate or actual_ch != self.channels:
                print(f"[麦克风采集已自适应]: 硬件格式 {actual_sr}Hz/{actual_ch}ch -> 自动重采样为 {self.sample_rate}Hz/单声道")
            return True
        except Exception:
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            return False

    def start(self):
        if self._stream is not None:
            return

        # 1. 优先尝试以指定设备启动
        success = self._open_and_start_stream(self.device)
        if success:
            return

        # 2. 如果指定了特定设备且启动失败，自动回退到系统默认麦克风 (device=None)
        if self.device is not None:
            print(f"[麦克风警告] 无法启动所选麦克风 (设备 ID: {self.device})，正在自动安全回退至系统默认麦克风...", file=sys.stderr)
            fallback_success = self._open_and_start_stream(None)
            if fallback_success:
                print(f"[麦克风提示] 已成功回退至系统默认麦克风正常运行。")
                self.device = None
                return

        # 3. 若全部失败，抛出友好的错误信息
        raise RuntimeError(f"无法启动麦克风音频采集流 (设备 ID: {self.device})，请检查麦克风权限或更换输入设备。")

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
            self.current_level = 0.0

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

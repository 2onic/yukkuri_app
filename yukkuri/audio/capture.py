"""
麦克风音频采集流封装，支持硬件采样率自适应重采样与声道下混
"""

import sys
import queue
from typing import Optional, Callable, Tuple
import sounddevice as sd
import numpy as np

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

    def _resolve_input_parameters(self) -> Tuple[int, int]:
        """探测并返回声卡硬件支持的 (sample_rate, channels)"""
        # 1. 优先尝试直接支持目标配置 (如 16000Hz, 1ch)
        try:
            sd.check_input_settings(device=self.device, samplerate=self.sample_rate, channels=self.channels)
            return self.sample_rate, self.channels
        except Exception:
            pass

        # 2. 查询设备推荐硬件参数
        default_sr = 48000
        max_ch = 2
        try:
            dev_info = sd.query_devices(self.device, 'input')
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
                    sd.check_input_settings(device=self.device, samplerate=sr, channels=ch)
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

        # 4. 采样率重采样至 self.sample_rate (16000Hz)
        if self.actual_sample_rate != self.sample_rate and len(mono) > 0:
            target_len = int(round(len(mono) * self.sample_rate / self.actual_sample_rate))
            if target_len > 0:
                resampled = np.interp(
                    np.linspace(0, len(mono), target_len, endpoint=False),
                    np.arange(len(mono)),
                    mono
                ).astype(np.float32)
            else:
                resampled = np.empty(0, dtype=np.float32)
        else:
            resampled = mono.astype(np.float32)

        # 5. 过滤非有限数值并投递队列
        if len(resampled) > 0:
            clean_samples = np.nan_to_num(resampled, copy=False)
            self.queue.put(clean_samples)

    def start(self):
        if self._stream is not None:
            return

        actual_sr, actual_ch = self._resolve_input_parameters()
        self.actual_sample_rate = actual_sr
        self.actual_channels = actual_ch

        # 计算自适应硬件 blocksize (保持 50ms 左右切片)
        if actual_sr == self.sample_rate:
            hw_blocksize = self.blocksize
        else:
            hw_blocksize = int(round(actual_sr * 0.05))

        try:
            self._stream = sd.InputStream(
                samplerate=actual_sr,
                channels=actual_ch,
                dtype=self.dtype,
                blocksize=hw_blocksize,
                device=self.device,
                callback=self._audio_callback
            )
            self._stream.start()
            if actual_sr != self.sample_rate or actual_ch != self.channels:
                print(f"[麦克风采集已自适应]: 硬件格式 {actual_sr}Hz/{actual_ch}ch -> 自动重采样为 {self.sample_rate}Hz/单声道")
        except Exception:
            # 若指定块大小失败，回退到系统自适应缓冲区
            self._stream = sd.InputStream(
                samplerate=actual_sr,
                channels=actual_ch,
                dtype=self.dtype,
                device=self.device,
                callback=self._audio_callback
            )
            self._stream.start()

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

"""
Silero-VAD 语音活动检测器封装
"""

import os
from typing import List
import numpy as np

try:
    import sherpa_onnx
except ImportError:
    sherpa_onnx = None

class SileroVAD:
    """Silero-VAD 封装，用于高灵敏度检测说话开始与停顿"""

    def __init__(
        self,
        vad_model_path: str,
        sample_rate: int = 16000,
        min_silence_duration: float = 0.35,
        min_speech_duration: float = 0.15,
        max_speech_duration: float = 6.0,
        threshold: float = 0.5,
    ):
        if sherpa_onnx is None:
            raise ImportError("缺少 sherpa_onnx 依赖，无法使用 Silero-VAD")

        if not os.path.exists(vad_model_path):
            raise FileNotFoundError(f"未找到 VAD 模型文件: {vad_model_path}")

        vad_config = sherpa_onnx.VadModelConfig()
        vad_config.silero_vad.model = vad_model_path
        vad_config.silero_vad.min_silence_duration = min_silence_duration
        vad_config.silero_vad.min_speech_duration = min_speech_duration
        vad_config.silero_vad.max_speech_duration = max_speech_duration
        vad_config.silero_vad.threshold = threshold
        vad_config.sample_rate = sample_rate

        buf_size = max(60, int(max_speech_duration * 3))
        self._detector = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=buf_size)
        self.sample_rate = sample_rate
        self.min_silence_duration = float(min_silence_duration)
        self.max_speech_duration = float(max_speech_duration)

    def is_speech_detected(self) -> bool:
        """返回当前是否正在检测到持续人声"""
        if self._detector is not None:
            try:
                return bool(self._detector.is_speech_detected())
            except Exception:
                pass
        return False

    def reset(self):
        """重置检测器内部状态"""
        if self._detector is not None:
            try:
                self._detector.reset()
            except Exception:
                pass

    def set_min_silence_duration(self, duration: float):
        """动态调整静音断句判定时长 (秒)"""
        self.min_silence_duration = max(0.1, float(duration))
        if self._detector is not None:
            try:
                self._detector.config.silero_vad.min_silence_duration = self.min_silence_duration
            except Exception:
                pass

    def set_max_speech_duration(self, duration: float):
        """动态调整最大连续说话截断保护时长 (秒)"""
        self.max_speech_duration = max(1.0, float(duration))
        if self._detector is not None:
            try:
                self._detector.config.silero_vad.max_speech_duration = self.max_speech_duration
            except Exception:
                pass

    def accept_waveform(self, samples: np.ndarray) -> List[np.ndarray]:
        """
        接收音频切片，当检测到完整语音段（说话停顿或达到最大说话时长保护）时弹出有效段
        :param samples: float32 一维音频数组
        :return: 完成断句的有效语音切片列表
        """
        self._detector.accept_waveform(samples)

        # 防长语音缓冲保护：连续说话超出设定上限时强制刷新截断，保障低延迟识别与推流
        if self.max_speech_duration > 0 and self._detector.is_speech_detected():
            try:
                cur = self._detector.current_segment
                if len(cur.samples) >= int(self.max_speech_duration * self.sample_rate):
                    self._detector.flush()
            except Exception:
                pass

        segments = []
        while not self._detector.empty():
            seg = self._detector.front
            self._detector.pop()
            segments.append(np.array(seg.samples, dtype=np.float32))
        return segments

    def flush(self) -> List[np.ndarray]:
        """清空残余语音缓冲区"""
        self._detector.flush()
        segments = []
        while not self._detector.empty():
            seg = self._detector.front
            self._detector.pop()
            segments.append(np.array(seg.samples, dtype=np.float32))
        return segments

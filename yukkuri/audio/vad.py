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
        vad_config.silero_vad.threshold = threshold
        vad_config.sample_rate = sample_rate

        self._detector = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=30)
        self.sample_rate = sample_rate

    def accept_waveform(self, samples: np.ndarray) -> List[np.ndarray]:
        """
        接收音频切片，当检测到完整语音段（说话结束）时弹出有效段
        :param samples: float32 一维音频数组
        :return: 完成断句的有效语音切片列表
        """
        self._detector.accept_waveform(samples)
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

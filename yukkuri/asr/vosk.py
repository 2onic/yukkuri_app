"""
Vosk 轻量级离线识别引擎实现
"""

import json
import os
import numpy as np

try:
    from vosk import Model, KaldiRecognizer
except ImportError:
    Model = None
    KaldiRecognizer = None

from yukkuri.asr.base import BaseASREngine

class VoskASR(BaseASREngine):
    """经典 Vosk Kaldi 识别引擎"""

    def __init__(self, model_dir: str, sample_rate: int = 16000):
        if Model is None:
            raise ImportError("缺少 vosk 依赖，无法加载 Vosk 引擎")

        if not os.path.exists(model_dir):
            raise FileNotFoundError(f"未找到 Vosk 模型目录: {model_dir}")

        self.model = Model(model_dir)
        self.sample_rate = sample_rate

    def decode(self, samples: np.ndarray, sample_rate: int = 16000) -> str:
        """识别音频切片"""
        # 将 float32 转为 16位有符号整型 PCM
        if samples.dtype == np.float32:
            pcm_data = (samples * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
        else:
            pcm_data = bytes(samples)

        recognizer = KaldiRecognizer(self.model, sample_rate)
        recognizer.AcceptWaveform(pcm_data)
        res = json.loads(recognizer.FinalResult())
        return res.get("text", "").strip()

"""
SenseVoice-Small 端到端多语种高精度识别引擎实现
"""

import os
import re
import numpy as np

try:
    import sherpa_onnx
except ImportError:
    sherpa_onnx = None

from yukkuri.asr.base import BaseASREngine

def clean_sensevoice_text(text: str) -> str:
    """清理 SenseVoice 输出的情感与富文本标签 (如 <|NEUTRAL|><|HAPPY|> 等)"""
    clean = re.sub(r'<\|.*?\|>', '', text)
    return clean.strip()

class SenseVoiceASR(BaseASREngine):
    """阿里通义 SenseVoice-Small 识别引擎 (基于 sherpa-onnx)"""

    def __init__(self, model_dir: str, num_threads: int = 4):
        if sherpa_onnx is None:
            raise ImportError("缺少 sherpa_onnx 依赖，无法加载 SenseVoice 引擎")

        model_file = os.path.join(model_dir, "model.int8.onnx")
        if not os.path.exists(model_file):
            model_file = os.path.join(model_dir, "model.onnx")
        tokens_file = os.path.join(model_dir, "tokens.txt")

        if not (os.path.exists(model_file) and os.path.exists(tokens_file)):
            raise FileNotFoundError(f"SenseVoice 目录下缺少 model.int8.onnx / model.onnx 或 tokens.txt: {model_dir}")

        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=model_file,
            tokens=tokens_file,
            num_threads=num_threads,
            use_itn=True
        )

    def decode(self, samples: np.ndarray, sample_rate: int = 16000) -> str:
        """识别 float32 音频切片"""
        if len(samples) == 0:
            return ""

        stream = self.recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        self.recognizer.decode_stream(stream)
        raw_text = stream.result.text
        return clean_sensevoice_text(raw_text)

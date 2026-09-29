"""
统一配置管理与路径解析模块
"""

import os
from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class AppConfig:
    # 基础引擎选项
    engine: str = "sensevoice"          # "sensevoice" 或 "vosk"
    lang: str = "zh"                    # "zh", "cn", "ja", "en"
    speed: int = 100                    # 语速 50 ~ 300
    target_sink: str = "yukkuri_sink"   # 输出虚拟 Sink 名称
    device: Optional[int] = None        # 麦克风输入设备 ID (None 为系统默认)

    # 音频参数
    sample_rate: int = 16000
    channels: int = 1

    # VAD 参数
    vad_min_silence: float = 0.35       # 静音断句阈值 (秒)
    vad_min_speech: float = 0.15        # 最短有效语音长度 (秒)
    vad_threshold: float = 0.5          # VAD 灵敏度概率 (0.0 ~ 1.0)
    vad_min_sample_duration: float = 0.2 # 忽略过短杂音 (秒)

    # 性能与调试
    num_threads: int = 4
    verbose: bool = False
    enable_dynamic_mic: bool = True     # 自动通过 pactl 管理虚拟声卡

    # 自定义模型路径 (若指定则覆盖自动搜索)
    custom_model_path: Optional[str] = None

    # 项目根目录路径（自动计算）
    project_root: str = field(default_factory=lambda: os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

    def find_aquestalk_library(self) -> Optional[str]:
        """按优先级搜索 libAquesTalk.so 动态库"""
        candidates = [
            os.path.join(self.project_root, "libAquesTalk.so"),
            os.path.join(self.project_root, "libAquesTalk.so.1"),
            os.path.join(self.project_root, "yukkuri", "libs", "libAquesTalk.so"),
            "libAquesTalk.so",
            "libAquesTalk.so.1",
        ]
        for path in candidates:
            if os.path.exists(path):
                return os.path.abspath(path)
        return None

    def find_vad_model(self) -> Optional[str]:
        """按优先级搜索 silero_vad.onnx"""
        candidates = [
            os.path.join(self.project_root, "silero_vad.onnx"),
            os.path.join(self.project_root, "models", "silero_vad.onnx"),
            os.path.expanduser("~/.cache/yukkuri/silero_vad.onnx"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return os.path.abspath(path)
        return None

    def find_sensevoice_dir(self) -> Optional[str]:
        """按优先级搜索 SenseVoice 模型目录"""
        if self.custom_model_path and os.path.exists(self.custom_model_path):
            return os.path.abspath(self.custom_model_path)

        candidates = [
            os.path.join(self.project_root, "sensevoice"),
            os.path.join(self.project_root, "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"),
            os.path.join(self.project_root, "models", "sensevoice"),
            os.path.expanduser("~/.cache/yukkuri/sensevoice"),
        ]
        for path in candidates:
            int8_file = os.path.join(path, "model.int8.onnx")
            tokens_file = os.path.join(path, "tokens.txt")
            if os.path.exists(int8_file) and os.path.exists(tokens_file):
                return os.path.abspath(path)
        return None

    def find_vosk_model_dir(self) -> Optional[str]:
        """按语种与优先级搜索 Vosk 模型目录"""
        if self.custom_model_path and os.path.exists(self.custom_model_path):
            return os.path.abspath(self.custom_model_path)

        mapping = {
            "zh": ["model_cn", "model", "models/model_cn", "models/model"],
            "cn": ["model_cn", "model", "models/model_cn", "models/model"],
            "ja": ["model_ja", "model", "models/model_ja", "models/model"],
            "en": ["model_en", "model", "models/model_en", "models/model"]
        }
        candidates = mapping.get(self.lang.lower(), ["model"])
        for c in candidates:
            p = os.path.join(self.project_root, c)
            if os.path.exists(p):
                return os.path.abspath(p)
        return None

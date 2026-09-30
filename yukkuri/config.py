"""
统一配置管理与路径解析模块
"""

import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict

AQUESTALK_VOICES = {
    "f1": "女声1",
    "f2": "女声2",
    "f3": "女声3",
    "m1": "男声1",
    "m2": "男声2",
    "imd1": "中性音",
    "jgr": "机械音",
    "dvd": "播音员",
    "r1": "机器人",
}

@dataclass
class AppConfig:
    # 基础引擎选项
    engine: str = "sensevoice"          # "sensevoice" 或 "vosk"
    lang: str = "zh"                    # "zh", "cn", "ja", "en"
    voice: str = "f1"                   # 默认声线: "f1", 可选 "f2", "f3", "m1", "m2", "imd1", "jgr", "dvd", "r1"
    speed: int = 100                    # 语速 50 ~ 300
    target_sink: str = "yukkuri_sink"   # 输出虚拟 Sink 名称
    source_name: str = "yukkuri_source" # 虚拟输入 Source 名称 (供录音或回放监听捕获)
    enable_loopback: bool = False       # 是否开启自身回放监听 (耳机/扬声器实时听到油库里语音)
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

    # 自定义模型与声线库路径 (若指定则覆盖自动搜索)
    custom_model_path: Optional[str] = None
    custom_aquestalk_dir: Optional[str] = None

    # 项目根目录路径（自动计算）
    project_root: str = field(default_factory=lambda: os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

    def find_aquestalk_library(self, voice: Optional[str] = None) -> Optional[str]:
        """
        按声线与优先级搜索对应的 libAquesTalk.so 动态库
        :param voice: 声线名称 (如 "f1", "f2", "m1" 等)，若未指定则使用 self.voice
        """
        target_voice = (voice or self.voice or "f1").lower()
        candidates = []

        # 1. 自定义指定目录
        if self.custom_aquestalk_dir and os.path.exists(self.custom_aquestalk_dir):
            c_dir = self.custom_aquestalk_dir
            candidates.extend([
                os.path.join(c_dir, "lib64", target_voice, "libAquesTalk.so"),
                os.path.join(c_dir, target_voice, "libAquesTalk.so"),
                os.path.join(c_dir, f"libAquesTalk-{target_voice}.so"),
                os.path.join(c_dir, f"libAquesTalk_{target_voice}.so"),
                os.path.join(c_dir, "libAquesTalk.so"),
            ])

        # 2. 项目内 libs / aquestalk 目录
        candidates.extend([
            os.path.join(self.project_root, "libs", "aquestalk", "lib64", target_voice, "libAquesTalk.so"),
            os.path.join(self.project_root, "libs", "aquestalk", target_voice, "libAquesTalk.so"),
            os.path.join(self.project_root, "libs", "lib64", target_voice, "libAquesTalk.so"),
            os.path.join(self.project_root, "libs", target_voice, "libAquesTalk.so"),
            os.path.join(self.project_root, f"libAquesTalk-{target_voice}.so"),
            os.path.join(self.project_root, f"libAquesTalk_{target_voice}.so"),
            os.path.join(self.project_root, "libs", f"libAquesTalk-{target_voice}.so"),
        ])

        # 3. 用户常用安装或缓存路径 (~/.cache/yukkuri/aquestalk 或 ~/opt)
        home = os.path.expanduser("~")
        candidates.extend([
            os.path.join(home, ".cache", "yukkuri", "aquestalk", "lib64", target_voice, "libAquesTalk.so"),
            os.path.join(home, ".cache", "yukkuri", "aquestalk", target_voice, "libAquesTalk.so"),
            os.path.join(home, "opt", "aqtk1_lnx_200", "aqtk1_lnx", "lib64", target_voice, "libAquesTalk.so"),
            os.path.join("/opt", "aqtk1_lnx_200", "aqtk1_lnx", "lib64", target_voice, "libAquesTalk.so"),
        ])

        # 4. 回退：如果是 f1 或单库模式，检查根目录动态库
        if target_voice == "f1":
            candidates.extend([
                os.path.join(self.project_root, "libAquesTalk.so"),
                os.path.join(self.project_root, "libAquesTalk.so.1"),
                os.path.join(self.project_root, "libs", "libAquesTalk.so"),
                os.path.join(self.project_root, "libs", "aquestalk", "libAquesTalk.so"),
                "libAquesTalk.so",
                "libAquesTalk.so.1",
            ])

        for path in candidates:
            if os.path.exists(path):
                return os.path.abspath(path)
        return None

    def get_available_voices(self) -> Dict[str, str]:
        """获取当前系统已安装就绪的声线字典 {voice_id: voice_desc}"""
        available = {}
        for v_id, v_desc in AQUESTALK_VOICES.items():
            if self.find_aquestalk_library(v_id) is not None:
                available[v_id] = v_desc
        return available

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
            os.path.join(self.project_root, "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"),
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

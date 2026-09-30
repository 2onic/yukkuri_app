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
    output_device: Optional[int] = None # Windows 目标播放设备 ID (默认自动寻找 CABLE Input)
    monitor_device: Optional[int] = None # Windows 耳机监听设备 ID (默认使用系统默认输出)

    # 音频参数
    sample_rate: int = 16000
    channels: int = 1
    mic_gain: float = 1.0               # 麦克风输入增益倍数 (默认 1.0)

    # VAD 参数
    vad_min_silence: float = 0.35       # 静音断句阈值 (秒)
    vad_min_speech: float = 0.15        # 最短有效语音长度 (秒)
    vad_max_speech: float = 6.0         # 最长单句强制截断断句 (秒, <=0 表示关闭截断)
    vad_enable_max_speech: bool = True  # 是否启用最长单句强制截断保护
    vad_threshold: float = 0.5          # VAD 灵敏度概率 (0.0 ~ 1.0)
    vad_min_sample_duration: float = 0.2 # 忽略过短杂音 (秒)

    def get_effective_max_speech_duration(self) -> float:
        """获取实际生效的截断保护时长 (若未启用则返回 0.0)"""
        return self.vad_max_speech if self.vad_enable_max_speech and self.vad_max_speech > 0 else 0.0

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
        按声线与平台搜索对应的 AquesTalk 动态库 (Linux .so / Windows .dll)
        :param voice: 声线名称 (如 "f1", "f2", "m1" 等)，若未指定则使用 self.voice
        """
        import sys
        target_voice = (voice or self.voice or "f1").lower()
        is_win = sys.platform == "win32"

        if is_win:
            primary_names = [
                f"AquesTalk-{target_voice}.dll",
                f"AquesTalk_{target_voice}.dll",
                "AquesTalk.dll",
                "AquesTalk2.dll",
            ]
        else:
            primary_names = [
                f"libAquesTalk-{target_voice}.so",
                f"libAquesTalk_{target_voice}.so",
                "libAquesTalk.so",
                "libAquesTalk.so.1",
            ]

        search_dirs = []
        if self.custom_aquestalk_dir and os.path.exists(self.custom_aquestalk_dir):
            search_dirs.extend([
                os.path.join(self.custom_aquestalk_dir, "lib64", target_voice),
                os.path.join(self.custom_aquestalk_dir, target_voice),
                os.path.join(self.custom_aquestalk_dir, "lib64"),
                self.custom_aquestalk_dir,
            ])

        search_dirs.extend([
            os.path.join(self.project_root, "libs", "aquestalk", "lib64", target_voice),
            os.path.join(self.project_root, "libs", "aquestalk", target_voice),
            os.path.join(self.project_root, "libs", "lib64", target_voice),
            os.path.join(self.project_root, "libs", target_voice),
            os.path.join(self.project_root, "libs", "aquestalk"),
            os.path.join(self.project_root, "libs"),
        ])

        home = os.path.expanduser("~")
        search_dirs.extend([
            os.path.join(home, ".cache", "yukkuri", "aquestalk", "lib64", target_voice),
            os.path.join(home, ".cache", "yukkuri", "aquestalk", target_voice),
            os.path.join(home, ".cache", "yukkuri", "aquestalk"),
            os.path.join(home, "opt", "aqtk1_lnx_200", "aqtk1_lnx", "lib64", target_voice),
            os.path.join("/opt", "aqtk1_lnx_200", "aqtk1_lnx", "lib64", target_voice),
        ])

        if target_voice == "f1":
            search_dirs.append(self.project_root)

        for d in search_dirs:
            if not os.path.exists(d):
                continue
            for fn in primary_names:
                p = os.path.join(d, fn)
                if os.path.exists(p):
                    return os.path.abspath(p)

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

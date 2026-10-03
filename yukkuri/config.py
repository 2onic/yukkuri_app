"""
统一配置管理与路径解析模块
支持源码开发目录与 pip 全局安装环境 (XDG/AppData 用户目录隔离) 自适应切换
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Optional, List, Dict


def get_default_data_dir() -> str:
    """
    获取全局模型与数据存储目录：
    1. 优先读取环境变量 YUKKURI_DATA_DIR 或 YUKKURI_MODELS_DIR
    2. 如果当前运行在源码开发仓库中 (存在 pyproject.toml 且目录可写)，优先使用项目根目录
    3. 否则 (如 pip install . 安装至 site-packages)，使用系统级用户数据目录，避免权限不足或污染包目录：
       - Linux/macOS: ~/.local/share/yukkuri (符合 XDG Base Directory 规范)
       - Windows: %LOCALAPPDATA%/yukkuri 或 %APPDATA%/yukkuri
    """
    env_dir = os.environ.get("YUKKURI_DATA_DIR") or os.environ.get("YUKKURI_MODELS_DIR")
    if env_dir:
        return os.path.abspath(env_dir)

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    is_source_repo = os.path.exists(os.path.join(repo_root, "pyproject.toml"))
    if is_source_repo and os.access(repo_root, os.W_OK):
        return repo_root

    if sys.platform == "win32":
        base_dir = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
        data_dir = os.path.join(base_dir, "yukkuri")
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        data_dir = os.path.join(xdg_data, "yukkuri")

    try:
        os.makedirs(data_dir, exist_ok=True)
    except Exception:
        pass
    return data_dir


def _load_env_file():
    """轻量读取项目根目录、工作目录或用户数据目录下的 .env 环境变量文件 (零外部依赖)"""
    candidate_paths = [
        os.path.join(os.getcwd(), ".env"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")),
        os.path.join(get_default_data_dir(), ".env"),
    ]
    for p in candidate_paths:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass
            break


_load_env_file()

AQUESTALK_VOICES = {
    "f1": "女声1",
    "f2": "女声2",
    "f3": "女声3",
    "m1": "男声1",
    "m2": "男声2",
    "r1": "机器人声",
    "dvd": "DVD声",
    "imd1": "中性声",
    "jgr": "老者声",
}


@dataclass
class AppConfig:
    # 语音引擎选择: "sensevoice" 或 "vosk"
    engine: str = "sensevoice"

    # 识别语言: "zh", "ja", "en"
    lang: str = "zh"

    # AquesTalk 声线代号 (默认 "f1")
    voice: str = "f1"

    # 语速调节 (百分比, 默认 100)
    speed: int = 100

    # 音频输入输出参数
    sample_rate: int = 16000
    channels: int = 1
    device: Optional[int] = None            # 麦克风硬件设备索引
    output_device: Optional[int] = None     # 目标播放设备索引 (Windows WASAPI/VB-CABLE)
    monitor_device: Optional[int] = None    # 本地监听输出设备索引 (耳机)
    mic_gain: float = 1.0                   # 麦克风输入软件增益倍数 (0.1 ~ 5.0)
    output_gain: float = 1.0                # 合成语音推流输出增益倍数 (0.1 ~ 5.0)

    # 虚拟声卡名称 (Linux PipeWire 节点名)
    target_sink: str = "yukkuri_sink"
    source_name: str = "yukkuri_source"

    # Silero-VAD 端点检测参数
    vad_threshold: float = 0.5
    vad_min_silence: float = 0.3            # 静音截断判定时长 (秒)
    vad_min_speech: float = 0.15            # 起始有效语音最短时长 (秒)
    vad_max_speech: float = 6.0             # 单句语音强制截断上限 (秒)
    vad_enable_max_speech: bool = True      # 是否启用单句强制截断
    vad_min_sample_duration: float = 0.3    # 送入 ASR 的最短有效语音切片时长 (秒)

    # 性能配置
    num_threads: int = 4

    # 增强选项
    enable_loopback: bool = False
    verbose: bool = False
    enable_dynamic_mic: bool = True         # 退出时是否自动释放虚拟声卡

    # 自定义模型与声线库路径 (若指定则覆盖自动搜索)
    custom_model_path: Optional[str] = None
    custom_aquestalk_dir: Optional[str] = None

    # AquesTalk 官方授权密钥 (可选，支持从环境变量 AQUESTALK_DEV_KEY / AQUESTALK_USR_KEY 读取)
    dev_key: Optional[str] = field(default_factory=lambda: os.environ.get("AQUESTALK_DEV_KEY", None))
    usr_key: Optional[str] = field(default_factory=lambda: os.environ.get("AQUESTALK_USR_KEY", None))

    # 项目根目录路径（自动计算，非开发环境落入用户数据目录）
    project_root: str = field(default_factory=get_default_data_dir)

    def get_effective_max_speech_duration(self) -> float:
        """获取当前有效的最长切片时长"""
        if self.vad_enable_max_speech and self.vad_max_speech > 0.0:
            return float(self.vad_max_speech)
        return 0.0

    def find_aquestalk_library(self, voice: Optional[str] = None) -> Optional[str]:
        """
        按声线与平台搜索对应的 AquesTalk 动态库 (Linux .so / Windows .dll)
        :param voice: 声线名称 (如 "f1", "f2", "m1" 等)，若未指定则使用 self.voice
        """
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

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        candidate_roots = list(dict.fromkeys([
            self.project_root,
            repo_root,
            os.path.expanduser("~/.local/share/yukkuri"),
        ]))

        for r in candidate_roots:
            search_dirs.extend([
                os.path.join(r, "libs", "aquestalk", "lib64", target_voice),
                os.path.join(r, "libs", "aquestalk", target_voice),
                os.path.join(r, "libs", "lib64", target_voice),
                os.path.join(r, "libs", target_voice),
                os.path.join(r, "libs", "aquestalk"),
                os.path.join(r, "libs"),
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
            search_dirs.append(repo_root)

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
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        candidates = [
            os.path.join(self.project_root, "silero_vad.onnx"),
            os.path.join(self.project_root, "models", "silero_vad.onnx"),
            os.path.join(repo_root, "silero_vad.onnx"),
            os.path.join(repo_root, "models", "silero_vad.onnx"),
            os.path.expanduser("~/.local/share/yukkuri/silero_vad.onnx"),
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

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        roots = list(dict.fromkeys([
            self.project_root,
            repo_root,
            os.path.expanduser("~/.local/share/yukkuri"),
            os.path.expanduser("~/.cache/yukkuri"),
        ]))
        subnames = [
            "sensevoice",
            "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17",
            "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
            os.path.join("models", "sensevoice"),
        ]
        for r in roots:
            for s in subnames:
                p = os.path.join(r, s)
                int8_file = os.path.join(p, "model.int8.onnx")
                onnx_file = os.path.join(p, "model.onnx")
                tokens_file = os.path.join(p, "tokens.txt")
                if (os.path.exists(int8_file) or os.path.exists(onnx_file)) and os.path.exists(tokens_file):
                    return os.path.abspath(p)
        return None

    def find_vosk_model_dir(self) -> Optional[str]:
        """按语种与优先级搜索 Vosk 模型目录"""
        if self.custom_model_path and os.path.exists(self.custom_model_path):
            return os.path.abspath(self.custom_model_path)

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        roots = list(dict.fromkeys([
            self.project_root,
            repo_root,
            os.path.expanduser("~/.local/share/yukkuri"),
            os.path.expanduser("~/.cache/yukkuri"),
        ]))
        mapping = {
            "zh": ["model_cn", "model", "models/model_cn", "models/model"],
            "cn": ["model_cn", "model", "models/model_cn", "models/model"],
            "ja": ["model_ja", "model", "models/model_ja", "models/model"],
            "en": ["model_en", "model", "models/model_en", "models/model"]
        }
        candidates = mapping.get(self.lang.lower(), ["model"])
        for r in roots:
            for c in candidates:
                p = os.path.join(r, c)
                if os.path.exists(p):
                    return os.path.abspath(p)
        return None

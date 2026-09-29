"""
AquesTalk1 动态库 (ctypes) 封装实现
支持多声线动态切换与缓存管理
"""

import ctypes
import os
import sys
import threading
from typing import Optional, Callable, Dict, Tuple

from yukkuri.tts.base import BaseTTSEngine

AQUESTALK_ERROR_MAP = {
    100: "その他のエラー (Other error)",
    101: "メモリ不足 (Out of memory)",
    102: "音記号列の長さ制限オーバー (Koe string too long)",
    103: "音記号列が空 (Empty koe string)",
    104: "初期化されていない (Not initialized)",
    105: "音声記号列に未定義の読み記号が指定された (Undefined phonetic symbol)",
    106: "ポーズ長オーバー (Pause too long)",
    107: "音記号列の指定フォーマット不正 (Invalid format)",
}

class AquesTalk1Engine(BaseTTSEngine):
    """经典 AquesTalk1 C 动态库合成引擎，支持多声线无缝热切换"""

    def __init__(
        self,
        lib_path: Optional[str] = None,
        voice: str = "f1",
        voice_resolver: Optional[Callable[[str], Optional[str]]] = None
    ):
        self.voice_resolver = voice_resolver
        self._current_voice = voice.lower()
        self._lock = threading.Lock()

        # 声线缓存: voice_name -> (cdll_lib, synthe_fn, use_utf8)
        self._loaded_voices: Dict[str, Tuple[ctypes.CDLL, Callable, bool]] = {}

        if lib_path:
            self._load_library(self._current_voice, lib_path)
        elif self.voice_resolver:
            path = self.voice_resolver(self._current_voice)
            if not path:
                raise FileNotFoundError(f"未找到声线 '{self._current_voice}' 对应的 libAquesTalk.so 动态库")
            self._load_library(self._current_voice, path)
        else:
            raise ValueError("必须提供 lib_path 或 voice_resolver 之一以初始化 AquesTalk 引擎")

    def _load_library(self, voice: str, path: str):
        """加载特定声线的动态库并配置符号签名"""
        if not os.path.exists(path):
            raise FileNotFoundError(f"未找到 libAquesTalk.so 动态库: {path}")

        try:
            lib = ctypes.cdll.LoadLibrary(path)
        except Exception as e:
            raise RuntimeError(f"无法加载 AquesTalk 动态库 {path}: {e}")

        if hasattr(lib, 'AquesTalk_Synthe_Utf8'):
            synthe_fn = lib.AquesTalk_Synthe_Utf8
            use_utf8 = True
        else:
            synthe_fn = lib.AquesTalk_Synthe
            use_utf8 = False

        synthe_fn.restype = ctypes.POINTER(ctypes.c_ubyte)
        synthe_fn.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        lib.AquesTalk_FreeWave.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]

        self._loaded_voices[voice] = (lib, synthe_fn, use_utf8)

    @property
    def current_voice(self) -> str:
        return self._current_voice

    def set_voice(self, voice: str) -> bool:
        """
        动态切换当前声线 (如 'f1', 'f2', 'm1')
        若声线库未加载过，会自动调用 voice_resolver 解析并加载
        """
        voice = voice.lower()
        with self._lock:
            if voice in self._loaded_voices:
                self._current_voice = voice
                return True

            if not self.voice_resolver:
                print(f"[AquesTalk 警告] 未提供 voice_resolver，无法自动加载新声线: {voice}", file=sys.stderr)
                return False

            lib_path = self.voice_resolver(voice)
            if not lib_path or not os.path.exists(lib_path):
                print(f"[AquesTalk 错误] 未找到声线 '{voice}' 对应的动态库文件", file=sys.stderr)
                return False

            try:
                self._load_library(voice, lib_path)
                self._current_voice = voice
                return True
            except Exception as e:
                print(f"[AquesTalk 错误] 加载声线 '{voice}' 失败: {e}", file=sys.stderr)
                return False

    def synthesize(self, koe: str, speed: int = 100, voice: Optional[str] = None) -> Optional[bytes]:
        """将假名音标合成为 WAV 二进制字节流"""
        if not koe.strip():
            return None

        target_voice = (voice or self._current_voice).lower()

        with self._lock:
            if target_voice not in self._loaded_voices:
                if not self.set_voice(target_voice):
                    # 回退到当前声线
                    target_voice = self._current_voice

            lib, synthe_fn, use_utf8 = self._loaded_voices[target_voice]

        speed = max(50, min(300, speed))
        size = ctypes.c_int(0)
        encoding = 'utf-8' if use_utf8 else 'shift-jis'
        encoded_data = koe.encode(encoding, errors='ignore')

        wav_ptr = synthe_fn(encoded_data, speed, ctypes.byref(size))
        if not wav_ptr:
            err_code = size.value
            err_desc = AQUESTALK_ERROR_MAP.get(err_code, "未知错误")
            print(f"[AquesTalk 错误] 错误码 {err_code}: {err_desc} (声线: {target_voice}, 音标: '{koe}')", file=sys.stderr)
            return None

        try:
            wav_data = ctypes.string_at(wav_ptr, size.value)
        finally:
            lib.AquesTalk_FreeWave(wav_ptr)

        return wav_data

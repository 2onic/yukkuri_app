"""
AquesTalk1 动态库 (ctypes) 封装实现
"""

import ctypes
import os
import sys
from typing import Optional

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
    """经典 AquesTalk1 C 动态库合成引擎"""

    def __init__(self, lib_path: str):
        self.lib_path = lib_path
        if not os.path.exists(lib_path):
            raise FileNotFoundError(f"未找到 libAquesTalk.so 动态库: {lib_path}")

        try:
            self._lib = ctypes.cdll.LoadLibrary(lib_path)
        except Exception as e:
            raise RuntimeError(f"无法加载 AquesTalk 动态库 {lib_path}: {e}")

        # 优先使用 UTF-8 接口，若无则回退到 Shift-JIS 接口
        if hasattr(self._lib, 'AquesTalk_Synthe_Utf8'):
            self._synthe_fn = self._lib.AquesTalk_Synthe_Utf8
            self._use_utf8 = True
        else:
            self._synthe_fn = self._lib.AquesTalk_Synthe
            self._use_utf8 = False

        self._synthe_fn.restype = ctypes.POINTER(ctypes.c_ubyte)
        self._synthe_fn.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        self._lib.AquesTalk_FreeWave.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]

    def synthesize(self, koe: str, speed: int = 100) -> Optional[bytes]:
        """将假名音标合成为 WAV 二进制字节流"""
        if not koe.strip():
            return None

        speed = max(50, min(300, speed))
        size = ctypes.c_int(0)
        encoding = 'utf-8' if self._use_utf8 else 'shift-jis'
        encoded_data = koe.encode(encoding, errors='ignore')

        wav_ptr = self._synthe_fn(encoded_data, speed, ctypes.byref(size))
        if not wav_ptr:
            err_code = size.value
            err_desc = AQUESTALK_ERROR_MAP.get(err_code, "未知错误")
            print(f"[AquesTalk 错误] 错误码 {err_code}: {err_desc} (音标: '{koe}')", file=sys.stderr)
            return None

        try:
            wav_data = ctypes.string_at(wav_ptr, size.value)
        finally:
            self._lib.AquesTalk_FreeWave(wav_ptr)

        return wav_data

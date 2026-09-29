"""
语音识别与 VAD 模型下载管理器
支持断点检测、解压、文件清理与下载进度回调
"""

import os
import shutil
import tarfile
import zipfile
import urllib.request
from typing import Callable, Optional, Dict

VAD_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
SENSEVOICE_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2"
VOSK_URLS = {
    "zh": "https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip",
    "ja": "https://alphacephei.com/vosk/models/vosk-model-small-ja-0.22.zip",
    "en": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
}

def get_project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def check_model_status(root: Optional[str] = None) -> Dict[str, bool]:
    """检查各类模型在本地的存在状态"""
    root = root or get_project_root()
    sense_dir = os.path.join(root, "sensevoice")
    sense_orig = os.path.join(root, "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17")

    return {
        "vad": os.path.exists(os.path.join(root, "silero_vad.onnx")),
        "sensevoice": (
            (os.path.exists(os.path.join(sense_dir, "model.int8.onnx")) and os.path.exists(os.path.join(sense_dir, "tokens.txt"))) or
            (os.path.exists(os.path.join(sense_orig, "model.int8.onnx")) and os.path.exists(os.path.join(sense_orig, "tokens.txt")))
        ),
        "vosk_zh": os.path.exists(os.path.join(root, "model_cn", "am", "final.mdl")) or os.path.exists(os.path.join(root, "model", "am", "final.mdl")),
        "vosk_ja": os.path.exists(os.path.join(root, "model_ja", "am", "final.mdl")),
        "vosk_en": os.path.exists(os.path.join(root, "model_en", "am", "final.mdl")),
    }

def download_file(
    url: str,
    target_path: str,
    progress_callback: Optional[Callable[[int, int], None]] = None
):
    """
    通用带进度回调的文件下载
    progress_callback: (downloaded_bytes, total_bytes)
    """
    class ProgressTracker:
        def __init__(self):
            self.total = -1

        def hook(self, block_num, block_size, total_size):
            if total_size > 0:
                self.total = total_size
            downloaded = block_num * block_size
            if progress_callback:
                progress_callback(min(downloaded, self.total if self.total > 0 else downloaded), self.total)

    tracker = ProgressTracker()
    urllib.request.urlretrieve(url, target_path, reporthook=tracker.hook)

def download_vad(
    root: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> str:
    """下载 Silero-VAD 模型文件 (约 630KB)"""
    root = root or get_project_root()
    target_file = os.path.join(root, "silero_vad.onnx")
    download_file(VAD_URL, target_file, progress_callback=progress_callback)
    return target_file

def download_sensevoice(
    root: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> str:
    """下载并解压 SenseVoice-Small 模型 (量化后约 230MB)"""
    root = root or get_project_root()
    archive_path = os.path.join(root, "sensevoice.tar.bz2")
    sense_dir_name = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    extracted_dir = os.path.join(root, sense_dir_name)

    download_file(SENSEVOICE_URL, archive_path, progress_callback=progress_callback)

    # 解压
    with tarfile.open(archive_path, "r:bz2") as tar:
        tar.extractall(path=root)

    # 清理压缩包与未量化大模型 (900MB)
    if os.path.exists(archive_path):
        os.remove(archive_path)

    unquantized = os.path.join(extracted_dir, "model.onnx")
    if os.path.exists(unquantized):
        os.remove(unquantized)

    # 创建软链接 sensevoice
    symlink_path = os.path.join(root, "sensevoice")
    if os.path.islink(symlink_path) or os.path.exists(symlink_path):
        try:
            os.remove(symlink_path)
        except Exception:
            pass
    try:
        os.symlink(sense_dir_name, symlink_path)
    except Exception:
        pass

    return symlink_path

def download_vosk(
    lang: str = "zh",
    root: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> str:
    """下载并解压 Vosk 单语种轻量模型"""
    root = root or get_project_root()
    if lang not in VOSK_URLS:
        raise ValueError(f"不支持的 Vosk 语种: {lang} (支持: zh, ja, en)")

    url = VOSK_URLS[lang]
    zip_path = os.path.join(root, f"vosk_{lang}.zip")
    target_dir = os.path.join(root, f"model_{lang}")

    download_file(url, zip_path, progress_callback=progress_callback)

    with zipfile.ZipFile(zip_path, "r") as zf:
        # 获取第一级目录名
        top_dir = zf.namelist()[0].split('/')[0]
        zf.extractall(path=root)

    if os.path.exists(zip_path):
        os.remove(zip_path)

    extracted_path = os.path.join(root, top_dir)
    if os.path.exists(extracted_path) and extracted_path != target_dir:
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        os.rename(extracted_path, target_dir)

    return target_dir

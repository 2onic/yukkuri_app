"""
语音识别与 VAD 模型下载管理器
支持断点检测、解压、文件清理与下载进度回调
"""

import os
import shutil
import tarfile
import zipfile
import urllib.request
from typing import Callable, Optional, Dict, List, Any

VAD_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
SENSEVOICE_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2"
VOSK_URLS = {
    "zh": "https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip",
    "ja": "https://alphacephei.com/vosk/models/vosk-model-small-ja-0.22.zip",
    "en": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
}

def get_project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def check_model_status(root: Optional[str] = None) -> Dict[str, object]:
    """检查各类模型在本地的存在状态"""
    root = root or get_project_root()
    sense_dir = os.path.join(root, "sensevoice")
    sense_int8 = os.path.join(root, "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17")
    sense_orig = os.path.join(root, "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17")

    from yukkuri.config import AppConfig
    cfg = AppConfig(project_root=root)
    avail_voices = cfg.get_available_voices()

    return {
        "vad": os.path.exists(os.path.join(root, "silero_vad.onnx")),
        "sensevoice": (
            (os.path.exists(os.path.join(sense_dir, "model.int8.onnx")) and os.path.exists(os.path.join(sense_dir, "tokens.txt"))) or
            (os.path.exists(os.path.join(sense_int8, "model.int8.onnx")) and os.path.exists(os.path.join(sense_int8, "tokens.txt"))) or
            (os.path.exists(os.path.join(sense_orig, "model.int8.onnx")) and os.path.exists(os.path.join(sense_orig, "tokens.txt")))
        ),
        "vosk_zh": os.path.exists(os.path.join(root, "model_cn", "am", "final.mdl")) or os.path.exists(os.path.join(root, "model", "am", "final.mdl")),
        "vosk_ja": os.path.exists(os.path.join(root, "model_ja", "am", "final.mdl")),
        "vosk_en": os.path.exists(os.path.join(root, "model_en", "am", "final.mdl")),
        "aquestalk": len(avail_voices) > 0,
        "aquestalk_count": len(avail_voices),
        "aquestalk_voices": list(avail_voices.keys()),
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
    """下载并解压 SenseVoice-Small 模型 (官方精简版约 155MB)"""
    root = root or get_project_root()
    archive_path = os.path.join(root, "sensevoice.tar.bz2")
    sense_dir_name = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
    sense_orig_name = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    extracted_dir = os.path.join(root, sense_dir_name)

    if not os.path.exists(archive_path) or os.path.getsize(archive_path) == 0:
        download_file(SENSEVOICE_URL, archive_path, progress_callback=progress_callback)

    # 优先使用系统原生 tar 解压以保证极速，避免 Python bzip2 倒回寻址性能瓶颈
    extracted = False
    if shutil.which("tar"):
        try:
            import subprocess
            cmd = ["tar", "--exclude=*model.onnx", "-xf", archive_path]
            res = subprocess.run(cmd, cwd=root, capture_output=True)
            if res.returncode == 0:
                extracted = True
            else:
                res2 = subprocess.run(["tar", "-xf", archive_path], cwd=root, capture_output=True)
                if res2.returncode == 0:
                    extracted = True
        except Exception:
            extracted = False

    if not extracted:
        # 回退至 Python 纯流式单遍解压 (严禁使用 tar.getmembers() 避免 1GB bz2 倒回寻址导致死循环卡顿)
        kw = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        with tarfile.open(archive_path, "r|bz2") as tar:
            for member in tar:
                if member.name.endswith("model.onnx"):
                    continue
                tar.extract(member, path=root, **kw)

    # 清理压缩包
    if os.path.exists(archive_path):
        os.remove(archive_path)

    for d in [extracted_dir, os.path.join(root, sense_orig_name)]:
        unquantized = os.path.join(d, "model.onnx")
        if os.path.exists(unquantized):
            os.remove(unquantized)

    actual_dir = extracted_dir if os.path.exists(extracted_dir) else os.path.join(root, sense_orig_name)

    # 创建软链接 sensevoice
    symlink_path = os.path.join(root, "sensevoice")
    if os.path.islink(symlink_path) or os.path.exists(symlink_path):
        try:
            os.remove(symlink_path)
        except Exception:
            pass
    try:
        os.symlink(os.path.basename(actual_dir), symlink_path)
    except Exception:
        pass

    return symlink_path if os.path.exists(symlink_path) else actual_dir

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

def install_aquestalk_from_archive(archive_path: str, root: Optional[str] = None) -> List[str]:
    """从本地 zip 或 tar 压缩包（或单个 dll/so 文件）解压安装 AquesTalk 多声线库"""
    root = root or get_project_root()
    target_lib64 = os.path.join(root, "libs", "aquestalk", "lib64")
    target_base = os.path.join(root, "libs", "aquestalk")
    os.makedirs(target_lib64, exist_ok=True)
    os.makedirs(target_base, exist_ok=True)

    lower_path = archive_path.lower()
    if lower_path.endswith((".dll", ".so")):
        filename = os.path.basename(archive_path)
        shutil.copy2(archive_path, os.path.join(target_lib64, filename))
        shutil.copy2(archive_path, os.path.join(target_base, filename))
    elif lower_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member in zf.namelist():
                m_lower = member.lower()
                if "lib64/" in member and (m_lower.endswith(".so") or m_lower.endswith(".dll")):
                    parts = member.split("lib64/")
                    if len(parts) > 1 and parts[1]:
                        rel_path = parts[1]
                        out_file = os.path.join(target_lib64, rel_path)
                        os.makedirs(os.path.dirname(out_file), exist_ok=True)
                        with zf.open(member) as src, open(out_file, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                elif m_lower.endswith(".dll") or m_lower.endswith(".so"):
                    out_file = os.path.join(target_lib64, os.path.basename(member))
                    with zf.open(member) as src, open(out_file, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    out_base = os.path.join(target_base, os.path.basename(member))
                    with zf.open(member) as src, open(out_base, "wb") as dst:
                        shutil.copyfileobj(src, dst)
    elif lower_path.endswith((".tar.gz", ".tgz", ".tar.bz2")):
        with tarfile.open(archive_path, "r:*") as tf:
            for member in tf.getmembers():
                m_lower = member.name.lower()
                if "lib64/" in member.name and (m_lower.endswith(".so") or m_lower.endswith(".dll")):
                    parts = member.name.split("lib64/")
                    if len(parts) > 1 and parts[1]:
                        rel_path = parts[1]
                        out_file = os.path.join(target_lib64, rel_path)
                        os.makedirs(os.path.dirname(out_file), exist_ok=True)
                        f = tf.extractfile(member)
                        if f:
                            with open(out_file, "wb") as dst:
                                shutil.copyfileobj(f, dst)
                elif m_lower.endswith(".so") or m_lower.endswith(".dll"):
                    out_file = os.path.join(target_lib64, os.path.basename(member.name))
                    f = tf.extractfile(member)
                    if f:
                        with open(out_file, "wb") as dst:
                            shutil.copyfileobj(f, dst)

    from yukkuri.config import AppConfig
    cfg = AppConfig(project_root=root)
    return list(cfg.get_available_voices().keys())

def install_aquestalk_from_dir(src_dir: str, root: Optional[str] = None) -> List[str]:
    """从本地解压好的目录导入并配置 AquesTalk 多声线库"""
    root = root or get_project_root()
    target_lib64 = os.path.join(root, "libs", "aquestalk", "lib64")
    target_base = os.path.join(root, "libs", "aquestalk")
    os.makedirs(target_lib64, exist_ok=True)
    os.makedirs(target_base, exist_ok=True)

    # 寻找 lib64 目录
    lib64_dir = None
    if os.path.isdir(os.path.join(src_dir, "lib64")):
        lib64_dir = os.path.join(src_dir, "lib64")
    else:
        for child in os.listdir(src_dir):
            candidate = os.path.join(src_dir, child, "lib64")
            if os.path.isdir(candidate):
                lib64_dir = candidate
                break

    if not lib64_dir:
        lib64_dir = src_dir

    for item in os.listdir(lib64_dir):
        sub = os.path.join(lib64_dir, item)
        if os.path.isdir(sub):
            for libname in ["libAquesTalk.so", "AquesTalk.dll", "AquesTalk2.dll"]:
                candidate = os.path.join(sub, libname)
                if os.path.exists(candidate):
                    target_sub = os.path.join(target_lib64, item)
                    os.makedirs(target_sub, exist_ok=True)
                    shutil.copy2(candidate, os.path.join(target_sub, libname))
        elif item.lower().endswith((".so", ".dll")):
            shutil.copy2(sub, os.path.join(target_lib64, item))
            shutil.copy2(sub, os.path.join(target_base, item))

    from yukkuri.config import AppConfig
    cfg = AppConfig(project_root=root)
    return list(cfg.get_available_voices().keys())

def auto_detect_and_install_aquestalk(root: Optional[str] = None) -> Optional[List[str]]:
    """自动扫描用户环境中的 AquesTalk 安装包或已安装目录，并配置到项目 libs"""
    root = root or get_project_root()
    home = os.path.expanduser("~")

    # 1. 扫描已知目录
    dir_candidates = [
        os.path.join(root, "aqtk1_lnx"),
        os.path.join(home, "opt", "aqtk1_lnx_200"),
        os.path.join(home, "opt", "aqtk1_lnx_200", "aqtk1_lnx"),
        "/opt/aqtk1_lnx_200",
        "/opt/aqtk1_lnx_200/aqtk1_lnx",
        os.path.join(home, "Downloads", "aqtk1-win"),
        os.path.join(home, "Desktop", "aqtk1-win"),
    ]
    for d in dir_candidates:
        if os.path.isdir(d):
            voices = install_aquestalk_from_dir(d, root=root)
            if voices:
                return voices

    # 2. 扫描压缩包与动态库
    archive_candidates = [
        os.path.join(root, "aqtk1_lnx_200.zip"),
        os.path.join(home, "Downloads", "aqtk1_lnx_200.zip"),
        os.path.join(home, "下载", "aqtk1_lnx_200.zip"),
        os.path.join(home, "Downloads", "aqtk1-win.zip"),
        os.path.join(home, "Downloads", "AquesTalk.dll"),
        os.path.join(home, "Desktop", "AquesTalk.dll"),
    ]
    for a in archive_candidates:
        if os.path.isfile(a):
            voices = install_aquestalk_from_archive(a, root=root)
            if voices:
                return voices

    return None


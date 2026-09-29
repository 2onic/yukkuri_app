"""
PipeWire / PulseAudio 本地回放监听 (Loopback) 管理器
允许用户自身通过耳机/扬声器实时同步监听合成出的油库里语音
"""

import subprocess
import shutil
import time
import sys
from typing import Optional

class LoopbackManager:
    """管理 yukkuri_source 的本地回放监听进程"""

    def __init__(self, source_name: str = "yukkuri_source", target_sink: Optional[str] = None):
        self.source_name = source_name
        self.target_sink = target_sink
        self._proc: Optional[subprocess.Popen] = None
        self._pactl_module_id: Optional[str] = None

    def is_running(self) -> bool:
        """检查回放监听是否正在运行"""
        if self._proc is not None:
            if self._proc.poll() is None:
                return True
            self._proc = None
        return self._pactl_module_id is not None

    def start(self) -> bool:
        """启动回放监听"""
        if self.is_running():
            return True

        # 优先使用 PipeWire 原生低延迟工具 pw-loopback
        if shutil.which("pw-loopback"):
            cmd = ["pw-loopback", "--capture", self.source_name]
            if self.target_sink:
                cmd.extend(["--playback", self.target_sink])
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                time.sleep(0.08)
                if self._proc.poll() is None:
                    print(f"[回放监听] 已启动 pw-loopback (监听源: {self.source_name})")
                    return True
                else:
                    self._proc = None
            except Exception as e:
                print(f"[回放监听警告] 启动 pw-loopback 失败: {e}", file=sys.stderr)
                self._proc = None

        # 回退：使用 pactl 动态加载 module-loopback
        if shutil.which("pactl"):
            try:
                cmd = ["pactl", "load-module", "module-loopback", f"source={self.source_name}"]
                if self.target_sink:
                    cmd.append(f"sink={self.target_sink}")
                mod_id = subprocess.check_output(cmd, text=True).strip()
                self._pactl_module_id = mod_id
                print(f"[回放监听] 已通过 pactl 加载 module-loopback (模块 ID: {mod_id})")
                return True
            except Exception as e:
                print(f"[回放监听警告] 通过 pactl 加载 module-loopback 失败: {e}", file=sys.stderr)
                self._pactl_module_id = None

        return False

    def stop(self):
        """停止并清理回放监听"""
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

        if self._pactl_module_id is not None:
            try:
                subprocess.run(
                    ["pactl", "unload-module", self._pactl_module_id],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                pass
            self._pactl_module_id = None

        print("[回放监听] 已停止本地回放监听。")

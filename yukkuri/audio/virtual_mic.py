"""
PipeWire / PulseAudio 虚拟麦克风动态生命周期管理器
支持运行时零重启动态加载与退出时自动清理
"""

import subprocess
import shutil
from typing import List, Optional

class VirtualMicManager:
    """管理临时虚拟声卡节点 (yukkuri_sink -> yukkuri_source)"""

    def __init__(self, sink_name: str = "yukkuri_sink", source_name: str = "yukkuri_source"):
        self.sink_name = sink_name
        self.source_name = source_name
        self._loaded_modules: List[str] = []
        self._is_active = False

    @staticmethod
    def is_pactl_available() -> bool:
        return shutil.which("pactl") is not None

    def sink_exists(self) -> bool:
        """检查目标 Sink 是否已经在系统中注册"""
        if not self.is_pactl_available():
            return False
        try:
            res = subprocess.run(
                ["pactl", "list", "short", "sinks"],
                capture_output=True,
                text=True,
                check=True
            )
            return self.sink_name in res.stdout
        except Exception:
            return False

    def setup(self) -> bool:
        """若系统中尚未存在该虚拟节点，则动态创建"""
        if self.sink_exists():
            # 已经存在（例如用户配置了 99-yukkuri-mic.conf），无需重复创建
            self._is_active = True
            return True

        if not self.is_pactl_available():
            return False

        try:
            # 1. 动态加载 Null Sink
            sink_cmd = [
                "pactl", "load-module", "module-null-sink",
                f"sink_name={self.sink_name}",
                'sink_properties=device.description="Yukkuri_Virtual_Sink"'
            ]
            sink_mod = subprocess.check_output(sink_cmd, text=True).strip()
            self._loaded_modules.append(sink_mod)

            # 2. 动态加载 Remap Source 作为虚拟麦克风
            src_cmd = [
                "pactl", "load-module", "module-remap-source",
                f"source_name={self.source_name}",
                f"master={self.sink_name}.monitor",
                'source_properties=device.description="Yukkuri_Virtual_Mic"'
            ]
            src_mod = subprocess.check_output(src_cmd, text=True).strip()
            self._loaded_modules.append(src_mod)

            self._is_active = True
            print(f"[声卡管理] 已成功动态创建虚拟声卡: {self.sink_name} -> {self.source_name}")
            return True
        except Exception as e:
            print(f"[声卡管理] 动态创建虚拟声卡失败: {e}")
            self.cleanup()
            return False

    def cleanup(self):
        """退出时释放动态加载的模块，保持系统整洁"""
        if not self._loaded_modules:
            return

        for mod_id in reversed(self._loaded_modules):
            try:
                subprocess.run(["pactl", "unload-module", mod_id], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        print(f"[声卡管理] 已清理动态虚拟声卡节点。")
        self._loaded_modules.clear()
        self._is_active = False

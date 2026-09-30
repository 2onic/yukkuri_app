"""
虚拟麦克风动态生命周期管理器，支持平台物理隔离：
- Linux: 基于 PipeWire / PulseAudio (pactl load-module module-null-sink & module-remap-source)
- Windows: 基于 VB-Audio Virtual Cable (CABLE Input / CABLE Output) 驱动状态检测与免驱动引导
"""

import sys
import subprocess
import shutil
from typing import List, Optional


class LinuxPipeWireMicManager:
    """Linux 专有虚拟声卡管理：动态加载/卸载 yukkuri_sink 与 yukkuri_source"""

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


class WindowsVBCableManager:
    """Windows 专有虚拟声卡管理：检测 VB-Audio Virtual Cable (CABLE Input / Output) 状态"""

    def __init__(self):
        self._is_active = False

    @staticmethod
    def is_driver_installed() -> bool:
        """检查系统中是否已安装 VB-Audio Virtual Cable 驱动"""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            has_input = False
            has_output = False
            for d in devices:
                name = d.get("name", "").lower()
                if "cable input" in name and d.get("max_output_channels", 0) > 0:
                    has_input = True
                if "cable output" in name and d.get("max_input_channels", 0) > 0:
                    has_output = True
            return has_input and has_output
        except Exception:
            return False

    def setup(self) -> bool:
        if self.is_driver_installed():
            self._is_active = True
            print("[声卡管理] 已检测到 VB-Audio Virtual Cable 驱动就绪。")
            return True
        else:
            print("[声卡管理 提示] 未检测到 VB-Audio Virtual Cable！", file=sys.stderr)
            print("  请访问 https://vb-audio.com/Cable/ 下载并安装 VB-CABLE 虚拟声卡驱动。", file=sys.stderr)
            print("  安装后请将游戏/开黑软件的麦克风设置为 [CABLE Output]。", file=sys.stderr)
            return False

    def cleanup(self):
        self._is_active = False


class VirtualMicManager:
    """
    通用虚拟声卡管理器门面 (Facade)：
    根据运行环境自动分派对应平台的虚拟声卡驱动管理实现。
    """

    def __init__(self, sink_name: str = "yukkuri_sink", source_name: str = "yukkuri_source"):
        if sys.platform == "win32":
            self._impl = WindowsVBCableManager()
        else:
            self._impl = LinuxPipeWireMicManager(sink_name=sink_name, source_name=source_name)

    @property
    def impl(self):
        return self._impl

    def setup(self) -> bool:
        return self._impl.setup()

    def cleanup(self):
        self._impl.cleanup()

    def sink_exists(self) -> bool:
        if hasattr(self._impl, "sink_exists"):
            return self._impl.sink_exists()
        return True

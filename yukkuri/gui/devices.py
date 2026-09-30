"""
音频设备检测与格式化工具
"""

from typing import List, Tuple, Optional
import sounddevice as sd

def get_input_devices() -> List[Tuple[Optional[int], str]]:
    """
    获取系统中所有可用的麦克风输入设备
    返回: [(device_id, display_label), ...]
    """
    device_list: List[Tuple[Optional[int], str]] = [(None, "系统默认 (Default)")]
    try:
        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                name = dev.get("name", f"Device {idx}")
                # 截断过长设备名保持 UI 美观
                short_name = name[:36] + "..." if len(name) > 36 else name
                device_list.append((idx, f"[{idx}] {short_name}"))
    except Exception as e:
        print(f"[设备探测异常]: {e}")
    return device_list

def find_default_real_input_device() -> Optional[int]:
    """
    智能探测并返回一个首选的物理硬件麦克风设备 ID。
    自动剔除带有 virtual, cable, monitor, yukkuri, null 等字样的虚拟通道，
    优先保障拾音指向用户电脑的真实物理麦克风。
    若未找到合适的物理麦克风，则返回系统默认设备或 None。
    """
    try:
        devices = sd.query_devices()
        default_in = sd.default.device[0]

        candidates = []
        for idx, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) <= 0:
                continue

            name = dev.get("name", "")
            lower = name.lower()
            is_virtual = any(k in lower for k in [
                "cable", "virtual", "yukkuri", "monitor", "null", "loopback", "remap"
            ])
            if is_virtual:
                continue

            priority = 0
            if any(k in lower for k in ["mic", "microphone", "麦克风", "headset", "realtek", "conexant", "usb", "hifi"]):
                priority += 10
            if idx == default_in:
                priority += 5

            candidates.append((priority, idx))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

        return default_in if default_in is not None and default_in >= 0 else None
    except Exception as e:
        print(f"[首选物理麦克风探测异常]: {e}")
        return None

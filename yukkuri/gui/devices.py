"""
音频设备检测与格式化工具
"""

from typing import List, Tuple, Optional
import sounddevice as sd

def is_virtual_device(name: str) -> bool:
    """判断是否为虚拟声卡或监视回环节点"""
    lower = name.lower()
    return any(k in lower for k in [
        "cable", "virtual", "yukkuri", "monitor", "null", "loopback", "remap"
    ])

def get_input_devices() -> List[Tuple[Optional[int], str]]:
    """
    获取系统中所有可用的麦克风输入设备，并标记虚拟声卡
    返回: [(device_id, display_label), ...]
    """
    device_list: List[Tuple[Optional[int], str]] = [(None, "系统默认 (Default)")]
    try:
        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                name = dev.get("name", f"Device {idx}")
                is_virt = is_virtual_device(name)
                tag = " [虚拟声卡]" if is_virt else ""
                # 截断过长设备名保持 UI 美观
                max_len = 30 if is_virt else 36
                short_name = name[:max_len] + "..." if len(name) > max_len else name
                device_list.append((idx, f"[{idx}] {short_name}{tag}"))
    except Exception as e:
        print(f"[设备探测异常]: {e}")
    return device_list


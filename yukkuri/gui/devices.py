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

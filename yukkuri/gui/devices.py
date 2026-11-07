"""
音频设备检测与格式化工具
支持多平台音频设备枚举、虚拟声卡识别、WDM-KS 不兼容驱动过滤以及 Windows WASAPI 主机接口去重
"""

import sys
from typing import List, Tuple, Optional, Set
import sounddevice as sd

def is_virtual_device(name: str) -> bool:
    """判断是否为虚拟声卡或监视回环节点"""
    lower = name.lower()
    return any(k in lower for k in [
        "cable", "virtual", "yukkuri", "monitor", "null", "loopback", "remap"
    ])

def _get_hostapis_info() -> Tuple[Optional[int], Set[int]]:
    """探测 Windows HostAPI 分类，识别 WASAPI 索引并收集需屏蔽的 WDM-KS 索引"""
    if sys.platform != "win32":
        return None, set()
    wasapi_idx = None
    wdmks_indices: Set[int] = set()
    try:
        hostapis = sd.query_hostapis()
        for idx, api in enumerate(hostapis):
            name = api.get("name", "").lower()
            if "wasapi" in name:
                wasapi_idx = idx
            elif "wdm-ks" in name or "wdmks" in name:
                wdmks_indices.add(idx)
    except Exception:
        pass
    return wasapi_idx, wdmks_indices

def get_input_devices() -> List[Tuple[Optional[int], str]]:
    """
    获取系统中所有可用的麦克风输入设备，并标记虚拟声卡。
    在 Windows 下严格排除不可靠的 WDM-KS 底层内核流设备，并优先过滤 WASAPI HostAPI 避免设备重复及驱动冲突。
    返回: [(device_id, display_label), ...]
    """
    device_list: List[Tuple[Optional[int], str]] = [(None, "系统默认 (Default)")]
    try:
        devices = sd.query_devices()
        wasapi_idx, wdmks_indices = _get_hostapis_info()

        use_wasapi = False
        if wasapi_idx is not None:
            # 只有当确实检测到属于 WASAPI 的输入设备时才启用过滤，防止特殊无驱动环境被过滤为空
            if any(dev.get("max_input_channels", 0) > 0 and dev.get("hostapi") == wasapi_idx for dev in devices):
                use_wasapi = True

        for idx, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                dev_hostapi = dev.get("hostapi")
                # 严格过滤 Windows WDM-KS 驱动接口，彻底杜绝 WdmSyncIoctl DeviceIoControl 异常
                if dev_hostapi is not None and dev_hostapi in wdmks_indices:
                    continue
                if use_wasapi and dev_hostapi != wasapi_idx:
                    continue

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

def get_output_devices() -> List[Tuple[Optional[int], str]]:
    """
    获取系统中所有可用的音频输出设备 (扬声器/耳机/虚拟播放通道)。
    在 Windows 下严格过滤 WDM-KS 并优先采用 WASAPI HostAPI。
    返回: [(device_id, display_label), ...]
    """
    device_list: List[Tuple[Optional[int], str]] = [(None, "系统默认 (Default)")]
    try:
        devices = sd.query_devices()
        wasapi_idx, wdmks_indices = _get_hostapis_info()

        use_wasapi = False
        if wasapi_idx is not None:
            if any(dev.get("max_output_channels", 0) > 0 and dev.get("hostapi") == wasapi_idx for dev in devices):
                use_wasapi = True

        for idx, dev in enumerate(devices):
            if dev.get("max_output_channels", 0) > 0:
                dev_hostapi = dev.get("hostapi")
                if dev_hostapi is not None and dev_hostapi in wdmks_indices:
                    continue
                if use_wasapi and dev_hostapi != wasapi_idx:
                    continue

                name = dev.get("name", f"Output {idx}")
                is_virt = is_virtual_device(name)
                tag = " [虚拟声卡]" if is_virt else ""
                max_len = 30 if is_virt else 36
                short_name = name[:max_len] + "..." if len(name) > max_len else name
                device_list.append((idx, f"[{idx}] {short_name}{tag}"))
    except Exception as e:
        print(f"[输出设备探测异常]: {e}")
    return device_list

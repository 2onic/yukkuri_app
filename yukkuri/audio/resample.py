"""
音频重采样工具，具备抗混叠低通滤波 (Anti-Aliasing Filter)。
兼容 SciPy (resample_poly) 与纯 NumPy 实现，消除采样率转换时的频谱混叠与高频噪声。
"""

import math
from typing import Optional
import numpy as np

try:
    from scipy.signal import resample_poly
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def _design_lowpass_fir(cutoff: float, sample_rate: float, num_taps: int = 41) -> np.ndarray:
    """设计窗函数法 (Hamming) 低通 FIR 滤波器核"""
    if num_taps % 2 == 0:
        num_taps += 1
    m = (num_taps - 1) / 2
    n = np.arange(num_taps)
    # 归一化截止频率
    omega = 2.0 * cutoff / sample_rate
    # sinc 函数
    h = np.sinc(omega * (n - m)) * omega
    # 加 Hamming 窗
    window = np.hamming(num_taps)
    h *= window
    # 归一化增益
    h_sum = np.sum(h)
    if h_sum != 0:
        h /= h_sum
    return h


def _convolve_with_padding(audio_1d: np.ndarray, fir: np.ndarray) -> np.ndarray:
    """对一维音频进行具备边界边缘填充 (edge padding) 的卷积，消除滤波器边缘瞬态畸变"""
    pad_len = len(fir)
    if len(audio_1d) <= pad_len:
        # 音频过短时直接卷积
        return np.convolve(audio_1d, fir, mode='same')
    padded = np.pad(audio_1d, pad_len, mode='edge')
    filtered = np.convolve(padded, fir, mode='same')
    return filtered[pad_len:-pad_len]


def resample_audio(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """
    高质量音频重采样。
    :param audio: 1D 或 2D numpy 数组音频数据
    :param orig_sr: 原始采样率 (Hz)
    :param target_sr: 目标采样率 (Hz)
    :return: 重采样后的音频数据 (保持原有 dtype)
    """
    if orig_sr == target_sr or len(audio) == 0:
        return audio

    orig_dtype = audio.dtype
    is_int16 = np.issubdtype(orig_dtype, np.integer)

    # 若安装了 scipy，优先使用其多相多速率重采样
    if _HAS_SCIPY:
        g = math.gcd(int(orig_sr), int(target_sr))
        up = target_sr // g
        down = orig_sr // g
        float_data = audio.astype(np.float32)
        resampled = resample_poly(float_data, up, down, axis=0)
        if is_int16:
            resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
        else:
            resampled = resampled.astype(orig_dtype)
        return resampled

    # 纯 NumPy 具备抗混叠滤波的重采样实现
    float_audio = audio.astype(np.float32)
    axis_len = len(float_audio)
    target_len = int(round(axis_len * target_sr / orig_sr))
    if target_len <= 0:
        return np.zeros((0,) + float_audio.shape[1:], dtype=orig_dtype)

    # 1. 降采样 (Downsampling: orig_sr > target_sr)
    # 奈奎斯特频率为 target_sr / 2，必须在降采样前应用低通抗混叠滤波，避免高于奈奎斯特频率的高频折叠进带内
    if orig_sr > target_sr:
        nyquist = target_sr / 2.0
        cutoff = nyquist * 0.85
        fir = _design_lowpass_fir(cutoff, orig_sr, num_taps=41)

        if float_audio.ndim == 1:
            filtered = _convolve_with_padding(float_audio, fir)
        else:
            channels = float_audio.shape[1]
            filtered = np.zeros_like(float_audio)
            for ch in range(channels):
                filtered[:, ch] = _convolve_with_padding(float_audio[:, ch], fir)

        indices = np.linspace(0, axis_len - 1, target_len)
        if float_audio.ndim == 1:
            resampled = np.interp(indices, np.arange(axis_len), filtered)
        else:
            resampled = np.zeros((target_len, float_audio.shape[1]), dtype=np.float32)
            for ch in range(float_audio.shape[1]):
                resampled[:, ch] = np.interp(indices, np.arange(axis_len), filtered[:, ch])

    # 2. 升采样 (Upsampling: orig_sr < target_sr)
    # 插值后施加低通滤波滤除高频镜像成分 (Anti-Imaging)
    else:
        indices = np.linspace(0, axis_len - 1, target_len)
        if float_audio.ndim == 1:
            interp_audio = np.interp(indices, np.arange(axis_len), float_audio)
        else:
            interp_audio = np.zeros((target_len, float_audio.shape[1]), dtype=np.float32)
            for ch in range(float_audio.shape[1]):
                interp_audio[:, ch] = np.interp(indices, np.arange(axis_len), float_audio[:, ch])

        nyquist = orig_sr / 2.0
        cutoff = nyquist * 0.85
        fir = _design_lowpass_fir(cutoff, target_sr, num_taps=41)

        if interp_audio.ndim == 1:
            resampled = _convolve_with_padding(interp_audio, fir)
        else:
            resampled = np.zeros_like(interp_audio)
            for ch in range(interp_audio.shape[1]):
                resampled[:, ch] = _convolve_with_padding(interp_audio[:, ch], fir)

    if is_int16:
        return np.clip(resampled, -32768, 32767).astype(np.int16)
    return resampled.astype(orig_dtype)

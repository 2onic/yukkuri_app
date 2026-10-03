"""
音频推流播放器模块，支持平台物理隔离：
- Linux: 严格使用原生 PipeWire (pw-play) 或 PulseAudio (paplay)，0 丢包推流至 yukkuri_sink，并具备虚拟节点就绪检查防止物理扬声器外放
- Windows: 使用 WASAPI/sounddevice，长连接 OutputStream 保持低延迟避免爆音，自动抗混叠重采样并升混为立体声推流至 VB-CABLE Input，支持双路耳机监听
"""

import sys
import abc
import queue
import threading
import subprocess
import shutil
import io
import wave
from typing import Optional, Tuple
import numpy as np
import sounddevice as sd

from yukkuri.audio.resample import resample_audio


def apply_wav_gain(wav_data: bytes, gain: float) -> bytes:
    """
    对 WAV 二进制音频数据应用软件输出增益调节 (支持防溢出饱和截断)。
    若增益为 1.0 或数据为空则直接返回，保持零额外开销。
    """
    if abs(gain - 1.0) < 1e-4 or not wav_data:
        return wav_data

    gain = max(0.0, float(gain))
    try:
        with wave.open(io.BytesIO(wav_data), "rb") as wf:
            params = wf.getparams()
            frames = wf.readframes(wf.getnframes())
            if wf.getsampwidth() == 2:
                samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
                samples = samples * gain
                samples = np.clip(samples, -32768, 32767).astype(np.int16)
                out_io = io.BytesIO()
                with wave.open(out_io, "wb") as out_wf:
                    out_wf.setparams(params)
                    out_wf.writeframes(samples.tobytes())
                return out_io.getvalue()
    except Exception:
        if len(wav_data) > 44:
            header = wav_data[:44]
            raw = wav_data[44:]
            if len(raw) % 2 != 0:
                raw = raw[:-1]
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            samples = np.clip(samples * gain, -32768, 32767).astype(np.int16)
            return header + samples.tobytes()

    return wav_data


class BaseAudioPlayer(abc.ABC):
    """音频播放器抽象基类"""

    @abc.abstractmethod
    def play(self, wav_data: bytes, desc: str = ""):
        """异步投递一段 WAV 音频数据入队播放"""
        pass

    @abc.abstractmethod
    def stop(self):
        """停止播放队列并释放资源"""
        pass

    def set_monitor(self, enable: bool, device_id: Optional[int] = None):
        """设置耳机监听 (在非 PipeWire 模式下生效)"""
        pass

    def set_gain(self, gain: float):
        """设置软件输出音量增益"""
        pass


class LinuxPipeWirePlayer(BaseAudioPlayer):
    """
    Linux 专有推流播放器：
    严格调用系统原生 pw-play --target {target_sink} 或 paplay，严禁经由 sounddevice，
    以保证推流直接注入 PipeWire 虚拟声卡节点图。
    """

    def __init__(self, target_sink: str = "yukkuri_sink", gain: float = 1.0):
        self.target_sink = target_sink
        self.gain = max(0.0, float(gain))
        self.queue: queue.Queue = queue.Queue()
        self.running = True
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def set_gain(self, gain: float):
        """动态设置输出增益"""
        self.gain = max(0.0, float(gain))

    def play(self, wav_data: bytes, desc: str = ""):
        if wav_data:
            if abs(self.gain - 1.0) >= 1e-4:
                wav_data = apply_wav_gain(wav_data, self.gain)
            self.queue.put((wav_data, desc))

    def _is_sink_available(self) -> bool:
        """检查目标虚拟声卡是否存在于系统中"""
        if not self.target_sink:
            return True
        if shutil.which("pactl"):
            try:
                res = subprocess.run(
                    ["pactl", "list", "short", "sinks"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                return self.target_sink in res.stdout
            except Exception:
                pass
        return True

    def _worker(self):
        has_pw_play = shutil.which("pw-play") is not None

        while self.running:
            try:
                item = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue

            wav_data, desc = item
            try:
                # 检查虚拟声卡节点是否存在，避免向默认物理扬声器漏音
                if self.target_sink and not self._is_sink_available():
                    print(f"[播放警告] 目标虚拟声卡 '{self.target_sink}' 不存在或未就绪，已阻止向系统默认物理扬声器推流以防止隐私泄露。", file=sys.stderr)
                    continue

                if has_pw_play:
                    cmd = ["pw-play"]
                    if self.target_sink:
                        cmd.extend(["--target", self.target_sink])
                    cmd.append("-")

                    proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE
                    )
                    _, stderr = proc.communicate(input=wav_data)
                    if proc.returncode != 0 and stderr:
                        err_msg = stderr.decode(errors='ignore').strip()
                        print(f"[播放警告] pw-play 提示: {err_msg}", file=sys.stderr)
                else:
                    cmd = ["paplay"]
                    if self.target_sink:
                        cmd.extend(["-d", self.target_sink])
                    proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE
                    )
                    proc.communicate(input=wav_data)

            except Exception as e:
                print(f"[播放异常]: {e}", file=sys.stderr)
            finally:
                self.queue.task_done()

    def stop(self):
        self.running = False
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)


class WindowsWASAPIPlayer(BaseAudioPlayer):
    """
    Windows 专有推流播放器：
    利用 sounddevice 异步向虚拟声卡 (如 VB-CABLE Input) 推流。
    针对 Windows WASAPI 驱动特性：
    - 采用长连接保持 OutputStream，避免每句频繁启闭驱动产生爆音与性能抖动
    - 自动抗混叠重采样至声卡采样率并升混为立体声 (2ch)
    - 优先匹配 WASAPI HostAPI 设备，并具备默认扬声器防外放保护
    - 支持向用户的物理耳机/音箱设备进行双路并行推流监听
    """

    def __init__(
        self,
        output_device: Optional[int] = None,
        monitor_device: Optional[int] = None,
        enable_monitor: bool = False,
        allow_default_speaker: bool = False,
        gain: float = 1.0
    ):
        self.output_device = output_device
        self.monitor_device = monitor_device
        self.enable_monitor = enable_monitor
        self.allow_default_speaker = allow_default_speaker
        self.gain = max(0.0, float(gain))
        self.queue: queue.Queue = queue.Queue()
        self.running = True

        self._stream_out: Optional[sd.OutputStream] = None
        self._stream_out_params: Optional[Tuple[Optional[int], int, int]] = None
        self._stream_mon: Optional[sd.OutputStream] = None
        self._stream_mon_params: Optional[Tuple[Optional[int], int, int]] = None
        self._stream_lock = threading.Lock()

        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def set_gain(self, gain: float):
        """动态设置输出增益"""
        self.gain = max(0.0, float(gain))

    def set_monitor(self, enable: bool, device_id: Optional[int] = None):
        """动态开启/关闭本地耳机回放监听"""
        with self._stream_lock:
            self.enable_monitor = enable
            if device_id is not None:
                self.monitor_device = device_id
            if not enable and self._stream_mon is not None:
                try:
                    self._stream_mon.stop()
                    self._stream_mon.close()
                except Exception:
                    pass
                self._stream_mon = None
                self._stream_mon_params = None

    def set_output_device(self, device_id: Optional[int]):
        """动态设置输出目标设备"""
        with self._stream_lock:
            if self.output_device != device_id:
                self.output_device = device_id
                if self._stream_out is not None:
                    try:
                        self._stream_out.stop()
                        self._stream_out.close()
                    except Exception:
                        pass
                    self._stream_out = None
                    self._stream_out_params = None

    @staticmethod
    def find_default_cable_input() -> Optional[int]:
        """智能寻找 VB-CABLE Input 设备的索引 ID (优先匹配 WASAPI HostAPI)"""
        try:
            devices = sd.query_devices()
            wasapi_api_idx = None
            try:
                hostapis = sd.query_hostapis()
                for idx, api in enumerate(hostapis):
                    if "wasapi" in api.get("name", "").lower():
                        wasapi_api_idx = idx
                        break
            except Exception:
                pass

            best_match = None
            for idx, dev in enumerate(devices):
                if dev.get("max_output_channels", 0) > 0:
                    name = dev.get("name", "").lower()
                    if "cable input" in name or "vb-audio point" in name:
                        if wasapi_api_idx is not None and dev.get("hostapi") == wasapi_api_idx:
                            return idx
                        if best_match is None:
                            best_match = idx
            return best_match
        except Exception:
            pass
        return None

    @staticmethod
    def _prepare_audio_for_device(
        mono_int16: np.ndarray,
        src_sample_rate: int,
        device_id: Optional[int]
    ) -> Tuple[np.ndarray, int, int]:
        """
        为指定输出设备适配采样率与声道数 (自动抗混叠重采样并升混为双声道/立体声，兼容 Windows WASAPI/VB-CABLE)
        返回: (formatted_audio_2d_or_1d, target_sample_rate, target_channels)
        """
        target_sr = src_sample_rate
        target_ch = 1

        default_sr = 48000
        max_ch = 2
        try:
            dev_info = sd.query_devices(device_id, 'output')
            default_sr = int(dev_info.get('default_samplerate', 48000))
            max_ch = int(dev_info.get('max_output_channels', 2))
        except Exception:
            pass

        # 检查设备是否原生支持原始格式 (如 8000Hz 1ch)
        direct_supported = False
        try:
            sd.check_output_settings(device=device_id, samplerate=src_sample_rate, channels=1)
            direct_supported = True
            target_sr = src_sample_rate
            target_ch = 1
        except Exception:
            pass

        if not direct_supported:
            candidate_srs = [default_sr, 48000, 44100, 32000, 16000]
            candidate_srs = list(dict.fromkeys(candidate_srs))
            candidate_chs = [min(2, max_ch), 1] if max_ch >= 2 else [1]

            matched = False
            for test_sr in candidate_srs:
                for test_ch in candidate_chs:
                    try:
                        sd.check_output_settings(device=device_id, samplerate=test_sr, channels=test_ch)
                        target_sr = test_sr
                        target_ch = test_ch
                        matched = True
                        break
                    except Exception:
                        continue
                if matched:
                    break

            if not matched:
                target_sr = default_sr
                target_ch = min(2, max(1, max_ch))

        # 1. 采样率重采样 (具备抗混叠低通滤波)
        if target_sr != src_sample_rate and len(mono_int16) > 0:
            resampled = resample_audio(mono_int16, src_sample_rate, target_sr).astype(np.int16)
        else:
            resampled = mono_int16.astype(np.int16)

        # 2. 声道转换 (单声道 -> 复制为双声道或对应声道数，防止 WASAPI 报错)
        if target_ch == 2:
            out_data = np.column_stack((resampled, resampled))
        elif target_ch > 2:
            out_data = np.tile(resampled[:, None], (1, target_ch))
        else:
            out_data = resampled

        return out_data, target_sr, target_ch

    def play(self, wav_data: bytes, desc: str = ""):
        if wav_data:
            if abs(self.gain - 1.0) >= 1e-4:
                wav_data = apply_wav_gain(wav_data, self.gain)
            self.queue.put((wav_data, desc))

    def _get_or_create_stream(
        self,
        stream_type: str,
        device_id: Optional[int],
        sample_rate: int,
        channels: int
    ) -> Optional[sd.OutputStream]:
        """获取长连接流或复用已有流，避免每句语音频繁启闭驱动产生爆音与开销"""
        desired_params = (device_id, sample_rate, channels)
        with self._stream_lock:
            cur_stream = self._stream_out if stream_type == "main" else self._stream_mon
            cur_params = self._stream_out_params if stream_type == "main" else self._stream_mon_params

            if cur_stream is not None and cur_params == desired_params and cur_stream.active:
                return cur_stream

            if cur_stream is not None:
                try:
                    cur_stream.stop()
                    cur_stream.close()
                except Exception:
                    pass

            try:
                new_stream = sd.OutputStream(
                    samplerate=sample_rate,
                    channels=channels,
                    dtype='int16',
                    device=device_id
                )
                new_stream.start()
                if stream_type == "main":
                    self._stream_out = new_stream
                    self._stream_out_params = desired_params
                else:
                    self._stream_mon = new_stream
                    self._stream_mon_params = desired_params
                return new_stream
            except Exception as e:
                desc = "主推流" if stream_type == "main" else "耳机监听"
                print(f"[sounddevice {desc}启动失败 (设备: {device_id})]: {e}", file=sys.stderr)
                if stream_type == "main":
                    self._stream_out = None
                    self._stream_out_params = None
                else:
                    self._stream_mon = None
                    self._stream_mon_params = None
                return None

    def _play_streams(self, wav_data: bytes):
        try:
            with wave.open(io.BytesIO(wav_data)) as wf:
                sample_rate = wf.getframerate()
                n_channels = wf.getnchannels()
                frames = wf.readframes(wf.getnframes())
                audio_array = np.frombuffer(frames, dtype=np.int16)
                if n_channels > 1:
                    audio_array = audio_array.reshape(-1, n_channels)[:, 0]
        except Exception:
            if len(wav_data) > 44:
                raw_bytes = wav_data[44:]
                if len(raw_bytes) % 2 != 0:
                    raw_bytes = raw_bytes[:-1]
                audio_array = np.frombuffer(raw_bytes, dtype=np.int16)
                sample_rate = 8000
            else:
                return

        out_dev = self.output_device
        if out_dev is None:
            out_dev = self.find_default_cable_input()

        # 防外放隐私保护：如果既未显式指定设备，也未找到 VB-CABLE，且未显式允许外放，则拦截
        if out_dev is None and not self.allow_default_speaker:
            print("[播放警告] 未找到虚拟音频输出设备 (VB-CABLE)，已拦截静默外放以防止物理扬声器隐私泄露。请先安装 VB-CABLE 或在配置中指定输出设备。", file=sys.stderr)
            return

        mon_dev = self.monitor_device
        should_monitor = self.enable_monitor and (mon_dev is not None or out_dev is not None)

        try:
            data_out, sr_out, ch_out = self._prepare_audio_for_device(audio_array, sample_rate, out_dev)
            s1 = self._get_or_create_stream("main", out_dev, sr_out, ch_out)

            data_mon = None
            s2 = None
            if should_monitor:
                data_mon, sr_mon, ch_mon = self._prepare_audio_for_device(audio_array, sample_rate, mon_dev)
                s2 = self._get_or_create_stream("monitor", mon_dev, sr_mon, ch_mon)

            if s1 or s2:
                chunk_size = 512
                len_out = len(data_out) if s1 else 0
                len_mon = len(data_mon) if s2 else 0
                max_len = max(len_out, len_mon)
                for i in range(0, max_len, chunk_size):
                    if not self.running:
                        break
                    if s1 and i < len_out:
                        chunk1 = data_out[i:i + chunk_size]
                        try:
                            s1.write(chunk1)
                        except Exception:
                            with self._stream_lock:
                                self._stream_out = None
                                self._stream_out_params = None
                            break
                    if s2 and i < len_mon:
                        chunk2 = data_mon[i:i + chunk_size]
                        try:
                            s2.write(chunk2)
                        except Exception:
                            with self._stream_lock:
                                self._stream_mon = None
                                self._stream_mon_params = None
                            break

        except Exception as e:
            print(f"[sounddevice 推流异常]: {e}", file=sys.stderr)

    def _worker(self):
        while self.running:
            try:
                item = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue

            wav_data, desc = item
            try:
                self._play_streams(wav_data)
            except Exception as e:
                print(f"[Windows 播放线程异常]: {e}", file=sys.stderr)
            finally:
                self.queue.task_done()

    def stop(self):
        self.running = False
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
        with self._stream_lock:
            for s in [self._stream_out, self._stream_mon]:
                if s is not None:
                    try:
                        s.stop()
                        s.close()
                    except Exception:
                        pass
            self._stream_out = None
            self._stream_out_params = None
            self._stream_mon = None
            self._stream_mon_params = None


class AudioPlayer(BaseAudioPlayer):
    """
    通用音频播放器门面 (Facade)：
    根据操作系统环境自动实例化对应平台的隔离实现：
    - Windows: 实例化 WindowsWASAPIPlayer (长连接对接 VB-CABLE Input 与耳机监听)
    - Linux: 严格实例化 LinuxPipeWirePlayer (走原生 pw-play --target yukkuri_sink)
    """

    def __init__(
        self,
        target_sink: str = "yukkuri_sink",
        output_device: Optional[int] = None,
        monitor_device: Optional[int] = None,
        enable_monitor: bool = False,
        backend: Optional[str] = None,
        allow_default_speaker: bool = False,
        gain: float = 1.0
    ):
        if backend == "wasapi" or (backend is None and sys.platform == "win32"):
            self._impl: BaseAudioPlayer = WindowsWASAPIPlayer(
                output_device=output_device,
                monitor_device=monitor_device,
                enable_monitor=enable_monitor,
                allow_default_speaker=allow_default_speaker,
                gain=gain
            )
        else:
            self._impl = LinuxPipeWirePlayer(
                target_sink=target_sink,
                gain=gain
            )

    @property
    def impl(self) -> BaseAudioPlayer:
        return self._impl

    def play(self, wav_data: bytes, desc: str = ""):
        self._impl.play(wav_data, desc)

    def stop(self):
        self._impl.stop()

    def set_monitor(self, enable: bool, device_id: Optional[int] = None):
        self._impl.set_monitor(enable, device_id)

    def set_gain(self, gain: float):
        self._impl.set_gain(gain)

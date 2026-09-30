"""
音频推流播放器模块，支持平台物理隔离：
- Linux: 严格使用原生 PipeWire (pw-play) 或 PulseAudio (paplay)，0 丢包推流至 yukkuri_sink
- Windows: 使用 WASAPI/sounddevice，自动重采样至声卡采样率并升混为立体声推流至 VB-CABLE Input，支持双路耳机监听
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


class LinuxPipeWirePlayer(BaseAudioPlayer):
    """
    Linux 专有推流播放器：
    严格调用系统原生 pw-play --target {target_sink} 或 paplay，严禁经由 sounddevice，
    以保证推流直接注入 PipeWire 虚拟声卡节点图。
    """

    def __init__(self, target_sink: str = "yukkuri_sink"):
        self.target_sink = target_sink
        self.queue: queue.Queue = queue.Queue()
        self.running = True
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def play(self, wav_data: bytes, desc: str = ""):
        if wav_data:
            self.queue.put((wav_data, desc))

    def _worker(self):
        has_pw_play = shutil.which("pw-play") is not None

        while self.running:
            try:
                item = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue

            wav_data, desc = item
            try:
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
    针对 Windows WASAPI 驱动特性，自动将 AquesTalk 的 8000Hz 1ch 采样数据
    自适应重采样为目标设备的推荐采样率（如 48000Hz/44100Hz）并升混为立体声 (2ch)，
    并支持向用户的物理耳机/音箱设备进行双路并行推流监听。
    """

    def __init__(
        self,
        output_device: Optional[int] = None,
        monitor_device: Optional[int] = None,
        enable_monitor: bool = False
    ):
        self.output_device = output_device
        self.monitor_device = monitor_device
        self.enable_monitor = enable_monitor
        self.queue: queue.Queue = queue.Queue()
        self.running = True
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def set_monitor(self, enable: bool, device_id: Optional[int] = None):
        """动态开启/关闭本地耳机回放监听"""
        self.enable_monitor = enable
        if device_id is not None:
            self.monitor_device = device_id

    def set_output_device(self, device_id: Optional[int]):
        """动态设置输出目标设备"""
        self.output_device = device_id

    @staticmethod
    def find_default_cable_input() -> Optional[int]:
        """智能寻找 VB-CABLE Input 设备的索引 ID"""
        try:
            devices = sd.query_devices()
            for idx, dev in enumerate(devices):
                if dev.get("max_output_channels", 0) > 0:
                    name = dev.get("name", "").lower()
                    if "cable input" in name or "vb-audio point" in name:
                        return idx
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
        为指定输出设备适配采样率与声道数 (自动将 8000Hz 单声道重采样并升混为双声道/立体声，兼容 Windows WASAPI/VB-CABLE)
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

        # 1. 采样率重采样
        if target_sr != src_sample_rate and len(mono_int16) > 0:
            ratio = target_sr / src_sample_rate
            num_samples = int(round(len(mono_int16) * ratio))
            if num_samples > 0:
                resampled = np.interp(
                    np.linspace(0, len(mono_int16), num_samples, endpoint=False),
                    np.arange(len(mono_int16)),
                    mono_int16
                ).astype(np.int16)
            else:
                resampled = np.empty(0, dtype=np.int16)
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
            self.queue.put((wav_data, desc))

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
                audio_array = np.frombuffer(wav_data[44:], dtype=np.int16)
                sample_rate = 8000
            else:
                return

        out_dev = self.output_device
        if out_dev is None:
            out_dev = self.find_default_cable_input()

        mon_dev = self.monitor_device
        should_monitor = self.enable_monitor and (mon_dev is not None or out_dev is not None)

        try:
            data_out, sr_out, ch_out = self._prepare_audio_for_device(audio_array, sample_rate, out_dev)

            s1 = None
            s2 = None
            try:
                s1 = sd.OutputStream(samplerate=sr_out, channels=ch_out, dtype='int16', device=out_dev)
                s1.start()
            except Exception as e:
                print(f"[sounddevice 主输出启动失败 (设备: {out_dev})]: {e}", file=sys.stderr)

            data_mon = None
            if should_monitor:
                data_mon, sr_mon, ch_mon = self._prepare_audio_for_device(audio_array, sample_rate, mon_dev)
                try:
                    s2 = sd.OutputStream(samplerate=sr_mon, channels=ch_mon, dtype='int16', device=mon_dev)
                    s2.start()
                except Exception as e:
                    print(f"[sounddevice 耳机监听启动失败 (设备: {mon_dev})]: {e}", file=sys.stderr)

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
                            pass
                    if s2 and i < len_mon:
                        chunk2 = data_mon[i:i + chunk_size]
                        try:
                            s2.write(chunk2)
                        except Exception:
                            pass
            if s1:
                s1.stop()
                s1.close()
            if s2:
                s2.stop()
                s2.close()
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


class AudioPlayer(BaseAudioPlayer):
    """
    通用音频播放器门面 (Facade)：
    根据操作系统环境自动实例化对应平台的隔离实现：
    - Windows: 实例化 WindowsWASAPIPlayer (自动对接 VB-CABLE Input 与耳机监听)
    - Linux: 严格实例化 LinuxPipeWirePlayer (走原生 pw-play --target yukkuri_sink)
    """

    def __init__(
        self,
        target_sink: str = "yukkuri_sink",
        output_device: Optional[int] = None,
        monitor_device: Optional[int] = None,
        enable_monitor: bool = False,
        backend: Optional[str] = None
    ):
        if backend == "wasapi" or (backend is None and sys.platform == "win32"):
            self._impl: BaseAudioPlayer = WindowsWASAPIPlayer(
                output_device=output_device,
                monitor_device=monitor_device,
                enable_monitor=enable_monitor
            )
        else:
            self._impl = LinuxPipeWirePlayer(
                target_sink=target_sink
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

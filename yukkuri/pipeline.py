"""
实时语音转换核心编排流水线 (Yukkuri Voice Conversion Pipeline)
"""

import time
import sys
import queue
import threading
from typing import Optional

from yukkuri.config import AppConfig
from yukkuri.asr.base import BaseASREngine
from yukkuri.tts.base import BaseTTSEngine
from yukkuri.g2p.polyglot import PolyglotG2P
from yukkuri.audio.vad import SileroVAD
from yukkuri.audio.capture import MicrophoneStream
from yukkuri.audio.player import AudioPlayer
from yukkuri.audio.virtual_mic import VirtualMicManager
from yukkuri.audio.loopback import LoopbackManager

class YukkuriPipeline:
    """连接音频采集、端点检测、语音识别、音标转写、语音合成与推流的核心流水线"""

    def __init__(
        self,
        config: AppConfig,
        asr: BaseASREngine,
        tts: BaseTTSEngine,
        g2p: Optional[PolyglotG2P] = None,
        vad: Optional[SileroVAD] = None,
        mic_manager: Optional[VirtualMicManager] = None,
        loopback_manager: Optional[LoopbackManager] = None,
        on_segment_processed: Optional[callable] = None,
    ):
        self.config = config
        self.asr = asr
        self.tts = tts
        self.g2p = g2p or PolyglotG2P()
        self.vad = vad
        self.mic_manager = mic_manager
        self.loopback_manager = loopback_manager or LoopbackManager(source_name=config.source_name)
        self.on_segment_processed = on_segment_processed

        self.player = AudioPlayer(target_sink=config.target_sink)
        self.mic_stream = MicrophoneStream(
            sample_rate=config.sample_rate,
            channels=config.channels,
            device=config.device,
            gain=getattr(config, "mic_gain", 1.0),
        )
        self.stop_event = threading.Event()

    def set_voice(self, voice: str) -> bool:
        """动态切换当前油库里声线 (如 f1, f2, m1 等)"""
        if hasattr(self.tts, "set_voice"):
            success = self.tts.set_voice(voice)
            if success:
                self.config.voice = voice
                return True
        return False

    def set_loopback(self, enable: bool) -> bool:
        """动态开启或关闭本地回放监听 (耳机/扬声器同步收听)"""
        self.config.enable_loopback = enable
        if enable:
            return self.loopback_manager.start()
        else:
            self.loopback_manager.stop()
            return True

    def set_mic_gain(self, gain: float):
        """动态调节麦克风软件增益"""
        self.config.mic_gain = max(0.1, float(gain))
        if self.mic_stream:
            self.mic_stream.set_gain(self.config.mic_gain)

    @property
    def is_speech_detected(self) -> bool:
        """当前是否正在检测到持续人声"""
        if self.vad is not None:
            return self.vad.is_speech_detected()
        return False

    def process_segment(self, segment):
        """处理一段已完成断句的语音切片"""
        if len(segment) < self.config.sample_rate * self.config.vad_min_sample_duration:
            return

        try:
            t0 = time.perf_counter()
            text = self.asr.decode(segment, sample_rate=self.config.sample_rate)
            t_asr = (time.perf_counter() - t0) * 1000

            if not text:
                return

            t1 = time.perf_counter()
            koe = self.g2p.convert(text, lang=self.config.lang)
            t_g2p = (time.perf_counter() - t1) * 1000

            if not koe:
                return

            t2 = time.perf_counter()
            wav_data = self.tts.synthesize(koe, speed=self.config.speed)
            t_tts = (time.perf_counter() - t2) * 1000

            if not wav_data:
                return

            self.player.play(wav_data)

            # 终端友好的信息输出与延迟打点
            total_time = t_asr + t_g2p + t_tts
            print(f"\n[识别原文]: {text}")
            print(f"[油库里音标]: {koe}")
            print(f"[推流音频]: {len(wav_data)} 字节 -> {self.config.target_sink}  (耗时: ASR {t_asr:.1f}ms | G2P {t_g2p:.1f}ms | TTS {t_tts:.1f}ms | 合计: {total_time:.1f}ms)")

            if self.on_segment_processed:
                try:
                    stats = {
                        "t_asr": t_asr,
                        "t_g2p": t_g2p,
                        "t_tts": t_tts,
                        "total_time": total_time,
                        "wav_size": len(wav_data),
                        "manual": False,
                    }
                    self.on_segment_processed(text, koe, stats)
                except Exception as e:
                    print(f"[UI 回调异常]: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[切片处理异常]: {e}", file=sys.stderr)

    def speak_text(self, text: str):
        """手动输入文本进行合成与推流"""
        if not text.strip():
            return

        t1 = time.perf_counter()
        koe = self.g2p.convert(text.strip(), lang=self.config.lang)
        t_g2p = (time.perf_counter() - t1) * 1000

        if not koe:
            return

        t2 = time.perf_counter()
        wav_data = self.tts.synthesize(koe, speed=self.config.speed)
        t_tts = (time.perf_counter() - t2) * 1000

        if not wav_data:
            return

        self.player.play(wav_data)

        total_time = t_g2p + t_tts
        print(f"\n[快捷播报]: {text}")
        print(f"[油库里音标]: {koe}")
        print(f"[推流音频]: {len(wav_data)} 字节 -> {self.config.target_sink}  (耗时: G2P {t_g2p:.1f}ms | TTS {t_tts:.1f}ms | 合计: {total_time:.1f}ms)")

        if self.on_segment_processed:
            try:
                stats = {
                    "t_asr": 0.0,
                    "t_g2p": t_g2p,
                    "t_tts": t_tts,
                    "total_time": total_time,
                    "wav_size": len(wav_data),
                    "manual": True,
                }
                self.on_segment_processed(text, koe, stats)
            except Exception as e:
                print(f"[UI 回调异常]: {e}", file=sys.stderr)

    def run(self):
        """启动主循环"""
        if self.mic_manager:
            self.mic_manager.setup()

        if self.config.enable_loopback:
            self.loopback_manager.start()

        print("\n" + "=" * 65)
        print("  油库里实时语音转换器已就绪")
        print(f"  - 识别引擎: {self.config.engine} (语种: {self.config.lang})")
        print(f"  - 合成引擎: AquesTalk1 (声线: {self.config.voice}, 语速: {self.config.speed})")
        print(f"  - 音频输出: {self.config.target_sink}")
        print(f"  - 回放监听: {'已开启 (耳机可同步收听)' if self.config.enable_loopback else '已关闭'}")
        if self.config.device is not None:
            print(f"  - 输入设备 ID: {self.config.device}")
        print("  - 提示: 请对着麦克风说话，按 Ctrl+C 可停止程序")
        print("=" * 65 + "\n")

        self.mic_stream.start()
        fallback_buffer = []

        try:
            while not self.stop_event.is_set():
                try:
                    samples = self.mic_stream.queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if self.vad is not None:
                    segments = self.vad.accept_waveform(samples)
                    for seg in segments:
                        self.process_segment(seg)
                else:
                    # 无 VAD 模式：累积样本切片以达到最低识别时长，避免短切片直接被过滤
                    fallback_buffer.append(samples)
                    total_samples = sum(len(x) for x in fallback_buffer)
                    if total_samples >= int(self.config.sample_rate * 1.5):
                        combined = np.concatenate(fallback_buffer)
                        fallback_buffer.clear()
                        self.process_segment(combined)

        except KeyboardInterrupt:
            pass
        finally:
            if fallback_buffer:
                combined = np.concatenate(fallback_buffer)
                fallback_buffer.clear()
                self.process_segment(combined)
            self.stop()

    def stop(self):
        """优雅关闭各组件"""
        self.stop_event.set()
        print("\n>>> 正在停止音频采集与推流...")
        self.mic_stream.stop()

        if self.vad is not None:
            try:
                flushed = self.vad.flush()
                for seg in flushed:
                    self.process_segment(seg)
            except Exception:
                pass

        self.player.stop()

        if self.loopback_manager:
            self.loopback_manager.stop()

        if self.mic_manager:
            self.mic_manager.cleanup()

        self.tts.close()
        self.asr.close()
        print(">>> 已安全退出。")

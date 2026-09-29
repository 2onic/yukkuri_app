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
    ):
        self.config = config
        self.asr = asr
        self.tts = tts
        self.g2p = g2p or PolyglotG2P()
        self.vad = vad
        self.mic_manager = mic_manager

        self.player = AudioPlayer(target_sink=config.target_sink)
        self.mic_stream = MicrophoneStream(
            sample_rate=config.sample_rate,
            channels=config.channels,
            device=config.device
        )
        self.stop_event = threading.Event()

    def process_segment(self, segment):
        """处理一段已完成断句的语音切片"""
        if len(segment) < self.config.sample_rate * self.config.vad_min_sample_duration:
            return

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

    def run(self):
        """启动主循环"""
        if self.mic_manager:
            self.mic_manager.setup()

        print("\n" + "=" * 65)
        print("  油库里实时语音转换器已就绪")
        print(f"  - 识别引擎: {self.config.engine} (语种: {self.config.lang})")
        print(f"  - 合成引擎: AquesTalk1 (语速: {self.config.speed})")
        print(f"  - 音频输出: {self.config.target_sink}")
        if self.config.device is not None:
            print(f"  - 输入设备 ID: {self.config.device}")
        print("  - 提示: 请对着麦克风说话，按 Ctrl+C 可停止程序")
        print("=" * 65 + "\n")

        self.mic_stream.start()

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
                    # 无 VAD 模式 (直接交给 ASR 处理，兼容部分传统识别器)
                    self.process_segment(samples)

        except KeyboardInterrupt:
            pass
        finally:
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

        if self.mic_manager:
            self.mic_manager.cleanup()

        self.tts.close()
        self.asr.close()
        print(">>> 已安全退出。")

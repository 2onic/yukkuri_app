"""
麦克风音频采集流封装
"""

import sys
import queue
from typing import Optional, Callable
import sounddevice as sd
import numpy as np

class MicrophoneStream:
    """基于 sounddevice 的非阻塞麦克风采样流"""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        blocksize: int = 800,
        device: Optional[int] = None,
        dtype: str = 'float32',
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize
        self.device = device
        self.dtype = dtype

        self.queue: queue.Queue = queue.Queue()
        self._stream: Optional[sd.InputStream] = None

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            print(f"[麦克风状态警告]: {status}", file=sys.stderr)
        self.queue.put(indata.flatten().copy())

    def start(self):
        if self._stream is not None:
            return

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
            blocksize=self.blocksize,
            device=self.device,
            callback=self._audio_callback
        )
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

"""
音频输出与 PipeWire 异步推流播放器
"""

import sys
import queue
import threading
import subprocess
import shutil
from typing import Optional

class AudioPlayer:
    """异步音频播放队列，将合成好的 WAV 缓冲推入目标 Sink"""

    def __init__(self, target_sink: str = "yukkuri_sink"):
        self.target_sink = target_sink
        self.queue: queue.Queue = queue.Queue()
        self.running = True
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def play(self, wav_data: bytes, desc: str = ""):
        """投递一段 WAV 音频数据入队播放"""
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
                    # 如果没有 pw-play，通过 paplay 或直接输出
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

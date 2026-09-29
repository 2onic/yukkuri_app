"""
GUI 模型下载与状态管理对话框
支持可视化查看模型就绪状态、进度条下载与解压
"""

import threading
import queue
from typing import Dict, Optional
import customtkinter as ctk

from yukkuri.model_downloader import (
    check_model_status,
    download_vad,
    download_sensevoice,
    download_vosk,
)

class ModelManagerDialog(ctk.CTkToplevel):
    """模型下载管理弹窗"""

    def __init__(self, parent):
        super().__init__(parent)

        self.title("模型下载与管理 - Yukkuri")
        self.geometry("680x560")
        self.minsize(640, 520)
        self.transient(parent)
        self.grab_set()

        self.msg_queue: queue.Queue = queue.Queue()
        self.is_downloading = False

        self.models_meta = [
            {
                "key": "vad",
                "name": "Silero-VAD 语音活动检测器",
                "desc": "说话停顿与端点切分模块 (约 630KB)",
                "action": lambda cb: download_vad(progress_callback=cb)
            },
            {
                "key": "sensevoice",
                "name": "SenseVoice-Small 多语种端到端",
                "desc": "核心推荐：中/英/日高精度实时识别 (约 230MB)",
                "action": lambda cb: download_sensevoice(progress_callback=cb)
            },
            {
                "key": "vosk_zh",
                "name": "Vosk 中文模型 (model_cn)",
                "desc": "轻量离线中文普通话识别模型 (约 42MB)",
                "action": lambda cb: download_vosk("zh", progress_callback=cb)
            },
            {
                "key": "vosk_ja",
                "name": "Vosk 日文模型 (model_ja)",
                "desc": "轻量离线日语识别模型 (约 48MB)",
                "action": lambda cb: download_vosk("ja", progress_callback=cb)
            },
            {
                "key": "vosk_en",
                "name": "Vosk 英文模型 (model_en)",
                "desc": "轻量离线英语识别模型 (约 40MB)",
                "action": lambda cb: download_vosk("en", progress_callback=cb)
            },
        ]

        self.row_widgets: Dict[str, dict] = {}
        self._build_ui()
        self._refresh_status()

        self.after(50, self._process_queue)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 1. 顶部说明
        header = ctk.CTkFrame(self, corner_radius=8, fg_color=("#2B2B2B", "#1E1E1E"))
        header.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="语音模型管理中心",
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, padx=14, pady=(10, 2), sticky="w")

        ctk.CTkLabel(
            header,
            text="在此一键下载或更新所需的 ASR 与 VAD 语音模型。推荐下载 VAD 与 SenseVoice。",
            font=ctk.CTkFont(size=12),
            text_color="#9E9E9E"
        ).grid(row=1, column=0, padx=14, pady=(0, 10), sticky="w")

        # 2. 模型列表区域 (滚动)
        list_frame = ctk.CTkScrollableFrame(self, corner_radius=8)
        list_frame.grid(row=1, column=0, padx=16, pady=8, sticky="nsew")
        list_frame.grid_columnconfigure(0, weight=1)

        for item in self.models_meta:
            card = ctk.CTkFrame(list_frame, corner_radius=6, fg_color=("#323232", "#262626"))
            card.pack(fill="x", padx=6, pady=5)
            card.grid_columnconfigure(0, weight=1)

            # 信息区
            info_frame = ctk.CTkFrame(card, fg_color="transparent")
            info_frame.grid(row=0, column=0, padx=12, pady=8, sticky="w")

            lbl_name = ctk.CTkLabel(
                info_frame,
                text=item["name"],
                font=ctk.CTkFont(size=13, weight="bold")
            )
            lbl_name.pack(anchor="w")

            lbl_desc = ctk.CTkLabel(
                info_frame,
                text=item["desc"],
                font=ctk.CTkFont(size=11),
                text_color="#B0BEC5"
            )
            lbl_desc.pack(anchor="w")

            # 状态与动作区
            action_frame = ctk.CTkFrame(card, fg_color="transparent")
            action_frame.grid(row=0, column=1, padx=12, pady=8, sticky="e")

            lbl_status = ctk.CTkLabel(
                action_frame,
                text="检查中...",
                font=ctk.CTkFont(size=12, weight="bold")
            )
            lbl_status.pack(side="left", padx=10)

            btn_dl = ctk.CTkButton(
                action_frame,
                text="下载",
                width=80,
                height=30,
                command=lambda meta=item: self._start_download(meta)
            )
            btn_dl.pack(side="left")

            self.row_widgets[item["key"]] = {
                "status_label": lbl_status,
                "button": btn_dl,
                "meta": item
            }

        # 3. 底部下载进度条与状态
        progress_card = ctk.CTkFrame(self, corner_radius=8, fg_color=("#2B2B2B", "#1E1E1E"))
        progress_card.grid(row=2, column=0, padx=16, pady=(8, 16), sticky="ew")
        progress_card.grid_columnconfigure(0, weight=1)

        self.lbl_progress_status = ctk.CTkLabel(
            progress_card,
            text="就绪",
            font=ctk.CTkFont(size=12),
            text_color="#90CAF9"
        )
        self.lbl_progress_status.grid(row=0, column=0, padx=14, pady=(8, 2), sticky="w")

        self.progress_bar = ctk.CTkProgressBar(progress_card, height=10)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, padx=14, pady=(2, 10), sticky="ew")

    def _refresh_status(self):
        """刷新模型检测状态"""
        status_dict = check_model_status()
        for key, exists in status_dict.items():
            if key in self.row_widgets:
                w = self.row_widgets[key]
                if exists:
                    w["status_label"].configure(text="● 已就绪", text_color="#66BB6A")
                    w["button"].configure(text="重新下载", fg_color="#37474F", hover_color="#455A64")
                else:
                    w["status_label"].configure(text="● 未下载", text_color="#FFA726")
                    w["button"].configure(text="立即下载", fg_color="#1E88E5", hover_color="#1565C0")

    def _start_download(self, item_meta):
        if self.is_downloading:
            return

        self.is_downloading = True
        self._set_buttons_state("disabled")
        name = item_meta["name"]
        self.lbl_progress_status.configure(text=f"正在下载 {name}...")
        self.progress_bar.set(0)

        def worker():
            try:
                def on_progress(downloaded, total):
                    self.msg_queue.put(("progress", (downloaded, total)))

                item_meta["action"](on_progress)
                self.msg_queue.put(("done", name))
            except Exception as e:
                self.msg_queue.put(("error", f"下载失败: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _set_buttons_state(self, state: str):
        for w in self.row_widgets.values():
            w["button"].configure(state=state)

    def _process_queue(self):
        while not self.msg_queue.empty():
            msg_type, data = self.msg_queue.get_nowait()
            if msg_type == "progress":
                downloaded, total = data
                if total > 0:
                    fraction = min(1.0, downloaded / total)
                    self.progress_bar.set(fraction)
                    dl_mb = downloaded / (1024 * 1024)
                    tot_mb = total / (1024 * 1024)
                    self.lbl_progress_status.configure(
                        text=f"正在下载... {dl_mb:.1f} MB / {tot_mb:.1f} MB ({fraction * 100:.1f}%)"
                    )
                else:
                    dl_mb = downloaded / (1024 * 1024)
                    self.lbl_progress_status.configure(text=f"正在下载... 已下载 {dl_mb:.1f} MB")

            elif msg_type == "done":
                self.is_downloading = False
                name = data
                self.progress_bar.set(1.0)
                self.lbl_progress_status.configure(text=f"恭喜！{name} 下载并解压完成！", text_color="#66BB6A")
                self._set_buttons_state("normal")
                self._refresh_status()

            elif msg_type == "error":
                self.is_downloading = False
                err_msg = data
                self.lbl_progress_status.configure(text=err_msg, text_color="#EF5350")
                self._set_buttons_state("normal")
                self._refresh_status()

        self.after(50, self._process_queue)

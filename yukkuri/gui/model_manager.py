"""
GUI 模型下载与状态管理对话框
支持可视化查看模型就绪状态、进度条下载与解压，以及 AquesTalk 专有语音库导入向导
"""

import os
import threading
import queue
import webbrowser
from typing import Dict, Optional
import tkinter.filedialog as fd
import tkinter.messagebox as mb
import customtkinter as ctk

from yukkuri.model_downloader import (
    check_model_status,
    download_vad,
    download_sensevoice,
    download_vosk,
    install_aquestalk_from_archive,
    install_aquestalk_from_dir,
    auto_detect_and_install_aquestalk,
)

class AquesTalkImportDialog(ctk.CTkToplevel):
    """AquesTalk 多声线库导入向导弹窗"""

    def __init__(self, parent_manager):
        super().__init__(parent_manager)

        self.parent_manager = parent_manager
        self.title("AquesTalk1 多声线库配置向导")
        self.geometry("560x420")
        self.minsize(520, 380)
        self.transient(parent_manager)
        self.grab_set()

        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)

        # 1. 顶部提示
        header = ctk.CTkFrame(self, corner_radius=8, fg_color=("#2B2B2B", "#1E1E1E"))
        header.grid(row=0, column=0, padx=16, pady=14, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="AquesTalk1 语音库授权与获取指引",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#81D4FA"
        ).grid(row=0, column=0, padx=14, pady=(10, 4), sticky="w")

        info_text = (
            "AquesTalk1 属于 株式会社AQUEST (Aquest Corp.) 专有版权软件。\n"
            "受官方许可协议严格限制，任何第三方均不得二次打包或分发其动态库。\n"
            "用户可前往官方网站免费下载 Linux 评价版 (aqtk1_lnx_200.zip) 并导入。"
        )
        ctk.CTkLabel(
            header,
            text=info_text,
            font=ctk.CTkFont(size=12),
            text_color="#B0BEC5",
            justify="left"
        ).grid(row=1, column=0, padx=14, pady=(0, 10), sticky="w")

        # 2. 操作卡片
        body = ctk.CTkFrame(self, corner_radius=8)
        body.grid(row=1, column=0, padx=16, pady=6, sticky="ew")
        body.grid_columnconfigure(0, weight=1)

        # 选项 1: 打开官网
        btn_web = ctk.CTkButton(
            body,
            text="🌐 第一步：在浏览器中打开 AQUEST 官方下载页",
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1E88E5",
            hover_color="#1565C0",
            command=lambda: webbrowser.open("https://www.a-quest.com/download.html")
        )
        btn_web.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(
            body,
            text="提示：下载页中找到【AquesTalk1 Linux】点击 Download 即可获得 aqtk1_lnx_200.zip",
            font=ctk.CTkFont(size=11),
            text_color="#9E9E9E"
        ).pack(anchor="w", padx=18, pady=(0, 10))

        # 选项 2: 自动检测
        btn_auto = ctk.CTkButton(
            body,
            text="🔍 自动扫描导入 (检查下载目录及系统路径)",
            height=36,
            font=ctk.CTkFont(size=13),
            fg_color="#37474F",
            hover_color="#455A64",
            command=self._on_auto_detect
        )
        btn_auto.pack(fill="x", padx=16, pady=6)

        # 选项 3: 手动选择 zip
        btn_zip = ctk.CTkButton(
            body,
            text="📦 选择已下载的 zip 压缩包 (aqtk1_lnx_200.zip)",
            height=36,
            font=ctk.CTkFont(size=13),
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            command=self._on_select_zip
        )
        btn_zip.pack(fill="x", padx=16, pady=6)

        # 选项 4: 手动选择解压目录
        btn_dir = ctk.CTkButton(
            body,
            text="📁 选择本地已解压目录 (aqtk1_lnx)",
            height=36,
            font=ctk.CTkFont(size=13),
            fg_color="#455A64",
            hover_color="#37474F",
            command=self._on_select_dir
        )
        btn_dir.pack(fill="x", padx=16, pady=(6, 16))

    def _on_auto_detect(self):
        detected = auto_detect_and_install_aquestalk()
        if detected:
            mb.showinfo("导入成功", f"成功自动识别并配置 AquesTalk 多声线库！\n可用声线数量: {len(detected)} 种 ({', '.join(detected)})")
            self._finish_import()
        else:
            mb.showwarning("未找到文件", "未能自动在下载目录或常用位置找到 aqtk1_lnx_200.zip，请点击下方手动选择文件。")

    def _on_select_zip(self):
        file_path = fd.askopenfilename(
            parent=self,
            title="选择 AquesTalk1 Linux 压缩包",
            filetypes=[("AquesTalk 压缩包", "*.zip *.tgz *.tar.gz"), ("所有文件", "*.*")]
        )
        if file_path:
            try:
                voices = install_aquestalk_from_archive(file_path)
                if voices:
                    mb.showinfo("导入成功", f"AquesTalk1 多声线库解压配置成功！\n可用声线: {', '.join(voices)}")
                    self._finish_import()
                else:
                    mb.showerror("错误", "所选压缩包中未检测到 lib64 动态库，请确认下载的是 AquesTalk1 Linux 版本。")
            except Exception as e:
                mb.showerror("解压异常", f"解压配置失败: {e}")

    def _on_select_dir(self):
        dir_path = fd.askdirectory(parent=self, title="选择 AquesTalk1 解压目录")
        if dir_path:
            try:
                voices = install_aquestalk_from_dir(dir_path)
                if voices:
                    mb.showinfo("导入成功", f"AquesTalk1 目录导入成功！\n可用声线: {', '.join(voices)}")
                    self._finish_import()
                else:
                    mb.showerror("错误", "所选目录中未找到 lib64 声线动态库文件。")
            except Exception as e:
                mb.showerror("导入异常", f"导入目录失败: {e}")

    def _finish_import(self):
        self.parent_manager._refresh_status()
        if hasattr(self.parent_manager.master, "_refresh_voices"):
            self.parent_manager.master._refresh_voices()
        self.destroy()

class ModelManagerDialog(ctk.CTkToplevel):
    """模型下载与状态管理对话框"""

    def __init__(self, parent):
        super().__init__(parent)

        self.title("模型下载与管理 - Yukkuri")
        self.geometry("700x600")
        self.minsize(640, 520)
        self.transient(parent)
        self.grab_set()

        self.msg_queue: queue.Queue = queue.Queue()
        self.is_downloading = False

        self.models_meta = [
            {
                "key": "aquestalk",
                "name": "AquesTalk1 经典油库里音效库 (多声线)",
                "desc": "核心语音库：f1、f2等 9 种声线 (AQUEST 版权所有)",
                "custom": True,
            },
            {
                "key": "vad",
                "name": "Silero-VAD 语音活动检测器",
                "desc": "说话停顿与端点切分模块 (约 630KB)",
                "action": lambda cb: download_vad(progress_callback=cb)
            },
            {
                "key": "sensevoice",
                "name": "SenseVoice-Small 多语种端到端",
                "desc": "核心推荐：中/英/日高精度实时识别 (官方精简版约 155MB)",
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
            text="语音模型与声线库管理中心",
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, padx=14, pady=(10, 2), sticky="w")

        ctk.CTkLabel(
            header,
            text="在此管理所需的 ASR 识别模型、VAD 模块与 AquesTalk1 多声线合成库。",
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

            if item.get("custom"):
                btn_dl = ctk.CTkButton(
                    action_frame,
                    text="配置向导",
                    width=86,
                    height=30,
                    command=self._handle_aquestalk_action
                )
            else:
                btn_dl = ctk.CTkButton(
                    action_frame,
                    text="下载",
                    width=86,
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

    def _handle_aquestalk_action(self):
        """打开 AquesTalk 导入向导"""
        AquesTalkImportDialog(self)

    def _refresh_status(self):
        """刷新模型检测状态"""
        status_dict = check_model_status()
        for key, exists in status_dict.items():
            if key in self.row_widgets:
                w = self.row_widgets[key]
                if key == "aquestalk":
                    if exists:
                        count = status_dict.get("aquestalk_count", 0)
                        w["status_label"].configure(text=f"● 已就绪 ({count} 种声线)", text_color="#66BB6A")
                        w["button"].configure(text="声线向导", fg_color="#37474F", hover_color="#455A64")
                    else:
                        w["status_label"].configure(text="● 未安装 (需获取)", text_color="#FFA726")
                        w["button"].configure(text="导入/配置", fg_color="#1E88E5", hover_color="#1565C0")
                else:
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

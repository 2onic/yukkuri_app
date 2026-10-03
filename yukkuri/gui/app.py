"""
Yukkuri 图形界面 (CustomTkinter GUI)
提供可视化声卡选择、语速调节、实时转写展示与快捷播报
"""

import sys
import queue
import threading
import time
from typing import Optional, Dict, Any

import customtkinter as ctk
import sounddevice as sd

from yukkuri.config import AppConfig
from yukkuri.tts.aquestalk1 import AquesTalk1Engine
from yukkuri.asr.sensevoice import SenseVoiceASR
from yukkuri.asr.vosk import VoskASR
from yukkuri.audio.vad import SileroVAD
from yukkuri.audio.virtual_mic import VirtualMicManager
from yukkuri.pipeline import YukkuriPipeline
from yukkuri.gui.devices import get_input_devices, get_output_devices

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class YukkuriApp(ctk.CTk):
    """油库里实时变声器 GUI 主应用"""

    def __init__(self):
        super().__init__()

        self.title("Yukkuri_app - 油库里语音转换器")
        self.geometry("1020x720")
        self.minsize(920, 640)

        # 状态与管道对象
        self.pipeline: Optional[YukkuriPipeline] = None
        self.pipeline_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.msg_queue: queue.Queue = queue.Queue()

        # 音频设备映射
        self.device_map: Dict[str, Optional[int]] = {}
        self.monitor_device_map: Dict[str, Optional[int]] = {}

        # 构建界面
        self._build_ui()

        # 刷新设备与声线列表
        self._refresh_devices()
        self._refresh_voices()

        # 注册定时消费队列与关闭事件
        self.after(50, self._process_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # 左侧固定 380px 宽度，右侧弹性拉伸
        self.grid_columnconfigure(0, weight=0, minsize=380)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 1. 顶部状态栏
        header_frame = ctk.CTkFrame(self, corner_radius=10, fg_color=("#2B2B2B", "#1E1E1E"))
        header_frame.grid(row=0, column=0, columnspan=2, padx=16, pady=(16, 8), sticky="ew")
        header_frame.grid_columnconfigure(1, weight=1)

        title_label = ctk.CTkLabel(
            header_frame,
            text="油库里语音转换器 (Yukkuri Voice Transformer)",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        title_label.grid(row=0, column=0, padx=16, pady=10, sticky="w")

        # 状态指示胶囊
        status_sub_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        status_sub_frame.grid(row=0, column=1, padx=16, pady=10, sticky="e")

        self.status_indicator = ctk.CTkLabel(
            status_sub_frame,
            text="● 已就绪 (未运行)",
            text_color="#9E9E9E",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.status_indicator.pack(side="right", padx=(10, 0))

        badge_sink = "CABLE Input" if sys.platform == "win32" else "yukkuri_sink"
        self.mic_badge = ctk.CTkLabel(
            status_sub_frame,
            text=f"虚拟设备: {badge_sink}",
            text_color="#64B5F6",
            font=ctk.CTkFont(size=13)
        )
        self.mic_badge.pack(side="right", padx=10)

        # 2. 左侧控制面板 (Settings Panel)
        left_panel = ctk.CTkScrollableFrame(self, width=380, corner_radius=10)
        left_panel.grid(row=1, column=0, padx=(16, 8), pady=(8, 16), sticky="nsew")

        # 启动/停止大按钮
        self.btn_toggle = ctk.CTkButton(
            left_panel,
            text="▶ 启动转换器",
            height=46,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#2FA572",
            hover_color="#228B5B",
            command=self._toggle_running
        )
        self.btn_toggle.pack(fill="x", padx=12, pady=(12, 8))

        # 模型管理与下载按钮
        self.btn_models = ctk.CTkButton(
            left_panel,
            text="语音模型与声线库管理",
            height=34,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#37474F",
            hover_color="#455A64",
            command=self._open_model_manager
        )
        self.btn_models.pack(fill="x", padx=12, pady=(0, 14))

        # 分组 1: 引擎与语种
        eng_card = self._create_card(left_panel, "识别引擎与语种")

        ctk.CTkLabel(eng_card, text="识别引擎:", font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=12, pady=(6, 2))
        self.engine_seg = ctk.CTkSegmentedButton(
            eng_card,
            values=["SenseVoice (高精度)", "Vosk (轻量)"]
        )
        self.engine_seg.set("SenseVoice (高精度)")
        self.engine_seg.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkLabel(eng_card, text="发音语种模式:", font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=12, pady=(4, 2))
        self.lang_seg = ctk.CTkSegmentedButton(
            eng_card,
            values=["中文 (zh)", "日语 (ja)", "英语 (en)"]
        )
        self.lang_seg.set("中文 (zh)")
        self.lang_seg.pack(fill="x", padx=12, pady=(0, 12))

        # 分组 2: 声线配置
        voice_card = self._create_card(left_panel, "油库里声线选择")
        ctk.CTkLabel(voice_card, text="当前合成声线 (支持实时热切换):", font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=12, pady=(6, 2))
        self.voice_menu = ctk.CTkOptionMenu(voice_card, values=["正在加载声线..."], command=self._on_voice_changed)
        self.voice_menu.pack(fill="x", padx=12, pady=(0, 12))

        # 分组 2: 硬件与麦克风设备
        dev_card = self._create_card(left_panel, "输入麦克风选择")

        dev_row = ctk.CTkFrame(dev_card, fg_color="transparent")
        dev_row.pack(fill="x", padx=12, pady=(6, 6))
        dev_row.grid_columnconfigure(0, weight=1)

        self.device_menu = ctk.CTkOptionMenu(dev_row, values=["正在获取设备..."])
        self.device_menu.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        btn_refresh = ctk.CTkButton(dev_row, text="刷新", width=48, command=self._refresh_devices)
        btn_refresh.grid(row=0, column=1)

        self.gain_label = ctk.CTkLabel(dev_card, text="麦克风增益: 1.0x (标准音量)", font=ctk.CTkFont(size=13))
        self.gain_label.pack(anchor="w", padx=12, pady=(4, 0))
        self.gain_slider = ctk.CTkSlider(dev_card, from_=0.5, to=3.0, number_of_steps=25, command=self._on_gain_changed)
        self.gain_slider.set(1.0)
        self.gain_slider.pack(fill="x", padx=12, pady=(2, 12))

        # 分组 3: 语速与端点灵敏度
        tune_card = self._create_card(left_panel, "声音与断句调优")

        self.speed_label = ctk.CTkLabel(tune_card, text="油库里语速: 100%", font=ctk.CTkFont(size=13))
        self.speed_label.pack(anchor="w", padx=12, pady=(6, 0))
        self.speed_slider = ctk.CTkSlider(tune_card, from_=50, to=250, number_of_steps=40, command=self._on_speed_changed)
        self.speed_slider.set(100)
        self.speed_slider.pack(fill="x", padx=12, pady=(2, 10))

        self.vad_label = ctk.CTkLabel(tune_card, text="说话停顿断句: 350 ms", font=ctk.CTkFont(size=13))
        self.vad_label.pack(anchor="w", padx=12, pady=(4, 0))
        self.vad_slider = ctk.CTkSlider(tune_card, from_=200, to=700, number_of_steps=50, command=self._on_vad_changed)
        self.vad_slider.set(350)
        self.vad_slider.pack(fill="x", padx=12, pady=(2, 10))

        self.switch_max_speech = ctk.CTkSwitch(
            tune_card,
            text="限制单句最长录音 (防长语音卡顿)",
            command=self._on_max_speech_switch_toggled
        )
        self.switch_max_speech.select()
        self.switch_max_speech.pack(padx=12, pady=(4, 2), anchor="w")

        self.max_speech_label = ctk.CTkLabel(tune_card, text="最长单句截断: 6.0 秒", font=ctk.CTkFont(size=13))
        self.max_speech_label.pack(anchor="w", padx=12, pady=(2, 0))
        self.max_speech_slider = ctk.CTkSlider(tune_card, from_=2.0, to=15.0, number_of_steps=26, command=self._on_max_speech_changed)
        self.max_speech_slider.set(6.0)
        self.max_speech_slider.pack(fill="x", padx=12, pady=(2, 12))

        # 分组 4: 监听与虚拟声卡
        opt_card = self._create_card(left_panel, "监听与虚拟麦克风")

        self.switch_loopback = ctk.CTkSwitch(
            opt_card,
            text="回放监听 (自己也能听到)",
            command=self._on_loopback_toggled
        )
        self.switch_loopback.pack(padx=12, pady=(6, 6), anchor="w")

        if sys.platform != "win32":
            self.switch_dyn_mic = ctk.CTkSwitch(
                opt_card,
                text="退出时自动释放虚拟声卡"
            )
            self.switch_dyn_mic.select()
            self.switch_dyn_mic.pack(padx=12, pady=(0, 10), anchor="w")
        else:
            self.switch_dyn_mic = None
            ctk.CTkLabel(opt_card, text="耳机监听输出设备 (回放输出):", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=12, pady=(4, 2))
            self.monitor_menu = ctk.CTkOptionMenu(opt_card, values=["系统默认 (Default)"])
            self.monitor_menu.pack(fill="x", padx=12, pady=(0, 10))

        # 3. 右侧内容区 (日志与快捷播报)
        right_panel = ctk.CTkFrame(self, corner_radius=10)
        right_panel.grid(row=1, column=1, padx=(8, 16), pady=(8, 16), sticky="nsew")
        right_panel.grid_rowconfigure(1, weight=1)
        right_panel.grid_columnconfigure(0, weight=1)

        # 日志顶部工具栏
        log_header = ctk.CTkFrame(right_panel, fg_color="transparent")
        log_header.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="ew")
        log_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            log_header,
            text="实时识别与转换日志",
            font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        btn_clear = ctk.CTkButton(
            log_header, text="清空日志", width=70, height=28,
            fg_color="#455A64", hover_color="#37474F",
            command=self._clear_log
        )
        btn_clear.grid(row=0, column=1, sticky="e")

        # 实时日志文本框
        self.log_box = ctk.CTkTextbox(
            right_panel,
            font=ctk.CTkFont(family="monospace", size=13),
            wrap="word",
            corner_radius=8
        )
        self.log_box.grid(row=1, column=0, padx=12, pady=6, sticky="nsew")
        self._append_log("系统", "欢迎使用 Yukkuri_app。请在左侧点击【启动转换器】开始体验！")

        # 快捷测试与播报区域
        quick_frame = ctk.CTkFrame(right_panel, corner_radius=8, fg_color=("#323232", "#242424"))
        quick_frame.grid(row=2, column=0, padx=12, pady=(6, 12), sticky="ew")
        quick_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            quick_frame,
            text="文字转语音 (无需说话，直接合成并推送到虚拟麦克风):",
            font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(8, 4), sticky="w")

        self.entry_speak = ctk.CTkEntry(
            quick_frame,
            placeholder_text="输入想要合成的文本...",
            height=34
        )
        self.entry_speak.grid(row=1, column=0, padx=(12, 8), pady=(0, 10), sticky="ew")
        self.entry_speak.bind("<Return>", lambda event: self._send_manual_speak())

        self.btn_speak = ctk.CTkButton(
            quick_frame,
            text="播报推流",
            width=90,
            height=34,
            command=self._send_manual_speak
        )
        self.btn_speak.grid(row=1, column=1, padx=(0, 12), pady=(0, 10))

    def _create_card(self, parent, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, corner_radius=8, fg_color=("#323232", "#242424"))
        card.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#81D4FA"
        ).pack(anchor="w", padx=12, pady=(10, 4))
        return card

    def _refresh_devices(self):
        """刷新并加载系统麦克风输入列表，默认选定系统默认设备"""
        devices = get_input_devices()
        self.device_map.clear()
        labels = []
        for dev_id, label in devices:
            self.device_map[label] = dev_id
            labels.append(label)

        if labels:
            self.device_menu.configure(values=labels)
            self.device_menu.set(labels[0])

        if sys.platform == "win32" and hasattr(self, "monitor_menu"):
            out_devices = get_output_devices()
            self.monitor_device_map.clear()
            out_labels = []
            for dev_id, label in out_devices:
                self.monitor_device_map[label] = dev_id
                out_labels.append(label)
            if out_labels:
                self.monitor_menu.configure(values=out_labels)
                self.monitor_menu.set(out_labels[0])

    def _refresh_voices(self):
        """刷新并加载可用的 AquesTalk 声线列表"""
        from yukkuri.config import AppConfig, AQUESTALK_VOICES
        config = AppConfig()
        avail = config.get_available_voices()

        options = []
        if avail:
            for k, v in avail.items():
                options.append(f"{k}: {v}")
        else:
            options = ["未检测到声线 (请点击上方模型管理导入)"]

        self.voice_menu.configure(values=options)
        if options:
            current = self.voice_menu.get()
            cur_key = current.split(":")[0].strip() if ":" in current else ""
            match = [opt for opt in options if opt.startswith(f"{cur_key}:")]
            if match:
                self.voice_menu.set(match[0])
            else:
                self.voice_menu.set(options[0])

    def _on_voice_changed(self, choice: str):
        if ":" not in choice:
            return
        voice_key = choice.split(":")[0].strip()
        if self.pipeline and self.is_running:
            ok = self.pipeline.set_voice(voice_key)
            if ok:
                self._append_log("系统", f"已实时热切换声线为: {choice}")
            else:
                self._append_log("系统", f"切换声线失败: 未找到 {voice_key} 库")
        else:
            self._append_log("系统", f"预设声线已选定: {choice}")

    def _on_loopback_toggled(self):
        enable = bool(self.switch_loopback.get())
        if self.pipeline and self.is_running:
            if sys.platform == "win32" and hasattr(self, "monitor_menu"):
                mon_label = self.monitor_menu.get()
                mon_id = self.monitor_device_map.get(mon_label, None)
                self.pipeline.config.monitor_device = mon_id
            ok = self.pipeline.set_loopback(enable)
            if enable:
                if ok:
                    msg = "已开启回放监听 (通过 WASAPI 双路输出)" if sys.platform == "win32" else "已开启回放监听 (通过 pw-loopback)"
                    self._append_log("系统", msg)
                else:
                    msg = "回放监听启动失败，请检查输出设备" if sys.platform == "win32" else "回放监听启动失败，请确认系统支持 pw-loopback 或 pactl"
                    self._append_log("系统", msg)
            else:
                self._append_log("系统", "已关闭回放监听")
        else:
            if enable:
                self._append_log("系统", "已开启回放监听预设 (启动转换器时将自动开启)")
            else:
                self._append_log("系统", "已关闭回放监听预设")

    def _on_gain_changed(self, value):
        gain = round(float(value), 1)
        percent = int(gain * 100)
        note = "标准音量" if gain == 1.0 else ("放大" if gain > 1.0 else "降低")
        self.gain_label.configure(text=f"麦克风增益: {gain:.1f}x ({percent}%, {note})")
        if self.pipeline:
            self.pipeline.set_mic_gain(gain)

    def _on_speed_changed(self, value):
        spd = int(value)
        self.speed_label.configure(text=f"油库里语速: {spd}%")
        if self.pipeline:
            self.pipeline.config.speed = spd

    def _on_vad_changed(self, value):
        ms = int(value)
        self.vad_label.configure(text=f"说话停顿断句: {ms} ms")
        if self.pipeline and self.pipeline.config:
            self.pipeline.config.vad_min_silence = ms / 1000.0
            if self.pipeline.vad:
                self.pipeline.vad.set_min_silence_duration(ms / 1000.0)

    def _on_max_speech_switch_toggled(self):
        enabled = bool(self.switch_max_speech.get())
        if enabled:
            self.max_speech_slider.configure(state="normal")
            sec = round(float(self.max_speech_slider.get()), 1)
            self.max_speech_label.configure(text=f"最长单句截断: {sec} 秒")
            if self.pipeline and self.pipeline.config:
                self.pipeline.config.vad_enable_max_speech = True
                self.pipeline.config.vad_max_speech = sec
                if self.pipeline.vad:
                    self.pipeline.vad.set_max_speech_duration(sec)
        else:
            self.max_speech_slider.configure(state="disabled")
            self.max_speech_label.configure(text="最长单句截断: 已手动关闭 (不限制长度)")
            if self.pipeline and self.pipeline.config:
                self.pipeline.config.vad_enable_max_speech = False
                if self.pipeline.vad:
                    self.pipeline.vad.set_max_speech_duration(0.0)

    def _on_max_speech_changed(self, value):
        if not bool(self.switch_max_speech.get()):
            return
        sec = round(float(value), 1)
        self.max_speech_label.configure(text=f"最长单句截断: {sec} 秒")
        if self.pipeline and self.pipeline.config:
            self.pipeline.config.vad_max_speech = sec
            if self.pipeline.config.vad_enable_max_speech and self.pipeline.vad:
                self.pipeline.vad.set_max_speech_duration(sec)

    def _clear_log(self):
        self.log_box.delete("1.0", "end")

    def _append_log(self, tag: str, message: str, meta: str = ""):
        timestamp = time.strftime("%H:%M:%S")
        if tag == "系统":
            prefix = "[系统]"
        elif tag == "语音":
            prefix = "[麦克风]"
        elif tag == "播报":
            prefix = "[播报]"
        else:
            prefix = "[信息]"

        formatted = f"[{timestamp}] {prefix} {message}\n"
        if meta:
            formatted += f"       ↳ {meta}\n"

        self.log_box.insert("end", formatted)
        self.log_box.see("end")

    def _toggle_running(self):
        if not self.is_running:
            self._start_pipeline()
        else:
            self._stop_pipeline()

    def _open_model_manager(self):
        """打开模型下载与状态管理对话框"""
        from yukkuri.gui.model_manager import ModelManagerDialog
        ModelManagerDialog(self)

    def _start_pipeline(self):
        """在后台线程初始化并运行变声流水线"""
        # 读取当前界面配置
        engine_str = "sensevoice" if "SenseVoice" in self.engine_seg.get() else "vosk"
        lang_str = "zh"
        if "ja" in self.lang_seg.get():
            lang_str = "ja"
        elif "en" in self.lang_seg.get():
            lang_str = "en"

        selected_label = self.device_menu.get()
        device_id = self.device_map.get(selected_label, None)
        speed = int(self.speed_slider.get())
        vad_silence = self.vad_slider.get() / 1000.0
        vad_max_speech = round(float(self.max_speech_slider.get()), 1)
        mic_gain = round(float(self.gain_slider.get()), 1)
        monitor_device_id = None
        if sys.platform == "win32" and hasattr(self, "monitor_menu"):
            selected_mon_label = self.monitor_menu.get()
            monitor_device_id = self.monitor_device_map.get(selected_mon_label, None)

        enable_dyn_mic = bool(self.switch_dyn_mic.get()) if getattr(self, "switch_dyn_mic", None) is not None else False
        enable_loopback = bool(self.switch_loopback.get())
        enable_max_speech = bool(self.switch_max_speech.get())

        selected_voice_opt = self.voice_menu.get()
        selected_voice = selected_voice_opt.split(":")[0].strip() if ":" in selected_voice_opt else "f1"

        config = AppConfig(
            engine=engine_str,
            lang=lang_str,
            voice=selected_voice,
            speed=speed,
            device=device_id,
            monitor_device=monitor_device_id,
            mic_gain=mic_gain,
            vad_min_silence=vad_silence,
            vad_max_speech=vad_max_speech,
            vad_enable_max_speech=enable_max_speech,
            enable_dynamic_mic=enable_dyn_mic,
            enable_loopback=enable_loopback,
        )

        self._append_log("系统", "正在启动实时转换器，加载语音模型与驱动...")
        self.status_indicator.configure(text="● 正在初始化...", text_color="#FFB74D")
        self.btn_toggle.configure(state="disabled", text="正在初始化...")

        def worker():
            try:
                # 查找并初始化 AquesTalk 多声线合成引擎
                so_path = config.find_aquestalk_library(config.voice)
                if not so_path:
                    self.msg_queue.put(("error_model", f"未找到所选声线 ({config.voice}) 库文件，已自动为你打开模型管理器，请点击导入/配置。"))
                    return

                tts_engine = AquesTalk1Engine(
                    voice=config.voice,
                    voice_resolver=config.find_aquestalk_library,
                    dev_key=config.dev_key,
                    usr_key=config.usr_key,
                )
                vad_detector = None

                if config.engine == "sensevoice":
                    model_dir = config.find_sensevoice_dir()
                    vad_file = config.find_vad_model()
                    if not model_dir or not vad_file:
                        self.msg_queue.put(("error_model", "未找到 SenseVoice 或 Silero-VAD 模型，已自动为你打开模型管理器，请点击下载。"))
                        return

                    asr_engine = SenseVoiceASR(model_dir, num_threads=config.num_threads)
                    vad_detector = SileroVAD(
                        vad_model_path=vad_file,
                        sample_rate=config.sample_rate,
                        min_silence_duration=config.vad_min_silence,
                        min_speech_duration=config.vad_min_speech,
                        max_speech_duration=config.get_effective_max_speech_duration(),
                        threshold=config.vad_threshold
                    )
                else:
                    model_dir = config.find_vosk_model_dir()
                    if not model_dir:
                        self.msg_queue.put(("error_model", f"未找到 Vosk 对应语种模型 ({config.lang})，已自动为你打开模型管理器，请点击下载。"))
                        return
                    asr_engine = VoskASR(model_dir, sample_rate=config.sample_rate)
                    vad_file = config.find_vad_model()
                    if vad_file:
                        try:
                            vad_detector = SileroVAD(
                                vad_model_path=vad_file,
                                sample_rate=config.sample_rate,
                                min_silence_duration=config.vad_min_silence,
                                min_speech_duration=config.vad_min_speech,
                                max_speech_duration=config.get_effective_max_speech_duration(),
                                threshold=config.vad_threshold
                            )
                        except Exception:
                            vad_detector = None

                if sys.platform == "win32":
                    mic_manager = VirtualMicManager(sink_name=config.target_sink)
                else:
                    mic_manager = VirtualMicManager(
                        sink_name=config.target_sink,
                        auto_cleanup=config.enable_dynamic_mic
                    )

                # 回调推送到 UI
                def on_segment(text: str, koe: str, stats: dict):
                    self.msg_queue.put(("transcription", {
                        "text": text,
                        "koe": koe,
                        "stats": stats
                    }))

                self.pipeline = YukkuriPipeline(
                    config=config,
                    asr=asr_engine,
                    tts=tts_engine,
                    vad=vad_detector,
                    mic_manager=mic_manager,
                    on_segment_processed=on_segment
                )

                self.msg_queue.put(("started", None))
                self.pipeline.run()

            except Exception as e:
                self.msg_queue.put(("error", f"运行异常: {e}"))
            finally:
                self.msg_queue.put(("stopped", None))

        self.pipeline_thread = threading.Thread(target=worker, daemon=True)
        self.pipeline_thread.start()

    def _stop_pipeline(self):
        """停止流水线"""
        self.status_indicator.configure(text="● 正在停止...", text_color="#FFB74D")
        self.btn_toggle.configure(state="disabled", text="正在停止...")
        if self.pipeline:
            self.pipeline.stop()

    def _send_manual_speak(self):
        """触发文字转语音推流播报 (异步工作线程执行，避免阻塞 Tkinter UI 事件循环)"""
        text = self.entry_speak.get().strip()
        if not text:
            return

        if self.pipeline and self.is_running:
            self.entry_speak.delete(0, "end")
            threading.Thread(
                target=self.pipeline.speak_text,
                args=(text,),
                daemon=True,
                name="ManualSpeakWorker"
            ).start()
        else:
            self._append_log("系统", "提示：请先启动转换器，即可将文字实时推流至虚拟麦克风！")

    def _process_queue(self):
        """在主线程定时轮询事件队列"""
        while not self.msg_queue.empty():
            msg_type, data = self.msg_queue.get_nowait()

            if msg_type == "started":
                self.is_running = True
                self.btn_toggle.configure(state="normal", text="⏹ 停止转换器", fg_color="#E04747", hover_color="#C62828")
                if sys.platform == "win32":
                    self._append_log("系统", "转换器启动成功！已推流至 [CABLE Input]，请在语音软件中将麦克风选择为 [CABLE Output]")
                else:
                    self._append_log("系统", "转换器启动成功！请在软件中将麦克风选择为 [Yukkuri Virtual Mic]")

            elif msg_type == "stopped":
                self.is_running = False
                self.pipeline = None
                self.btn_toggle.configure(state="normal", text="▶ 启动转换器", fg_color="#2FA572", hover_color="#228B5B")
                self.status_indicator.configure(text="● 已停止", text_color="#9E9E9E")
                self._append_log("系统", "转换器已停止。")

            elif msg_type == "error":
                self.is_running = False
                self.btn_toggle.configure(state="normal", text="▶ 启动转换器", fg_color="#2FA572", hover_color="#228B5B")
                self.status_indicator.configure(text="● 启动失败", text_color="#EF5350")
                self._append_log("系统", f"错误: {data}")

            elif msg_type == "error_model":
                self.is_running = False
                self.btn_toggle.configure(state="normal", text="▶ 启动转换器", fg_color="#2FA572", hover_color="#228B5B")
                self.status_indicator.configure(text="● 缺少模型", text_color="#FFA726")
                self._append_log("系统", f"提示: {data}")
                self._open_model_manager()

            elif msg_type == "transcription":
                text = data["text"]
                koe = data["koe"]
                stats = data["stats"]
                tag = "播报" if stats.get("manual") else "语音"
                meta_str = f"音标: {koe}  |  延迟: ASR {stats['t_asr']:.0f}ms, G2P {stats['t_g2p']:.0f}ms, TTS {stats['t_tts']:.0f}ms (总计 {stats['total_time']:.0f}ms)"
                self._append_log(tag, f"【原文】{text}", meta=meta_str)

        self.after(50, self._process_queue)

    def _on_close(self):
        """窗口关闭清理"""
        if self.is_running and self.pipeline:
            self.pipeline.stop()
        self.destroy()

def main():
    app = YukkuriApp()
    app.mainloop()

if __name__ == "__main__":
    main()

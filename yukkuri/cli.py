"""
Yukkuri 命令行接口与主入口 (CLI Entrypoint)
"""

import sys
import signal
import argparse
import sounddevice as sd

from yukkuri.config import AppConfig
from yukkuri.tts.aquestalk1 import AquesTalk1Engine
from yukkuri.asr.sensevoice import SenseVoiceASR
from yukkuri.asr.vosk import VoskASR
from yukkuri.audio.vad import SileroVAD
from yukkuri.audio.virtual_mic import VirtualMicManager
from yukkuri.pipeline import YukkuriPipeline

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="yukkuri",
        description="实时语音转油库里音效虚拟麦克风工具"
    )
    parser.add_argument(
        "--engine", type=str, default="sensevoice", choices=["sensevoice", "vosk"],
        help="ASR 识别引擎: sensevoice (阿里高精度端到端, 默认), vosk (传统轻量)"
    )
    parser.add_argument(
        "--lang", type=str, default="zh", choices=["zh", "cn", "ja", "en"],
        help="识别与发音语种 (SenseVoice 自动支持多语种; Vosk 用于选择对应模型)"
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="自定义 ASR 模型目录路径"
    )
    parser.add_argument(
        "--target", type=str, default="yukkuri_sink",
        help="PipeWire 输出目标 Sink 名称 (默认: yukkuri_sink)"
    )
    parser.add_argument(
        "--voice", type=str, default="f1", choices=["f1", "f2", "f3", "m1", "m2", "imd1", "jgr", "dvd", "r1"],
        help="油库里合成声线: f1 (默认), f2, f3, m1, m2, imd1, jgr, dvd, r1"
    )
    parser.add_argument(
        "--speed", type=int, default=100,
        help="油库里语速 50~300 (默认: 100)"
    )
    parser.add_argument(
        "--loopback", "--monitor", action="store_true", dest="loopback",
        help="开启本地回放监听 (耳机/扬声器可实时听到合成出的油库里语音)"
    )
    parser.add_argument(
        "--device", type=int, default=None,
        help="麦克风输入设备索引 ID (默认使用系统默认录音设备)"
    )
    parser.add_argument(
        "--max-speech-duration", type=float, default=6.0,
        help="最长连续说话截断时间 (秒, 默认: 6.0, 设为 0 或负数则关闭强制截断)"
    )
    parser.add_argument(
        "--mic-gain", type=float, default=1.0,
        help="麦克风输入软件增益倍数 (默认: 1.0, 可设为 0.5~3.0)"
    )
    parser.add_argument(
        "--no-max-speech", "--disable-cutoff", action="store_true",
        help="手动关闭最长单句强制截断保护"
    )
    parser.add_argument(
        "--no-dynamic-mic", action="store_true",
        help="禁用 pactl 自动动态加载虚拟声卡"
    )
    parser.add_argument(
        "--gui", action="store_true",
        help="启动桌面图形控制界面 (GUI)"
    )
    parser.add_argument(
        "--list-devices", action="store_true",
        help="列出所有可用音频输入/输出设备并退出"
    )
    return parser.parse_args()

def main():
    args = parse_args()

    if args.gui:
        try:
            from yukkuri.gui.app import main as gui_main
            return gui_main()
        except ImportError as e:
            print(f"[错误] 无法加载 GUI 模块: {e}", file=sys.stderr)
            print("请确认已安装 customtkinter 依赖: pip install customtkinter", file=sys.stderr)
            return 1

    if args.list_devices:
        print("\n=== 系统可用音频设备列表 ===")
        print(sd.query_devices())
        print()
        return 0

    enable_max_speech = (not args.no_max_speech) and (args.max_speech_duration > 0)
    config = AppConfig(
        engine=args.engine,
        lang=args.lang,
        voice=args.voice,
        speed=args.speed,
        target_sink=args.target,
        device=args.device,
        custom_model_path=args.model,
        enable_dynamic_mic=not args.no_dynamic_mic,
        enable_loopback=args.loopback,
        mic_gain=args.mic_gain,
        vad_max_speech=args.max_speech_duration if args.max_speech_duration > 0 else 0.0,
        vad_enable_max_speech=enable_max_speech,
    )

    # 1. 查找并初始化 AquesTalk 多声线合成引擎
    so_path = config.find_aquestalk_library(config.voice)
    if not so_path:
        print(f"[错误] 未找到声线 '{config.voice}' 对应的 libAquesTalk.so 动态库！", file=sys.stderr)
        print("请运行以下命令配置 AquesTalk 语音库：", file=sys.stderr)
        print("  ./setup_models.sh --aquestalk", file=sys.stderr)
        return 1

    try:
        tts_engine = AquesTalk1Engine(
            voice=config.voice,
            voice_resolver=config.find_aquestalk_library
        )
    except Exception as e:
        print(f"[错误] 初始化 AquesTalk 失败: {e}", file=sys.stderr)
        return 1

    # 2. 初始化识别引擎与 VAD
    vad_detector = None
    if config.engine == "sensevoice":
        model_dir = config.find_sensevoice_dir()
        vad_file = config.find_vad_model()

        if not model_dir or not vad_file:
            print("[错误] 未找到 SenseVoice 或 Silero-VAD 模型文件！", file=sys.stderr)
            print("请先执行以下命令下载所需模型：", file=sys.stderr)
            print("  ./setup_models.sh", file=sys.stderr)
            return 1

        try:
            print(f">>> 正在加载 SenseVoice 识别引擎 ({model_dir})...")
            asr_engine = SenseVoiceASR(model_dir, num_threads=config.num_threads)
            print(f">>> 正在加载 Silero-VAD 语音活动检测器 ({vad_file})...")
            vad_detector = SileroVAD(
                vad_model_path=vad_file,
                sample_rate=config.sample_rate,
                min_silence_duration=config.vad_min_silence,
                min_speech_duration=config.vad_min_speech,
                max_speech_duration=config.get_effective_max_speech_duration(),
                threshold=config.vad_threshold
            )
        except Exception as e:
            print(f"[错误] 初始化 SenseVoice 引擎失败: {e}", file=sys.stderr)
            return 1

    elif config.engine == "vosk":
        model_dir = config.find_vosk_model_dir()
        if not model_dir:
            print(f"[错误] 未找到 Vosk 模型目录 (语种: {config.lang})！", file=sys.stderr)
            print("请确认对应语种模型已下载至 model/ 或 model_cn/ 目录。", file=sys.stderr)
            return 1

        try:
            print(f">>> 正在加载 Vosk 识别引擎 ({model_dir})...")
            asr_engine = VoskASR(model_dir, sample_rate=config.sample_rate)
        except Exception as e:
            print(f"[错误] 初始化 Vosk 引擎失败: {e}", file=sys.stderr)
            return 1
    else:
        print(f"[错误] 未知引擎: {config.engine}", file=sys.stderr)
        return 1

    # 3. 虚拟声卡管理
    mic_manager = None
    if config.enable_dynamic_mic:
        mic_manager = VirtualMicManager(sink_name=config.target_sink)

    # 4. 构建并启动流水线
    pipeline = YukkuriPipeline(
        config=config,
        asr=asr_engine,
        tts=tts_engine,
        vad=vad_detector,
        mic_manager=mic_manager,
    )

    def sig_handler(sig, frame):
        pipeline.stop()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    try:
        pipeline.run()
    except Exception as e:
        print(f"[运行时异常]: {e}", file=sys.stderr)
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())

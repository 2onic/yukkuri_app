#!/usr/bin/env python3
"""
跨平台模型与语音库一键下载配置脚本 (Cross-platform Model Setup Script)
支持 Windows 与 Linux，无需 bash / curl / tar 等外部工具。
"""

import os
import sys
import argparse

from yukkuri.model_downloader import (
    check_model_status,
    download_vad,
    download_sensevoice,
    download_vosk,
    install_aquestalk_from_archive,
    install_aquestalk_from_dir,
    auto_detect_and_install_aquestalk,
    get_project_root,
)

def make_progress_bar(label: str):
    last_pct = [-1]

    def callback(downloaded: int, total: int):
        if total > 0:
            pct = int(downloaded * 100 / total)
            if pct != last_pct[0] or pct == 100:
                last_pct[0] = pct
                mb_cur = downloaded / (1024 * 1024)
                mb_tot = total / (1024 * 1024)
                bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                sys.stdout.write(f"\r  {label}: [{bar}] {pct:3d}% ({mb_cur:5.1f}MB / {mb_tot:5.1f}MB)")
                sys.stdout.flush()
                if pct >= 100:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
        else:
            mb_cur = downloaded / (1024 * 1024)
            sys.stdout.write(f"\r  {label}: 已下载 {mb_cur:5.1f}MB...")
            sys.stdout.flush()

    return callback

def show_status(root: str):
    status = check_model_status(root)
    print("\n================ 当前模型就绪状态 ================")
    print(f"  Silero-VAD 端点检测:    {'[已就绪]' if status['vad'] else '[未安装]'}")
    print(f"  SenseVoice 语音识别:    {'[已就绪]' if status['sensevoice'] else '[未安装]'}")
    print(f"  Vosk 中文模型 (zh):     {'[已就绪]' if status['vosk_zh'] else '[未安装]'}")
    print(f"  Vosk 日文模型 (ja):     {'[已就绪]' if status['vosk_ja'] else '[未安装]'}")
    print(f"  Vosk 英文模型 (en):     {'[已就绪]' if status['vosk_en'] else '[未安装]'}")
    aq_status = f"[已就绪: {status['aquestalk_count']} 种声线 ({', '.join(status['aquestalk_voices'])})]" if status['aquestalk'] else "[未安装]"
    print(f"  AquesTalk 声线动态库:   {aq_status}")
    print("==================================================\n")

def main():
    parser = argparse.ArgumentParser(
        description="Yukkuri 语音模型跨平台下载与配置工具"
    )
    parser.add_argument("--check", action="store_true", help="检查并显示所有模型当前就绪状态")
    parser.add_argument("--all", action="store_true", help="下载全部模型 (SenseVoice, VAD, Vosk 中日英)")
    parser.add_argument("--vad", action="store_true", help="仅下载 Silero-VAD 端点检测模型")
    parser.add_argument("--sensevoice", action="store_true", help="仅下载 SenseVoice ASR 阿里模型")
    parser.add_argument("--vosk", type=str, nargs="?", const="zh", choices=["zh", "ja", "en", "all"], help="下载 Vosk 模型 (默认: zh，可选 ja, en, all)")
    parser.add_argument("--aquestalk", type=str, nargs="?", const="auto", help="导入 AquesTalk 动态库 (可提供压缩包路径、解压目录或 dll/so 文件路径；留空则自动扫描)")

    args = parser.parse_args()
    root = get_project_root()

    if args.check:
        show_status(root)
        return 0

    run_default = not any([args.all, args.vad, args.sensevoice, args.vosk, args.aquestalk])

    print(">>> 正在检查并准备配置模型...")

    if args.aquestalk:
        target = args.aquestalk
        if target == "auto":
            print(">>> 正在自动扫描系统路径与下载目录中的 AquesTalk 安装包...")
            voices = auto_detect_and_install_aquestalk(root=root)
            if voices:
                print(f"[成功] 自动配置 AquesTalk 成功！检测到可用声线: {', '.join(voices)}")
            else:
                print("[提示] 未在常见目录中找到 AquesTalk 安装包。")
                print("请前往 AQUEST 官方网站 (https://www.a-quest.com/download.html) 获取后使用：")
                print("  python setup_models.py --aquestalk <文件或目录路径>")
        elif os.path.isdir(target):
            print(f">>> 正在从目录导入 AquesTalk: {target}")
            voices = install_aquestalk_from_dir(target, root=root)
            if voices:
                print(f"[成功] 导入 AquesTalk 成功！检测到可用声线: {', '.join(voices)}")
            else:
                print(f"[错误] 目录中未找到有效的 AquesTalk 库文件: {target}")
        elif os.path.isfile(target):
            print(f">>> 正在从文件导入 AquesTalk: {target}")
            voices = install_aquestalk_from_archive(target, root=root)
            if voices:
                print(f"[成功] 导入 AquesTalk 成功！检测到可用声线: {', '.join(voices)}")
            else:
                print(f"[错误] 文件中未检测到有效的 AquesTalk 动态库: {target}")
        else:
            print(f"[错误] 指定的 AquesTalk 路径不存在: {target}")

    # 下载 Silero-VAD
    if run_default or args.all or args.vad or args.sensevoice:
        status = check_model_status(root)
        if not status["vad"]:
            print(">>> 开始下载 Silero-VAD 端点检测模型 (~600KB)...")
            try:
                download_vad(root=root, progress_callback=make_progress_bar("Silero-VAD"))
                print("[完成] Silero-VAD 模型下载完毕！")
            except Exception as e:
                print(f"[错误] 下载 Silero-VAD 失败: {e}")
        else:
            print("  Silero-VAD: 已存在，跳过下载。")

    # 下载 SenseVoice
    if run_default or args.all or args.sensevoice:
        status = check_model_status(root)
        if not status["sensevoice"]:
            print(">>> 开始下载 SenseVoice 语音识别模型 (~240MB)...")
            try:
                download_sensevoice(root=root, progress_callback=make_progress_bar("SenseVoice"))
                print("[完成] SenseVoice 模型下载与解压完毕！")
            except Exception as e:
                print(f"[错误] 下载 SenseVoice 失败: {e}")
        else:
            print("  SenseVoice: 已存在，跳过下载。")

    # 下载 Vosk
    if args.all or args.vosk:
        langs = ["zh", "ja", "en"] if (args.all or args.vosk == "all") else [args.vosk]
        for l in langs:
            key = f"vosk_{l}"
            status = check_model_status(root)
            if not status.get(key, False):
                print(f">>> 开始下载 Vosk [{l}] 模型 (~50MB)...")
                try:
                    download_vosk(lang=l, root=root, progress_callback=make_progress_bar(f"Vosk-{l}"))
                    print(f"[完成] Vosk [{l}] 模型下载与配置完毕！")
                except Exception as e:
                    print(f"[错误] 下载 Vosk [{l}] 失败: {e}")
            else:
                print(f"  Vosk [{l}]: 已存在，跳过下载。")

    show_status(root)
    print("模型配置流程完成！可直接运行应用：")
    print("  GUI 界面: python -m yukkuri.cli --gui")
    print("  CLI 模式: python -m yukkuri.cli --lang zh")
    return 0

if __name__ == "__main__":
    sys.exit(main())

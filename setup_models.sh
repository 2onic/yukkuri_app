#!/usr/bin/env bash
# 自动下载所需 ASR 语音模型与 VAD 模块
# 支持指定下载特定模型与全量下载
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

show_help() {
    echo "使用方式: ./setup_models.sh [选项]"
    echo ""
    echo "选项:"
    echo "  (无参数)              下载默认推荐模型 (Silero-VAD + SenseVoice-Small)"
    echo "  --sensevoice          仅下载 SenseVoice-Small 多语种端到端模型 (约 230MB)"
    echo "  --vad                 仅下载 Silero-VAD 语音活动检测器 (约 630KB)"
    echo "  --vosk [zh|ja|en|all] 下载 Vosk 离线模型 (默认: zh，可选 ja/en/all)"
    echo "  --all                 下载所有模型 (VAD + SenseVoice + Vosk 全部语种)"
    echo "  -h, --help            显示本帮助信息"
    echo ""
    echo "示例:"
    echo "  ./setup_models.sh                  # 推荐：下载默认组合"
    echo "  ./setup_models.sh --vosk zh        # 仅下载 Vosk 中文模型"
    echo "  ./setup_models.sh --all            # 全量下载"
}

# 辅助函数：解压 zip
unzip_file() {
    local zip_file="$1"
    local dest_dir="$2"
    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$zip_file" -d "$dest_dir"
    else
        python3 -c "import zipfile; zipfile.ZipFile('$zip_file').extractall('$dest_dir')"
    fi
}

download_vad() {
    echo ">>> 正在检查 Silero-VAD 语音活动检测器..."
    if [ ! -f "silero_vad.onnx" ]; then
        echo ">>> 正在下载 Silero-VAD (约 630KB)..."
        curl -SL -# -o silero_vad.onnx https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx
        echo ">>> Silero-VAD 下载完成。"
    else
        echo ">>> Silero-VAD 已存在，跳过下载。"
    fi
}

download_sensevoice() {
    echo ">>> 正在检查 SenseVoice-Small 识别模型..."
    local SENSE_DIR="sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    if [ ! -f "$SENSE_DIR/model.int8.onnx" ] && [ ! -f "sensevoice/model.int8.onnx" ]; then
        echo ">>> 正在下载 SenseVoice-Small 模型压缩包 (约 230MB)..."
        curl -SL -# -o sensevoice.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2
        echo ">>> 正在解压 SenseVoice 模型..."
        tar -xvf sensevoice.tar.bz2
        rm -f sensevoice.tar.bz2
        rm -f "$SENSE_DIR/model.onnx"
        ln -sfn "$SENSE_DIR" sensevoice
        echo ">>> SenseVoice-Small 配置完成。"
    else
        echo ">>> SenseVoice-Small 已存在，跳过下载。"
    fi
}

download_vosk_single() {
    local lang="$1"
    local url=""
    local target_dir=""
    local zip_name="vosk_${lang}.zip"

    case "$lang" in
        zh|cn)
            url="https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip"
            target_dir="model_cn"
            top_dir="vosk-model-small-cn-0.22"
            desc="Vosk 中文轻量模型 (约 42MB)"
            ;;
        ja)
            url="https://alphacephei.com/vosk/models/vosk-model-small-ja-0.22.zip"
            target_dir="model_ja"
            top_dir="vosk-model-small-ja-0.22"
            desc="Vosk 日文轻量模型 (约 48MB)"
            ;;
        en)
            url="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
            target_dir="model_en"
            top_dir="vosk-model-small-en-us-0.15"
            desc="Vosk 英文轻量模型 (约 40MB)"
            ;;
        *)
            echo "[错误] 不支持的 Vosk 语种: $lang (支持: zh, ja, en, all)" >&2
            return 1
            ;;
    esac

    echo ">>> 正在检查 $desc..."
    if [ ! -d "$target_dir" ] && [ ! -d "model" ]; then
        echo ">>> 正在下载 $desc..."
        curl -SL -# -o "$zip_name" "$url"
        echo ">>> 正在解压..."
        unzip_file "$zip_name" "."
        rm -f "$zip_name"
        if [ -d "$top_dir" ] && [ "$top_dir" != "$target_dir" ]; then
            rm -rf "$target_dir"
            mv "$top_dir" "$target_dir"
        fi
        echo ">>> $desc 配置完成: $target_dir"
    else
        echo ">>> $target_dir 已存在，跳过下载。"
    fi
}

download_vosk() {
    local target_lang="${1:-zh}"
    if [ "$target_lang" = "all" ]; then
        download_vosk_single zh
        download_vosk_single ja
        download_vosk_single en
    else
        download_vosk_single "$target_lang"
    fi
}

echo "=========================================="
echo "  yukkuri_app - 模型一键配置工具"
echo "=========================================="

if [ $# -eq 0 ]; then
    download_vad
    download_sensevoice
    echo ""
    echo "=== 默认模型准备完成！==="
    echo "提示: 若需使用 Vosk 引擎，可执行: ./setup_models.sh --vosk zh"
    echo "现在可直接运行 yukkuri 或 ./run.sh 启动程序。"
    exit 0
fi

while [ $# -gt 0 ]; do
    case "$1" in
        --help|-h)
            show_help
            exit 0
            ;;
        --vad)
            download_vad
            shift
            ;;
        --sensevoice)
            download_sensevoice
            shift
            ;;
        --vosk)
            shift
            VOSK_LANG="zh"
            if [ $# -gt 0 ] && [[ "$1" != --* ]]; then
                VOSK_LANG="$1"
                shift
            fi
            download_vosk "$VOSK_LANG"
            ;;
        --all)
            download_vad
            download_sensevoice
            download_vosk all
            shift
            ;;
        *)
            echo "[错误] 未知参数: $1" >&2
            show_help
            exit 1
            ;;
    esac
done

echo ""
echo "=== 所选模型配置完成！==="

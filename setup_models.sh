#!/usr/bin/env bash
# 自动下载所需 ASR 语音模型与 VAD 模块
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  油库里实时变声器 - 模型一键配置工具"
echo "=========================================="

# 1. 下载 Silero-VAD 语音活动检测器 (约 630KB)
if [ ! -f "silero_vad.onnx" ]; then
    echo ">>> [1/2] 正在下载 Silero-VAD 语音活动检测器 (约 630KB)..."
    curl -SL -o silero_vad.onnx https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx
else
    echo ">>> [1/2] Silero-VAD 模型已存在，跳过下载。"
fi

# 2. 下载 SenseVoice-Small 多语种端到端模型 (量化版约 230MB)
SENSE_DIR="sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
if [ ! -f "$SENSE_DIR/model.int8.onnx" ] && [ ! -f "sensevoice/model.int8.onnx" ]; then
    echo ">>> [2/2] 正在下载 SenseVoice-Small 多语种端到端语音模型..."
    curl -SL -o sensevoice.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2
    echo ">>> 正在解压 SenseVoice 模型..."
    tar -xvf sensevoice.tar.bz2
    rm -f sensevoice.tar.bz2
    # 移除未量化的 900MB 大模型，保留更快、更小 (229MB) 的 model.int8.onnx
    rm -f "$SENSE_DIR/model.onnx"
    ln -sfn "$SENSE_DIR" sensevoice
else
    echo ">>> [2/2] SenseVoice 模型已存在，跳过下载。"
fi

echo ""
echo "=== 模型准备完成！==="
echo "现在可以直接执行 ./run.sh 启动油库里实时语音转换器。"

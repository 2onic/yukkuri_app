#!/usr/bin/env bash
# 自动下载所需 ASR 语音模型与 VAD 模块
# 支持指定下载特定模型与全量下载
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RESOLVED_PYTHON=""
for py in python3 python py; do
    if command -v "$py" >/dev/null 2>&1; then
        RESOLVED_PYTHON="$py"
        break
    fi
done

show_help() {
    echo "使用方式: ./setup_models.sh [选项]"
    echo ""
    echo "选项:"
    echo "  (无参数)              下载默认推荐模型 (Silero-VAD + SenseVoice-Small)"
    echo "  --sensevoice          仅下载 SenseVoice-Small 多语种端到端模型 (约 155MB)"
    echo "  --vad                 仅下载 Silero-VAD 语音活动检测器 (约 630KB)"
    echo "  --vosk [zh|ja|en|all] 下载 Vosk 离线模型 (默认: zh，可选 ja/en/all)"
    echo "  --aquestalk [zip|dir] 配置 AquesTalk1 多声线合成库 (支持传入 zip、目录或自动检测)"
    echo "  --all                 配置所有模型 (VAD + SenseVoice + Vosk 全部语种 + AquesTalk)"
    echo "  -h, --help            显示本帮助信息"
    echo ""
    echo "示例:"
    echo "  ./setup_models.sh                  # 推荐：配置默认组合"
    echo "  ./setup_models.sh --aquestalk      # 自动扫描或引导配置 AquesTalk 声线"
    echo "  ./setup_models.sh --vosk zh        # 仅下载 Vosk 中文模型"
    echo "  ./setup_models.sh --all            # 全量配置"
}

# 辅助函数：解压 zip
unzip_file() {
    local zip_file="$1"
    local dest_dir="$2"
    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$zip_file" -d "$dest_dir"
    elif [ -n "$RESOLVED_PYTHON" ]; then
        "$RESOLVED_PYTHON" -c "import zipfile; zipfile.ZipFile('$zip_file').extractall('$dest_dir')"
    else
        echo "[错误] 缺少 unzip 或 Python，无法解压 $zip_file" >&2
        return 1
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
    local SENSE_DIR="sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
    local SENSE_OLD_DIR="sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    if [ -f "$SENSE_DIR/model.int8.onnx" ] || [ -f "$SENSE_OLD_DIR/model.int8.onnx" ] || [ -f "sensevoice/model.int8.onnx" ]; then
        echo ">>> SenseVoice-Small 已存在，跳过下载。"
        return 0
    fi

    local ARCHIVE="sensevoice.tar.bz2"
    local URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2"

    if [ ! -s "$ARCHIVE" ]; then
        echo ">>> 正在下载 SenseVoice-Small 模型压缩包 (官方精简版，约 155MB)..."
        curl -SL -# -o "$ARCHIVE" "$URL"
    else
        echo ">>> 检测到本地已存在 $ARCHIVE，直接进行解压..."
    fi

    echo ">>> 正在解压 SenseVoice 模型..."
    local EXTRACT_OK=0
    # 优先使用系统原生 tar (C 语言实现，比 Python 解压 bz2 快数十倍且不消耗 Python 内存)
    if command -v tar >/dev/null 2>&1; then
        if tar --exclude="*model.onnx" -xf "$ARCHIVE" 2>/dev/null || tar -xf "$ARCHIVE" 2>/dev/null; then
            EXTRACT_OK=1
        fi
    fi

    # 若系统没有 tar 或 tar 失败，回退至 Python 纯流式单遍解压 (严禁使用 tar.getmembers() 避免 1GB bz2 倒回寻址死循环)
    if [ $EXTRACT_OK -eq 0 ] && [ -n "$RESOLVED_PYTHON" ]; then
        "$RESOLVED_PYTHON" -c "
import tarfile, sys
kw = {'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}
try:
    with tarfile.open('$ARCHIVE', 'r|bz2') as tar:
        for m in tar:
            if m.name.endswith('model.onnx'):
                continue
            tar.extract(m, '.', **kw)
    sys.exit(0)
except Exception as e:
    sys.exit(1)
" && EXTRACT_OK=1
    fi

    if [ $EXTRACT_OK -ne 1 ]; then
        echo "[错误] 解压 SenseVoice 模型失败！" >&2
        return 1
    fi

    rm -f "$ARCHIVE"
    rm -f "$SENSE_DIR/model.onnx" "$SENSE_OLD_DIR/model.onnx" 2>/dev/null || true

    # 确定解压出的实际目录名
    local TARGET_DIR=""
    if [ -d "$SENSE_DIR" ]; then
        TARGET_DIR="$SENSE_DIR"
    elif [ -d "$SENSE_OLD_DIR" ]; then
        TARGET_DIR="$SENSE_OLD_DIR"
    fi

    # 建立软链接 sensevoice
    if [ -n "$TARGET_DIR" ] && [ ! -e "sensevoice" ]; then
        ln -sfn "$TARGET_DIR" sensevoice 2>/dev/null || true
    fi
    echo ">>> SenseVoice-Small 配置完成。"
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

setup_aquestalk() {
    local src="$1"
    local target_dir="libs/aquestalk/lib64"
    mkdir -p "$target_dir"

    echo ">>> 正在检查 AquesTalk1 多声线合成库..."
    if [ -z "$RESOLVED_PYTHON" ]; then
        echo "[警告] 未找到 Python 解释器，跳过 AquesTalk 自动配置。"
        return 0
    fi

    if [ -n "$src" ]; then
        if [[ "$src" =~ ^https?:// ]]; then
            echo ">>> 正在从指定 URL 下载 AquesTalk 压缩包: $src ..."
            curl -SL -# -o aquestalk_tmp.zip "$src"
            unzip_file aquestalk_tmp.zip "libs/aquestalk_tmp"
            rm -f aquestalk_tmp.zip
            "$RESOLVED_PYTHON" -c "from yukkuri.model_downloader import install_aquestalk_from_dir; install_aquestalk_from_dir('libs/aquestalk_tmp')"
            rm -rf "libs/aquestalk_tmp"
        elif [ -f "$src" ]; then
            echo ">>> 正在从指定文件安装 AquesTalk 压缩包: $src ..."
            "$RESOLVED_PYTHON" -c "from yukkuri.model_downloader import install_aquestalk_from_archive; install_aquestalk_from_archive('$src')"
        elif [ -d "$src" ]; then
            echo ">>> 正在从指定目录导入 AquesTalk: $src ..."
            "$RESOLVED_PYTHON" -c "from yukkuri.model_downloader import install_aquestalk_from_dir; install_aquestalk_from_dir('$src')"
        else
            echo "[错误] 指定的 AquesTalk 文件或目录不存在: $src" >&2
            return 1
        fi
    else
        # 尝试自动检测本地已存在的安装包或解压目录
        local result
        result=$("$RESOLVED_PYTHON" -c "
from yukkuri.model_downloader import auto_detect_and_install_aquestalk, check_model_status
status = check_model_status()
if status['aquestalk']:
    print('ALREADY_OK:' + ','.join(status['aquestalk_voices']))
else:
    res = auto_detect_and_install_aquestalk()
    if res:
        print('INSTALLED:' + ','.join(res))
    else:
        print('NOT_FOUND')
" 2>/dev/null || echo "NOT_FOUND")

        if [[ "$result" == ALREADY_OK:* ]]; then
            local voices="${result#ALREADY_OK:}"
            echo ">>> AquesTalk 多声线库已就绪 (可用声线: $voices)，跳过配置。"
            return 0
        elif [[ "$result" == INSTALLED:* ]]; then
            local voices="${result#INSTALLED:}"
            echo ">>> 成功自动发现并配置本地 AquesTalk 多声线库！(可用声线: $voices)"
            return 0
        fi

        # 未自动找到，输出官方合规下载指引
        echo "========================================================================"
        echo "【提示】AquesTalk1 属于株式会社 AQUEST (Aquest Corp.) 专有版权软件。"
        echo "根据官方授权协议，本项目不得在代码仓库中附带分发该动态库，需用户自行获取。"
        echo ""
        echo "获取与配置步骤："
        echo "  1. 浏览器访问 AQUEST 官方下载页："
        echo "     https://www.a-quest.com/download.html"
        echo "  2. 找到 'AquesTalk1 Linux' (Ver.2.0.0)，点击 Download 下载 aqtk1_lnx_200.zip"
        echo "  3. 将下载的 aqtk1_lnx_200.zip 放入当前目录，或运行："
        echo "     ./setup_models.sh --aquestalk /路径/to/aqtk1_lnx_200.zip"
        echo "     (若已解压，也可直接传入解压目录: ./setup_models.sh --aquestalk /路径/to/aqtk1_lnx)"
        echo "========================================================================"
        return 0
    fi

    # 验证最终安装声线
    "$RESOLVED_PYTHON" -c "
from yukkuri.config import AppConfig
cfg = AppConfig()
voices = cfg.get_available_voices()
if voices:
    print('>>> AquesTalk 声线配置成功，当前可用:', ', '.join(voices.keys()))
else:
    print('[警告] 未能识别到有效的 libAquesTalk.so 库文件')
"
}

echo "=========================================="
echo "  yukkuri_app - 模型一键配置工具"
echo "=========================================="

if [ $# -eq 0 ]; then
    download_vad
    download_sensevoice
    setup_aquestalk
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
        --aquestalk)
            shift
            AQ_SRC=""
            if [ $# -gt 0 ] && [[ "$1" != --* ]]; then
                AQ_SRC="$1"
                shift
            fi
            setup_aquestalk "$AQ_SRC"
            ;;
        --all)
            download_vad
            download_sensevoice
            download_vosk all
            setup_aquestalk
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

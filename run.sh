#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 自动加载本地私有 .env 环境变量文件
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    . "$SCRIPT_DIR/.env"
    set +a
fi

# 智能探测可用 Python 解释器
# 1. 优先使用环境变量指定的 PYTHON_CMD
if [ -n "$PYTHON_CMD" ] && [ -x "$PYTHON_CMD" ]; then
    RESOLVED_PYTHON="$PYTHON_CMD"
# 2. 如果当前终端已经激活了包含依赖的环境
elif [ -n "$CONDA_PREFIX" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
    RESOLVED_PYTHON="$CONDA_PREFIX/bin/python"
# 3. 搜索常见 Conda 虚拟环境路径
elif [ -x "$HOME/miniforge3/envs/yukkuri/bin/python" ]; then
    RESOLVED_PYTHON="$HOME/miniforge3/envs/yukkuri/bin/python"
elif [ -x "$HOME/miniconda3/envs/yukkuri/bin/python" ]; then
    RESOLVED_PYTHON="$HOME/miniconda3/envs/yukkuri/bin/python"
elif [ -x "$HOME/anaconda3/envs/yukkuri/bin/python" ]; then
    RESOLVED_PYTHON="$HOME/anaconda3/envs/yukkuri/bin/python"
# 4. 回退到系统 python3
elif command -v python3 >/dev/null 2>&1; then
    RESOLVED_PYTHON="python3"
else
    echo "[错误] 未找到可用的 Python 解释器！" >&2
    exit 1
fi

export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"
exec "$RESOLVED_PYTHON" -m yukkuri.cli "$@"

#!/usr/bin/env bash
set -e

# 默认优先使用已配置好依赖的 yukkuri conda 环境
CONDA_PYTHON="/home/colimy/miniforge3/envs/yukkuri/bin/python"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$CONDA_PYTHON" ]; then
    PYTHON_CMD="$CONDA_PYTHON"
else
    PYTHON_CMD="python3"
fi

exec "$PYTHON_CMD" "$SCRIPT_DIR/yukkuri_bridge.py" "$@"

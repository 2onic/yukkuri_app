#!/usr/bin/env bash
# 配置 PipeWire 虚拟麦克风节点 (yukkuri_sink -> yukkuri_source)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="$HOME/.config/pipewire/pipewire.conf.d"
CONF_FILE="$TARGET_DIR/99-yukkuri-mic.conf"

echo ">>> 正在配置 PipeWire 虚拟麦克风..."
mkdir -p "$TARGET_DIR"
cp "$SCRIPT_DIR/config/99-yukkuri-mic.conf" "$CONF_FILE"

echo ">>> 配置文件已写入: $CONF_FILE"
echo ">>> 正在重启 PipeWire 服务以生效..."

systemctl --user restart pipewire pipewire-pulse wireplumber 2>/dev/null || true

echo ""
echo "=== 配置完成！==="
echo "现在系统已包含虚拟设备:"
echo "  - 输出目标 (Sink): yukkuri_sink"
echo "  - 麦克风输入 (Source): yukkuri_source (Yukkuri Virtual Mic)"
echo "你可以在 Discord / OBS / 会议软件中直接选择 'Yukkuri Virtual Mic' 作为麦克风输入。"

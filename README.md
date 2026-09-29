# yukkuri_app

[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20PipeWire-blue.svg)](https://pipewire.org/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![Engine](https://img.shields.io/badge/ASR-SenseVoice%20%7C%20Vosk-orange.svg)](https://github.com/FunAudioLLM/SenseVoice)
[![TTS](https://img.shields.io/badge/TTS-AquesTalk1-red.svg)](https://www.a-quest.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个运行于 Linux (PipeWire) 下的**实时语音转油库里音效**工具。

说出普通话、英语或日语，程序将实时识别，并通过 **AquesTalk1** 引擎实时合成出油库里语音，注入到虚拟麦克风节点中。可在 Discord、腾讯会议、OBS中直接作为麦克风使用。

---

## 核心特性

- **经典油库里空耳调教 (Polyglot G2P)**：
  - **中文**：自动将汉字转为拼音并映射为油库里假名音标（如 *“你好”* -> `にー/はお`，*“我是油库里”* -> `うぉ/しー/ゆっくり`）；
  - **英文**：常用词外来语化 + 音节音译 + 字母拼读（如 *“Hello world”* -> `へろー/わーるど`，*“CPU”* -> `しーぴーゆー`）；
  - **日文**：原生假名合成，自动纠偏助词读音（`は/へ` -> `わ/え`）。
  - **中英日数字混排**：无需手动切换语种，支持混合。
- **异步双缓冲队列推流**：麦克风采集、VAD 检测与 TTS 合成/播放解耦，不阻塞录音。
- **PipeWire 虚拟声卡原生集成**：自动将音频送入虚拟麦克风（`Yukkuri Virtual Mic`）。

---

## 系统架构

```mermaid
flowchart LR
    A[真实麦克风采集] --> B[Silero-VAD 端点检测]
    B -->|人声片段| C[SenseVoice 语音识别]
    C -->|中/英/日 文本| D[Polyglot G2P 音标转换]
    D -->|AquesTalk假名音标| E[AquesTalk1 动态库合成]
    E -->|8kHz 油库里音频| F[pw-play 管道推流]
    F --> G[yukkuri_sink 虚拟声卡]
    G --> H[虚拟麦克风<br>Discord / OBS / 语音软件]
```

---

## 快速上手

### 1. 克隆仓库与安装依赖

```bash
git clone git@github.com:2onic/yukkuri_app.git
cd yukkuri_app

# 安装依赖并注册全局 yukkuri 命令
pip install -e .
```

### 2. 下载语音模型

你可以通过命令行脚本下载，或者在启动 GUI 界面后点击【语音模型管理与下载】一键下载：

```bash
chmod +x setup_models.sh

# 默认推荐：下载 Silero-VAD + SenseVoice-Small（约 230MB）
./setup_models.sh

# 可选：下载 Vosk 离线模型 (支持 zh / ja / en)
./setup_models.sh --vosk zh

# 可选：全量下载所有模型
./setup_models.sh --all
```

### 3. 运行转换器

程序支持通过桌面图形界面（GUI）或轻量终端命令行运行，且支持自动通过 `pactl` 动态创建与清理虚拟麦克风：

#### 方式 A：启动现代桌面图形界面 (GUI，推荐)
```bash
# 直接使用全局 GUI 命令
yukkuri-gui

# 或者通过参数 / 启动脚本运行
yukkuri --gui
./run.sh --gui
```
> **GUI 特色**：
> - 麦克风设备可视化；
> - 语速与 VAD 停顿断句灵敏度滑块实时调整；
> - 原文识别、假名音标与延迟耗时统计面板；
> - 快捷文本试听推流框（无需说话即可一键播报）。

#### 方式 B：终端命令行启动 (CLI)
```bash
# 全局命令运行
yukkuri

# 或者通过脚本启动
./run.sh
```

现在对着麦克风说话，并在 Discord / QQ / OBS 中将音频输入设备选择为 **`Yukkuri Virtual Mic`** 即可。

> **提示（静态声卡配置）**：如果你希望在系统启动时常驻虚拟麦克风设备，也可以运行可选脚本 `./setup_virtual_mic.sh` 写入 PipeWire 静态配置文件。

---

## 进阶参数说明

`yukkuri` 命令与 `./run.sh` 支持以下自定义命令行参数：

| 参数 | 默认值 | 作用说明 |
| :--- | :--- | :--- |
| `--engine` | `sensevoice` | 识别引擎：`sensevoice`（默认高精度端到端）或 `vosk`（轻量传统） |
| `--speed` | `100` | 油库里说话语速（推荐范围: `70` ~ `160`） |
| `--target` | `yukkuri_sink` | PipeWire 推流目标 sink 名称 |
| `--device` | 系统默认 | 指定输入的实体麦克风设备 ID |
| `--list-devices` | - | 列出当前系统的所有音频输入输出设备及其 ID |
| `--lang` | `zh` | 发音/模型语种（SenseVoice 自动支持多语种；Vosk 模式下切换模型） |

#### 常用命令示例：

```bash
# 查看所有输入设备编号
./run.sh --list-devices

# 指定麦克风设备 ID（例如 14）并调快语速至 120
./run.sh --device 14 --speed 120

# 切换为日文语境发音
./run.sh --lang ja

# 切换为轻量 Vosk 引擎
./run.sh --engine vosk --lang zh
```

---

## 版权与免责声明

1. **AquesTalk1**：
   - 本项目调用的语音合成动态库 `libAquesTalk.so` 属于 **[株式会社アクエスト (Aquest Corp.)](https://www.a-quest.com/)** 的版权财产；
   - 个人非商业用途请遵守官方使用条款。如需商业用途，请向 AQUEST 申请正式商业授权。
2. **SenseVoice**：
   - 语音识别模型属于阿里巴巴通义实验室开源项目，遵循 Apache-2.0 开源协议。
3. **免责声明**：
   - 本工具仅供个人娱乐、语音技术交流及二创研究使用，请勿用于侵犯他人合法权益或违规场景。

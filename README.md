# yukkuri_app

[![Platform](https://img.shields.io/badge/Platform-Linux%20(PipeWire)%20%7C%20Windows%20(WASAPI)-blue.svg)](https://github.com/2onic/yukkuri_app)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![Engine](https://img.shields.io/badge/ASR-SenseVoice%20%7C%20Vosk-orange.svg)](https://github.com/FunAudioLLM/SenseVoice)
[![TTS](https://img.shields.io/badge/TTS-AquesTalk1-red.svg)](https://www.a-quest.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个跨平台的**实时语音转油库里音效**虚拟麦克风工具（支持 Linux PipeWire 与 Windows WASAPI）。

说出普通话、英语或日语，程序将实时识别，并通过 **AquesTalk1** 引擎实时合成出油库里语音，注入到虚拟麦克风节点中。可在 Discord、QQ、微信、腾讯会议、OBS 等语音开黑或直播软件中直接作为麦克风使用。

---

## 核心特性

- **多声线自由切换 (Multi-Voice Switch)**：
  - 支持 **f1**、**f2**、**f3**、**m1/m2**、**imd1**、**jgr**、**dvd**、**r1**共 9 种声线；
  - GUI 界面支持运行中**实时热切换**，命令行支持 `--voice` 选项。
- **经典油库里空耳调教 (Polyglot G2P)**：
  - **中文**：自动将汉字转为拼音并映射为油库里假名音标（如 *“你好”* -> `にー/はお`，*“我是油库里”* -> `うぉ/しー/ゆっくり`）；
  - **英文**：常用词外来语化 + 音节音译 + 字母拼读（如 *“Hello world”* -> `へろー/わーるど`，*“CPU”* -> `しーぴーゆー`）；
  - **日文**：原生假名合成，自动纠偏助词读音（`は/へ` -> `わ/え`）。
  - **中英日数字混排**：无需手动切换语种，支持混合。
- **异步双缓冲队列推流**：麦克风采集、VAD 检测与 TTS 合成/播放解耦，不阻塞录音。
- **跨平台虚拟麦克风深度适配 (零系统污染)**：
  - **Linux**：通过 PipeWire / pactl 原生直连（`pw-play --target yukkuri_sink`），自动动态创建与释放虚拟麦克风（`Yukkuri Virtual Mic`）。
  - **Windows**：通过 VB-Audio Virtual Cable + WASAPI 专有输出，内置自动采样率协商与 8000Hz Mono -> 48000Hz Stereo 升混重采样，无缝对齐 Discord / OBS (`CABLE Output`)。

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

### 2. 下载语音模型与配置 AquesTalk 声线库

你可以通过命令行脚本配置，或者在启动 GUI 界面后点击【语音模型与声线库管理】一键导入：

```bash
# 跨平台一键配置 (Windows / Linux 通用)：下载 Silero-VAD + SenseVoice 并自动扫描 AquesTalk
python setup_models.py

# 导入 AquesTalk 多声线库 (支持 zip 压缩包、解压目录或 dll/so 库路径；留空则自动扫描)
python setup_models.py --aquestalk [路径]

# 检查当前所有模型就绪状态
python setup_models.py --check

# Linux 环境亦可直接执行脚本：
./setup_models.sh
```

> **注意（AquesTalk 专有授权）**：
> `libAquesTalk.so` / `AquesTalk.dll` 属于 **[株式会社アクエスト (Aquest Corp.)](https://www.a-quest.com/)** 的专有财产，本项目不自带打包。
> 请前往 [AQUEST 官方下载页](https://www.a-quest.com/download.html) 获取相应平台的评价版，然后通过 `python setup_models.py --aquestalk` 或 GUI 向导导入即可解锁全套 9 种声线。

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
> - 耳机实时回放监听开关（一键自听合成效果，无需手动执行后台命令）；
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
| `--voice` | `f1` | 油库里声线：`f1`, `f2`, `f3`, `m1`, `m2`, `imd1`, `jgr`, `dvd`, `r1` |
| `--speed` | `100` | 油库里说话语速（推荐范围: `70` ~ `160`） |
| `--target` | `yukkuri_sink` | PipeWire 推流目标 sink 名称 |
| `--loopback`, `--monitor` | 关闭 | 启动耳机实时回放监听（将虚拟麦克风声音自动回放至默认耳机/扬声器，退出时自动清理） |
| `--device` | 系统默认 | 指定输入的实体麦克风设备 ID |
| `--list-devices` | - | 列出当前系统的所有音频输入输出设备及其 ID |
| `--lang` | `zh` | 发音/模型语种（SenseVoice 自动支持多语种；Vosk 模式下切换模型） |

#### 常用命令示例：

```bash
# 查看所有输入设备编号
./run.sh --list-devices

# 启动并开启耳机实时自听回放
./run.sh --loopback

# 使用女声2 (f2) 运行
./run.sh --voice f2

# 使用男声1 (m1) 运行
./run.sh --voice m1

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
   - 本项目本身**不打包、不分发任何 AquesTalk 二进制专有动态库**；
   - 语音合成引擎及动态库（`libAquesTalk.so` / `AquesTalk.dll`）属于 **[株式会社アクエスト (Aquest Corp.)](https://www.a-quest.com/)** 的版权财产，不受本项目 MIT 协议管辖；
   - 个人非商业用途请遵守官方使用条款。如需商业用途，请向 AQUEST 申请正式商业授权。
2. **开源组件与模型**：
   - SenseVoice、sherpa-onnx、Vosk 遵循 Apache-2.0 开源协议；
   - Silero VAD、CustomTkinter 遵循 MIT 开源协议。
3. **免责声明**：
   - 本工具仅供个人娱乐、语音技术交流及二创研究使用；
   - 使用者通过本工具采集、合成与广播的任何音频内容，其合规性与法律责任由使用者自行承担，请勿用于侵犯他人合法权益或违法违规场景。

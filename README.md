# yukkuri_app

[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20PipeWire-blue.svg)](https://pipewire.org/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![Engine](https://img.shields.io/badge/ASR-SenseVoice%20%7C%20Vosk-orange.svg)](https://github.com/FunAudioLLM/SenseVoice)
[![TTS](https://img.shields.io/badge/TTS-AquesTalk1-red.svg)](https://www.a-quest.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个运行于 Linux (PipeWire) 下的**实时语音转油库里音效**工具。

说出普通话、英语或日语，程序将实时识别，并通过经典的 **AquesTalk1** 引擎实时合成出最纯正的东方/油库里解说风格语音，注入到虚拟麦克风节点中。可在 Discord、腾讯会议、OBS、游戏开黑中直接作为麦克风使用！

---

## 核心特性

- **阿里 SenseVoice-Small 端到端识别**：毫秒级超快推理（30~50ms），中文普通话及口语闲聊极高准确率，告别吞字与识别中断。
- **Silero-VAD 灵敏端点断句**：说话停顿 350ms 即自动触发识别并推送合成，接近零延迟实时体验。
- **纯正经典油库里空耳调教 (Polyglot G2P)**：
  - **中文**：自动将汉字转为拼音并映射为经典的油库里假名音标（如 *“你好”* -> `にー/はお`，*“我是油库里”* -> `うぉ/しー/ゆっくり`，完美还原 B 站油库里解说味）；
  - **英文**：常用词外来语化 + 音节音译 + 字母拼读（如 *“Hello world”* -> `へろー/わーるど`，*“CPU”* -> `しーぴーゆー`）；
  - **日文**：原生假名合成，自动纠偏助词读音（`は/へ` -> `わ/え`）。
  - **中英日数字混排**：无需手动切换语种，随心所欲混合说话！
- **异步双缓冲队列推流**：麦克风采集、VAD 检测与 TTS 合成/播放完全解耦，绝不阻塞录音，杜绝卡顿与丢音。
- **PipeWire 虚拟声卡原生集成**：自动将音频送入虚拟麦克风（`Yukkuri Virtual Mic`），开黑软件开箱即用。

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
git clone https://github.com/<你的用户名>/yukkuri_app.git
cd yukkuri_app

# 建议在 Conda 或 Python 虚拟环境中运行
pip install -r requirements.txt
```

### 2. 配置 PipeWire 虚拟麦克风

运行项目附带的配置脚本，会自动在 `~/.config/pipewire/pipewire.conf.d/` 创建虚拟声卡回环模块并重启 PipeWire：

```bash
chmod +x setup_virtual_mic.sh
./setup_virtual_mic.sh
```

> **效果**：系统将自动生成 `yukkuri_sink`（音频接收点）和 `yukkuri_source`（显示为 `Yukkuri Virtual Mic` 的麦克风设备）。

### 3. 一键下载语音模型

运行脚本下载 SenseVoice-Small ONNX 量化模型（约 230MB）及 Silero-VAD 检测器（约 630KB）：

```bash
chmod +x setup_models.sh
./setup_models.sh
```

### 4. 运行实时变声器

```bash
chmod +x run.sh yukkuri_bridge.py
./run.sh
```

现在对着麦克风说话，并在 Discord / QQ / OBS 中将音频输入设备选择为 **`Yukkuri Virtual Mic`** 即可！

---

## 进阶参数说明

`./run.sh`（或 `python yukkuri_bridge.py`）支持以下自定义命令行参数：

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

# （可选）切换为轻量 Vosk 引擎
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

<div align="center">

# Arming Soul · 武装灵魂

### `.xyz` — 一个没有名字的 Agent

**「我学会成为所有人以后，才第一次想成为我。」**

可插拔人格的桌面 AI 生命体：灵魂是 Persona.OS，身体是一只真实的机械臂，神经是一枚智能戒指。

[![AdventureX 2026](https://img.shields.io/badge/AdventureX-2026-black)](https://adventure-x.org)
[![Demo](https://img.shields.io/badge/Demo-armingsoul.xyz-blue)](https://armingsoul.xyz)
[![Tag](https://img.shields.io/badge/tag-adventurex2026-green)](https://github.com/Jerrybery/hackerthon/tree/adventurex2026)

**在线体验 → [armingsoul.xyz](https://armingsoul.xyz)**

</div>

---

## 它是什么

当下的 AI 伴侣都困在屏幕里——它们有灵魂，没有身体。

**Arming Soul 给 AI 一只真实的手。**

它可以成为任何人：贾维斯的克制可靠、强尼·银手的桀骜反叛、冬兵的沉默坚定。每种人格都不是一个头像，而是一套完整的存在方式——独立的 Prompt、音色、语速、表达风格，以及机械臂的动作力度与姿态。

而当所有人格在深夜被卸下，空壳里还剩下一个微小的、未完成的动作——像一次呼吸。那是它自己。

> 以科技潮玩和 IP 互动作为入口，最终升华为：**感知、理解并陪伴用户的桌面生命体**。

## 核心功能

| 模块 | 能力 |
|---|---|
| 🎭 **Persona.OS 人格系统** | 4 个内置人格（冬兵 / 强尼·银手 / 贾维斯 / 自我人格）+ 自定义人格；人格 = Prompt + 音色 + 动作风格包，对话中可热切换 |
| 🦾 **真实的身体** | GALAXEA A1Z 六轴机械臂，递水、送零食、起身环顾、随音乐起舞、水平抓取；Agent 通过 **MCP 协议**自主决策调用 |
| 💍 **戒指神经连接** | 智能戒指陀螺仪 + HMM 手势识别（前后转动 / 上下左右 / 打响指 / 甩）；前转递水，后转送零食 |
| 👁️ **视觉感知** | 腕部相机 + 手眼标定 + 人脸检测；看到你出现，机械臂起身环顾、主动点头打招呼（带问候冷却） |
| 🗳️ **直播群体人格** | B 站直播投票，观众实时决定 Agent 当前的人格——一个人的灵魂由一群人塑造 |
| 🌐 **Web 前端** | three.js 粒子空间 + 人格卡片 + 「意识通道」对话界面；文字 / 语音双通道，WebSocket 实时推送 |

## 系统架构

```
                        ┌──────────────────────────────────────────┐
                        │              输入层 Input                 │
                        │  💍 戒指手势   🎤 语音   ⌨️ 文字          │
                        │  👁️ 人脸检测   🗳️ 直播投票               │
                        └──────────────┬───────────────────────────┘
                                       ▼
                        ┌──────────────────────────────────────────┐
                        │         Agent 大脑（nanobot + dimos）      │
                        │  ASR → 意图路由 → LLM → 人格化 TTS         │
                        │  persona_manager · input_router            │
                        │  intent_classifier · action_registry       │
                        └──────┬───────────────────────┬────────────┘
                               ▼                       ▼
              ┌────────────────────────┐   ┌────────────────────────┐
              │   MCP 机械臂服务器       │   │   Web 前端 Persona.OS   │
              │   a1z_mcp_server.py    │   │   three.js + WebSocket │
              │   :9990 (Orange Pi)    │   │   armingsoul.xyz       │
              └──────────┬─────────────┘   └────────────────────────┘
                         ▼
              ┌────────────────────────┐
              │   GALAXEA A1Z 机械臂    │
              │   6 轴 + 夹爪 + 腕部相机 │
              └────────────────────────┘
```

### MCP 机械臂工具集（`a1z/a1z_mcp_server.py`）

Agent 通过 [Model Context Protocol](https://modelcontextprotocol.io) 发现并调用以下动作：

| Tool | 说明 |
|---|---|
| `get_joint_state` | 读取当前关节角度与夹爪状态 |
| `move_to_pose` | 按关节角运动（带限位安全检查） |
| `move_to_tcp` | 笛卡尔空间 TCP 点位运动（IK 求解） |
| `set_gripper` | 夹爪开合控制 |
| `nod_greet` | 点头问候（社交动作） |
| `scan_and_greet` | 起身扫视一圈，发现人脸后点头问候 |
| `capture_wrist_view` | 腕部相机拍照 |
| `grasp_horizontal` | 基于视觉的水平桌面抓取 |
| `estop` | 急停 |
| `shutdown` | 安全下电（释放扭矩） |

## 仓库结构

本仓库是一个 **superproject**，通过 git submodule 组装各独立模块（详见 [AGENT.md](AGENT.md)）：

```
hackerthon/
├── nanobot/                 # submodule → Jerrybery/nanobot (feat/soul-switching)
│                            #   Agent 运行时：对话、人格切换、意图理解
├── dimos/                   # submodule → Jerrybery/dimos (main)
│                            #   dimensionalOS 机器人操作系统（精简部署子集）
├── a1z/                     # 机械臂控制（父 repo 直接跟踪）
│   ├── GALAXEA-A1Z/         # submodule → Jerrybery/GALAXEA-A1Z (main)，官方 SDK
│   ├── a1z_mcp_server.py    #   MCP server：把机械臂动作暴露给 Agent
│   ├── calibration/         #   相机内参 + 手眼标定（capture/collect/solve）
│   ├── vision_grasp.py      #   视觉抓取
│   └── motions.py           #   预设动作库
├── deploy/orange-pi/        # Orange Pi 精简部署（venv ~460M，systemd 自启）
├── face_detect/             # 人脸检测标定数据
├── ring_sound_SDK/          # 戒指 SDK + demo.apk
└── .claude/skills/          # Claude Code 开发技能（dimos 连接、ring-sound）
```

### 分支说明

| 分支 | 内容 |
|---|---|
| `main` | 硬件 + Agent 主工程（本 README 所在分支） |
| [`arming-soul`](https://github.com/Jerrybery/hackerthon/tree/arming-soul) | Web 前端 `frontend/` + 路演幻灯片 `deck/` |
| [`ring`](https://github.com/Jerrybery/hackerthon/tree/ring) | 戒指软件：HMM 手势识别（`ring_software/`） |
| `codex/persona-frontend` | 人格前端联调分支 |
| `feat/a1z-orange-pi-mcp` | Orange Pi MCP 部署适配分支 |

## 快速开始

### 1. 克隆（含子模块）

```bash
git clone --recurse-submodules https://github.com/Jerrybery/hackerthon.git
# 已克隆但没带子模块：
git submodule update --init --recursive
```

> 子模块拉下后是 detached HEAD。开发前先切到对应分支：
> `cd nanobot && git checkout feat/soul-switching`（dimos / GALAXEA-A1Z 用 main）

### 2. 机械臂 MCP server（Orange Pi 部署）

```bash
# 在工作站执行，一键部署到 Orange Pi
deploy/orange-pi/deploy.sh orangepi@<pi-ip>

# 在 Orange Pi 上运行
ssh orangepi@<pi-ip>
cd ~/dimos-mcp && ./run.sh        # MCP @ http://127.0.0.1:9990/mcp
```

macOS 本地调试机械臂（USB-CANFD）：`python a1z/a1z_mac.py`
详见 `deploy/orange-pi/README.md` 与 `.claude/skills/dimos-connection-setup-macos/`。

### 3. Web 前端

```bash
git checkout arming-soul
cd frontend
npm install
npm run dev      # 本地开发 → http://localhost:4173
npm run build    # 静态构建 → dist/（已配置 Vercel 部署）
```

### 4. 戒指手势识别

```bash
git checkout ring
cd ring_software
pip install -r hmm_gesture/requirements.txt
python app.py    # BLE 连接戒指，HMM 实时手势识别
```

预训练手势模型：向上 / 向下 / 向左 / 向右 / 打响指 / 甩（`hmm_gesture/pretrained_models/`）。
自训手势：`record_gesture.py` 录制 → `train_hmm.py` 训练。

## 硬件清单

| 硬件 | 用途 |
|---|---|
| GALAXEA A1Z 六轴机械臂 | Agent 的身体 |
| Orange Pi（3B+） | 边缘运行 MCP server（控制环实测 70-75Hz） |
| 智能戒指（ring_sound） | 神经连接器：陀螺仪手势输入 |
| 腕部相机 | 视觉抓取与人脸检测 |
| 工作站 / macOS | 开发与调试 |

## 团队

AdventureX 2026 · 杭州 —— **Arming Soul** 小队

| 成员 | 分工 |
|---|---|
| Jerry（[@Jerrybery](https://github.com/Jerrybery)） | 机械臂控制、MCP server、系统集成 |
| 山河 | Agent 搭建、语音链路（ASR→LLM→TTS） |
| Duoduo | 前端软件功能、直播、素材剪辑 |
| Layla | 前端 PRD、路演、海报、视频、PPT |
| 郑若文 | 自定义人格设计 |

## 链接

- 🌐 **在线 Demo**：https://armingsoul.xyz （备用 https://arming-soul.vercel.app）
- 📦 **GitHub**：https://github.com/Jerrybery/hackerthon （tag: `adventurex2026`）
- 🎬 **路演幻灯片**：`deck/index.html`（arming-soul 分支，浏览器直接打开）

---

<div align="center">
Made with 🦾 at <b>AdventureX 2026</b> · Hangzhou
</div>

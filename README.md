# Arming Soul — Web 前端 & 路演幻灯片

> 本分支是 **Arming Soul** 项目的软件表现层：Persona.OS Web 前端 + AdventureX 2026 路演 deck。
> 项目总览与硬件/Agent 部分见 [`main` 分支](https://github.com/Jerrybery/hackerthon)。

## 目录结构

```
├── frontend/     # Persona.OS Web 前端（three.js，原生 ES Modules，无框架）
└── deck/         # 路演幻灯片（单文件 HTML，motion 动画，浏览器直接打开）
```

## frontend — Persona.OS

「选择一个意识载体」——人格选择 +「意识通道」对话界面。

**功能块**

| 模块 | 说明 |
|---|---|
| `persona_selector` | 人格卡片展示，点击发送 persona_id |
| `current_persona` | 当前人格名称、头像、音色状态 |
| `text_chat` / `voice_chat` | 文字对话 / 麦克风语音输入 |
| `audio_player` | TTS 音频播放，支持打断 |
| `action_status` | 机械臂动作状态（等待/执行中/成功/失败） |
| `robot_status` / `vision_status` | 机械臂在线状态、视觉检测状态 |
| `live_vote` | 直播投票结果与人格切换 |
| `debug_controls` | 开发期手动触发递水、摆动等动作 |

**本地运行**

```bash
cd frontend
npm install
npm run dev       # http://localhost:4173
npm run build     # 构建到 dist/（three.js 整个 build 目录拷贝至 dist/vendor/）
npm run smoke     # 冒烟测试
```

**部署**：Vercel（根目录 `vercel.json`：`cd frontend && npm install && npm run build`，输出 `frontend/dist`）。
线上地址：https://armingsoul.xyz

## deck — 路演幻灯片

`deck/index.html` 单文件幻灯片（配合 `assets/motion.min.js` 与 `images/`），
浏览器直接打开，方向键翻页。AdventureX 2026 Expo 演示用。

---

Made with 🦾 at **AdventureX 2026** · Hangzhou

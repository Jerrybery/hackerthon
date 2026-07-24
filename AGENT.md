# 开发指南

本仓库是一个 superproject，通过 git submodule 组装各个独立模块。各模块是自己的 git repo（fork 在 `Jerrybery` 名下），开发、提交、推送都在模块内部独立完成，互不干扰；父 repo 只负责记录各模块的指针（pin）和存放不属于任何模块的散文件。

## 仓库结构

```
hackerthon/                     父 repo: github.com/Jerrybery/hackerthon
├── nanobot/                    submodule → github.com/Jerrybery/nanobot       (branch: feat/soul-switching)
├── dimos/                      submodule → github.com/Jerrybery/dimos         (branch: main)
├── a1z/
│   ├── GALAXEA-A1Z/            submodule → github.com/Jerrybery/GALAXEA-A1Z   (branch: main)
│   ├── a1z_mac.py              父 repo 直接跟踪（macOS USB-CANFD 助手）
│   ├── a1z_mcp_server.py       父 repo 直接跟踪（A1Z 机械臂 MCP server）
│   └── hold_neutral.py         父 repo 直接跟踪
├── ring_sound_SDK/             父 repo 直接跟踪（戒指 SDK + demo.apk）
└── .claude/skills/             父 repo 直接跟踪（Claude Code skills）
```

## Remote 约定

每个 submodule 内部统一：

- `origin` = 自己的 fork（`Jerrybery/*`），可读写，日常推送走这里
- `upstream` = 原上游（`HKUDS/nanobot`、`dimensionalOS/dimos`、`userguide-galaxea/GALAXEA-A1Z`），只读，用于同步官方更新

## 常用工作流

### 克隆整个项目

```bash
git clone --recurse-submodules https://github.com/Jerrybery/hackerthon.git
# 已 clone 但没加 --recurse-submodules 时：
git submodule update --init --recursive
```

注意：submodule 拉下来后处于 detached HEAD（指向父 repo pin 的提交）。要在某个模块里开发，先切到对应分支：

```bash
cd nanobot && git checkout feat/soul-switching   # dimos / GALAXEA-A1Z 用 main
```

### 在模块里开发（以 nanobot 为例）

```bash
cd nanobot
git checkout feat/soul-switching
# ... 写代码 ...
git commit -am "feat: ..."
git push                      # 推到自己的 fork，不需要碰其他模块
```

### 让父项目指向模块的新提交

模块推完后，父 repo 的 pin 还停在旧提交。需要更新时：

```bash
cd <父 repo 根目录>
git add nanobot               # 记录新的 pin
git commit -m "chore: bump nanobot to <描述>"
git push
```

### 同步上游官方更新（以 nanobot 为例）

```bash
cd nanobot
git fetch upstream
git merge upstream/main       # 或: git rebase upstream/main
git push origin feat/soul-switching   # 有冲突解决后再推
```

### 批量更新所有 submodule 到远端最新

```bash
git submodule update --remote   # 按 .gitmodules 里记录的 branch 拉最新
```

## 不入库的内容

`.gitignore` 已排除：`key_router.py`（已废弃）、`.venv/`、`__pycache__/`、`*.pyc`、`.DS_Store`、`.kimi-code/`、`.claude/skills/dimos-dev`（指向本机 home 目录的绝对路径软链）。

## 新增一个模块时

1. 确认模块自己的 repo 已推送到 `Jerrybery` 名下（上游项目先 `gh repo fork`）
2. 在父 repo 根目录：
   ```bash
   git submodule add https://github.com/Jerrybery/<repo>.git <path>
   git commit -m "chore: add <repo> submodule"
   git push
   ```

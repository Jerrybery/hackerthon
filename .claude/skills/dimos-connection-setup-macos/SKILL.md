---
name: dimos-connection-setup-macos
description: "macOS 上连接星海图 Galaxea A1Z 机械臂（HHS USB-CANFD, gs_usb 用户态, EchoFilterBus）。当用户在 macOS 上接入/调试 A1Z、CAN 总线、gs_usb，或准备 DimOS A1Z adapter 时使用。"
---

# macOS 连接 Galaxea A1Z 机械臂

## 硬件拓扑

- A1Z 经 **HHS USB-CANFD 适配器**接 Mac：VID:PID `a8fa:8598`，设备名 "CANFD Analyser"，vendor "Com Equipment"
- 6 电机共用**一条经典 CAN 总线 @ 1Mbps**（不是 CANFD 帧）
- CAN ID：关节 1-3 = MotorA (`0x01`-`0x03`)，关节 4-6 = MotorB (`0x04`-`0x06`)
- 验证设备插入：`ioreg -p IOUSB -l -w 0 | grep -i canfd`
- **弯路警告**：macOS 上的 `en5` (`ac:de:48:00:11:22`) 是 Apple T2 iBridge 内部接口，与机械臂无关；Thunderbolt `bridge0` 同样无关

## Setup

工作目录任意（下称 `$A1Z_WS`）：

```bash
brew install libusb
cd $A1Z_WS
git clone https://github.com/userguide-galaxea/GALAXEA-A1Z.git
uv venv --python 3.10 .venv
uv pip install --python .venv/bin/python -e ./GALAXEA-A1Z pyusb gs-usb
```

SDK 依赖：python-can>=4.0, numpy, pin (pinocchio)。官方文档假设 Linux SocketCAN（`modprobe gs_usb` + `ip link set can0`）；**macOS 没有 SocketCAN，必须走 python-can 的 gs_usb 用户态后端 + `scripts/a1z_mac.py` 的 patch**。

把 `scripts/a1z_mac.py` 复制到 `$A1Z_WS/`（或加到 `PYTHONPATH`）。

### `a1z_mac.py` 做了什么（改之前先读）

1. **`GsUsb.is_gs_usb_device` 白名单 `a8fa:8598`**：gs_usb 库只认 `0x1d50:0x606f` 等已知 VID/PID，不加找不到设备
2. **Darwin 上 `is_kernel_driver_active` 恒 False**：macOS 无 kernel driver 可 detach，原逻辑 Access denied
3. **`GsUsb.send` 改写 endpoint `0x01`**：HHS 适配器 OUT EP 是 `0x01`，gs_usb 默认 `0x02`，不改报 `ValueError: Invalid endpoint address 0x2`
4. **`EchoFilterBus`**：gs_usb 用户态后端回显发送帧（`is_rx=False`）；SocketCAN 默认抑制 echo，用户态不抑制。SDK 控制环会把回显的 MIT 指令帧当电机反馈解析 → 饱和假位置 (12.5 rad)、假 fault `0x1F` → 急停。**控制环必须走 EchoFilterBus**。SDK 的 `tools/motor_diag.py` 有同问题注释（IFF_ECHO），但它只在扫描时过滤，控制环没过滤

## Test

### 1. 电机扫描（安全，不动臂）

```bash
cd $A1Z_WS
.venv/bin/python <skill>/scripts/scan_motors.py --workspace $A1Z_WS
# 或 A1Z_WS=$A1Z_WS .venv/bin/python <skill>/scripts/scan_motors.py
```

逐关节 enable → 读一帧反馈 → 失能，打印 pos/vel/temp/rtt。全部 ONLINE 即通讯正常。

### 2. 位置保持（⚠️ 臂会锁死并移动）

```bash
.venv/bin/python <skill>/scripts/hold_neutral.py --workspace $A1Z_WS
```

PD + 重力补偿 250Hz，先锁当前位，再慢速 (0.3 rad/s) 移到中性位姿并保持。Ctrl+C 退出 → **电机失能，臂立刻变软**。

## 安全须知

- **电机失能 = 臂立刻变软**：断电/停止前托住臂
- 关节限位（`get_robot.py`）：j1 ±120°，j2 [0°, 180°]，j3 [-180°, 0°]，j4/j5 ±85°，j6 ±115°
- SDK 检测到低频（<80Hz）或 motor fault 会自动急停
- 已知风险：`error_code 0x4` 出现过一次（保持 ~1 分钟后 joint1 fault，原因未查明——可能 USB 延迟抖动或电机保护）

## 迁移 OrangePi / Linux

Linux 上**不需要任何 patch**，SDK 原生 socketcan 直接用：

```bash
sudo modprobe gs_usb
sudo sh -c 'echo "a8fa 8598" > /sys/bus/usb/drivers/gs_usb/new_id'
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
```

## DimOS 本体在 macOS 上运行（Intel 已验证）

在 dimos 仓库跑 blueprint / MCP 时的坑（Intel Mac, x86_64 实测）：

### 环境安装

新版 `rerun-sdk`(>=0.27) 和 `dimos-viewer` **没有 x86_64 macOS wheel**，正常 `uv pip install -e .` 不可解。绕过：

```bash
cd <dimos 仓库>
uv venv --python 3.12
uv pip install -e . --no-deps
# 手动补依赖（PyPI 慢/会挂死时用 aliyun 镜像；--no-config 绕过 workspace exclude-newer）
uv pip install eclipse-zenoh numpy pydantic pydantic-settings python-dotenv structlog typer \
  fastapi uvicorn reactivex sortedcontainers plum-dispatch==2.5.7 lazy_loader toolz psutil \
  lz4 protobuf typing_extensions annotation-protocol packaging requests open3d langchain-core \
  --no-config --index-url https://mirrors.aliyun.com/pypi/simple/
uv pip install rerun-sdk==0.26.0 --no-config --index-url https://mirrors.aliyun.com/pypi/simple/
uv pip install dimos-lcm   # lcm-dimos-fork 无 wheel,cmake 源码编译 ~5 分钟,属正常
```

- `rerun-sdk==0.26.0` 是最后一个有 x86_64 wheel 的版本；CLI (`dimos/robot/cli/dimos.py` → `mapping/utils/cli/map.py`) import 时就要 `rerun`，绕不开
- PyPI CDN (Fastly) 可能限速 ~15KB/s 甚至连接挂死（进程 0 CPU、TCP ESTABLISHED 但 0 流量）—— 卡 >5 分钟就杀掉换 aliyun 镜像重跑
- uv 被杀后残留进程会持有 `.venv/.lock`，后续 install 全部等锁：`pgrep -fl "uv pip"` 检查并清理

### Transport：必须用 LCM，Zenoh 不通

- **Zenoh 在这台机器上不通**：它绑到 VPN 网卡地址（非 127.0.0.1），coordinator→worker RPC 发出后收不到回应，`build_all_modules` 永久卡住（模块显示已部署但之后日志静止、CPU 空闲）
- 用 LCM：`DIMOS_TRANSPORT=lcm dimos run <blueprint>`（CLI 子命令如 `dimos mcp list-tools` 也要带同样的 env）
- **LCM 需要组播路由指向 lo0**（重启后失效，需重加）：

```bash
sudo route delete -net 224.0.0.0/4 2>/dev/null; sudo route add -net 224.0.0.0/4 -interface lo0
```

不加的话 dimos 启动时自动修复逻辑会因 sudo 密码报 `CalledProcessError`。

### 诊断卡住的 run

```bash
ls -t logs/ | head -3                        # 每次 run 一个目录,main.jsonl 是 coordinator 日志
sudo uv tool run py-spy dump --pid <PID>     # py-spy 在 macOS 需要 root
```

### MCP

- **McpServer 只在 blueprint 运行时存在**，监听 `127.0.0.1:9990/mcp`（Streamable HTTP）；没有 blueprint 在跑时 `claude mcp list` 显示 Failed 是正常的
- **A1Z 的三个 blueprint（coordinator-a1z / a1z-planner-coordinator / keyboard-teleop-a1z）都没接 McpServer**；要在 MCP 里控制 A1Z 需自己给 blueprint 加 `McpServer.blueprint()`
- 验证链路用 `demo-mcp-stress-test`（轻量无硬件，官方 MCP e2e 用）：

```bash
DIMOS_TRANSPORT=lcm dimos run demo-mcp-stress-test   # 前台或 nohup
DIMOS_TRANSPORT=lcm dimos mcp list-tools
DIMOS_TRANSPORT=lcm dimos mcp call echo --arg message=test
```

- Claude Code 注册（user scope `~/.claude.json`）：`{"dimos": {"type": "http", "url": "http://localhost:9990/mcp"}}`

## 后续：DimOS A1Z adapter（未做）

- 目标位置 `dimos/hardware/manipulators/a1z/`，实现 ManipulatorAdapter Protocol，注册进 `dimos/hardware/adapter_registry.py`
- 通讯底座直接复用 `scripts/a1z_mac.py` 的 `open_bus`/`EchoFilterBus`（macOS）；Linux/OrangePi 走原生 socketcan 不需要 patch
- DimOS 侧已有规划层：`dimos/robot/manipulators/a1z/config.py`（URDF、joint 配置、mock adapter）、`blueprints/basic.py` + `blueprints/teleop.py`

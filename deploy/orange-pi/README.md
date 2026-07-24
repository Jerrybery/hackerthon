# Orange Pi 精简部署：A1Z DimOS MCP server

在工作站上执行（仓库根目录）：

```bash
deploy/orange-pi/deploy.sh orangepi@10.80.11.57 [更多主机...]
```

目标机布局 `~/dimos-mcp/`：`dimos/`（源码子集，editable 安装）、`a1z/`（机械臂
server + GALAXEA-A1Z SDK + 标定 yaml）、`setup.sh`、`run.sh`、
`requirements-pi.txt`。

## 精简策略

`pip install --no-deps -e dimos`，只装 `requirements-pi.txt` 里的最小闭包
（MCP server 路径实测不 import 重包）。**刻意不装**：rerun-sdk、dimos-viewer、
numba/llvmlite、open3d、torch、textual、scipy、opencv-contrib（用 headless）、
完整 langchain（只需 langchain-core 生成 skill schema）。
venv 约 460M（pinocchio + opencv-headless + numpy 为主），完整安装需数 GB。
安装后已额外清理：cmeel.prefix 的 C++ 头文件（~200M）、Boost 静态库、
pip 缓存（~175M）、__pycache__。

dimos core 有两处补丁（`dimos/dimos/core/coordination/module_coordinator.py`）：
- `start()` 对 open3d 缺失容错（跳过 PointCloud pickler 注册，仅警告）
- `_log_blueprint_graph()` 对 rerun 缺失容错（无 RerunBridgeModule 时本就直接返回）

## 运行

```bash
ssh orangepi@<ip>
cd ~/dimos-mcp && ./run.sh        # http://127.0.0.1:9990/mcp
```

`run.sh` 支持环境变量：`LISTEN_HOST`（默认 127.0.0.1；设 0.0.0.0 暴露到局域网）、
`MCP_PORT`（默认 9990）。`PYTEST_VERSION=1` 用来跳过 LCM system configurator
（它需要 sudo 加组播路由）。单进程 ModuleCoordinator 不需要该路由；跨进程
LCM 时手动加：`sudo ip route add 224.0.0.0/4 dev lo`。

## 开机自启（systemd user）

`a1z-mcp.service` 已安装到 `~/.config/systemd/user/` 并 enable（ linger 已开，
开机自启，绑 0.0.0.0:9990，失败 30s 退避重启——未插 CAN 适配器时的失败
重试属预期）。常用命令：

```bash
systemctl --user start|stop|status a1z-mcp
journalctl --user -u a1z-mcp -f
```

## 远程接入（nanobot / 其他 MCP 客户端）

板子 MCP 绑 0.0.0.0 后，远程 nanobot 配置：

```json
"tools": {
  "mcpServers": {
    "a1z-arm-pi": {"type": "streamableHttp", "url": "http://10.80.11.57:9990/mcp", "toolTimeout": 120}
  },
  "ssrfWhitelist": ["10.80.11.0/24"]
}
```

nanobot 的 SSRF 防护默认拦私网/回环 MCP URL，必须加白名单（本机回环则需
`127.0.0.0/8` + `::1/128`）。


## 硬件：HHS USB-CANFD 适配器

未插适配器时 server 会在 `A1ZArmModule/start` 报 `Cannot find device 0`——
插上即可。Linux 下 pyusb 访问 USB 需要权限，首次请配置 udev 规则
（需要 sudo）：

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="a8fa", ATTR{idProduct}=="8598", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/99-hhs-can.rules
sudo udevadm control --reload && 重新插拔适配器
```

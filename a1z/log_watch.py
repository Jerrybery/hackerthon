#!/usr/bin/env python3
"""A1Z 日志监测器。

两种用法：

1. 包裹你的运行命令（推荐，无需改动任何代码）：

       python log_watch.py -- python a1z_mcp_server.py
       python log_watch.py -- python examples/gravity_comp.py --mode hold

   子进程的全部输出照常显示，监测器实时高亮告警。

2. 跟踪一个已有日志文件（如果你的程序自己重定向了输出）：

       python log_watch.py -f run.log

命中 A1Z SDK 的急停/故障关键词时：终端响铃 + 红色横幅提醒，
并把带时间戳的告警追加写入 a1z_alerts.log，方便事后定位
机械臂"突然失能"的原因。
"""

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ALERT_LOG = Path(__file__).resolve().parent / "a1z_alerts.log"

# A1Z SDK (arm_robot.py / can_interface.py) 在急停前后会打出的关键日志
ALERT_PATTERNS = [
    r"Motor fault",                      # 电机错误码（过流/过温/过载/通信丢失...）
    r"error_code",
    r"over-?temperature",                # MOS / 线圈过温急停
    r"temperature warning",              # 过温预警（急停前的信号）
    r"Control loop too slow",            # 控制回路掉频
    r"Emergency stop",
    r"CAN feedback stale",               # 总线反馈超时
    r"CAN Error",
    r"Inverse dynamics torques too large",
    r"receive timeout",
    r"Traceback",
]
ALERT_RE = re.compile("|".join(ALERT_PATTERNS), re.IGNORECASE)
WARN_RE = re.compile(r"\bWARNING\b")
ERR_RE = re.compile(r"\b(ERROR|CRITICAL)\b")

RED = "\033[1;31m"
YELLOW = "\033[1;33m"
RESET = "\033[0m"


def record_alert(line: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with ALERT_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {line.rstrip()}\n")


def process_line(line: str) -> None:
    out = sys.stdout
    if ALERT_RE.search(line) or ERR_RE.search(line):
        out.write(f"{RED}{line}{RESET}")
        out.flush()
        if ALERT_RE.search(line):
            out.write(f"{RED}{'=' * 60}\n>>> A1Z 告警：{line.rstrip()}\n{'=' * 60}{RESET}\n")
            out.write("\a")  # 终端响铃
            out.flush()
            record_alert(line)
    elif WARN_RE.search(line):
        out.write(f"{YELLOW}{line}{RESET}")
        out.flush()
    else:
        out.write(line)
        out.flush()


def watch_command(cmd: list[str]) -> int:
    print(f"[log_watch] 启动: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # SDK 日志走 stderr，合并一起监测
        text=True,
        bufsize=1,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            process_line(line)
    except KeyboardInterrupt:
        print("\n[log_watch] 收到 Ctrl-C，正在停止子进程...")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    return proc.wait()


def watch_file(path: Path) -> None:
    print(f"[log_watch] 跟踪日志文件: {path} (Ctrl-C 退出)")
    # 从文件末尾开始，只监测新内容
    pos = path.stat().st_size if path.exists() else 0
    try:
        while True:
            if not path.exists():
                time.sleep(0.5)
                continue
            with path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
            for line in chunk.splitlines(keepends=True):
                process_line(line if line.endswith("\n") else line + "\n")
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n[log_watch] 退出")


def main() -> None:
    ap = argparse.ArgumentParser(description="A1Z 日志监测器")
    ap.add_argument("-f", "--file", type=Path, help="跟踪已有日志文件")
    ap.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="-- 之后的命令会被启动并监测其输出")
    args = ap.parse_args()

    if args.file:
        watch_file(args.file)
        return

    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        ap.error("请用 -- 指定要运行的命令，或用 -f 指定日志文件")
    sys.exit(watch_command(cmd))


if __name__ == "__main__":
    main()

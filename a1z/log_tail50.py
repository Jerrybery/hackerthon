#!/usr/bin/env python3
"""Rolling tail: keep only the last N seconds of a growing log file.

Independent of the MCP server process: a1z_mcp_server.py tees its own
stdout/stderr into logs/mcp_server.log at startup (whoever launches it),
and this watcher only reads that file.

Continuously rewrites logs/last50s.log with the lines received within the
trailing WINDOW seconds, and appends lines matching A1Z alert patterns
(estop / motor fault / CAN stale / ...) to a1z_alerts.log with timestamps.
When something breaks, last50s.log is the fresh error context.
"""

import re
import sys
import time
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "logs" / "mcp_server.log"
DST = HERE / "logs" / "last50s.log"
ALERT_LOG = HERE / "a1z_alerts.log"
WINDOW = 50.0  # seconds

# Same patterns as log_watch.py
ALERT_RE = re.compile(
    "|".join(
        [
            r"Motor fault",
            r"error_code",
            r"over-?temperature",
            r"temperature warning",
            r"Control loop too slow",
            r"Emergency stop",
            r"CAN feedback stale",
            r"CAN Error",
            r"Inverse dynamics torques too large",
            r"receive timeout",
            r"Traceback",
        ]
    ),
    re.IGNORECASE,
)


def main() -> None:
    buf: deque[tuple[float, str]] = deque()
    pos = 0
    print(f"[tail50] watching {SRC}, writing {DST} (window={WINDOW:.0f}s)", flush=True)
    while True:
        if SRC.exists():
            size = SRC.stat().st_size
            if size < pos:  # file was truncated/recreated
                pos = 0
            with SRC.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
            now = time.time()
            for line in chunk.splitlines():
                buf.append((now, line))
                if ALERT_RE.search(line):
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    with ALERT_LOG.open("a", encoding="utf-8") as af:
                        af.write(f"[{ts}] {line}\n")

        cutoff = time.time() - WINDOW
        while buf and buf[0][0] < cutoff:
            buf.popleft()

        with DST.open("w", encoding="utf-8") as f:
            for _, line in buf:
                f.write(line + "\n")

        time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

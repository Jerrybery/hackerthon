#!/usr/bin/env python3
"""DualSense gyro teleop bridge for the A1Z MCP server.

Reads the PS5 DualSense controller from hidraw on this host (Orange Pi),
converts gyro angular rates / dpad / LB-RB buttons into small TCP increments,
and sends them to the arm via the `gamepad_teleop` MCP tool at SEND_HZ.

The mutual-exclusion gate lives on the server (a1z_mcp_server.py): this
bridge just sends; `gamepad_teleop` is rejected unless control mode is
"gamepad". Flip the mode via:
  - the controller PS button (edge-triggered), or
  - HTTP:  curl -XPOST http://<host>:9991/mode           (toggle)
           curl -XPOST http://<host>:9991/mode -d '{"mode":"ai"}'

Requires no third-party packages (stdlib only).

Report layout (USB, hidraw buffer; verified empirically on this controller):
  buf[0]      report ID 0x01
  buf[1..4]   sticks LX, LY, RX, RY (0..255, center ~128)
  buf[5],[6]  L2, R2 analog (0..255)
  buf[8]      buttons0: dpad lo nibble (0x08=neutral)|square 0x10|cross 0x20|circle 0x40|triangle 0x80
  buf[9]      buttons1: L1 0x01|R1 0x02|L2 0x04|R2 0x08|create 0x10|options 0x20|L3 0x40|R3 0x80
  buf[10]     buttons2: PS 0x01|touchpad 0x02|mute 0x04
  buf[16..21] gyro Pitch/Yaw/Roll  int16 LE
  buf[22..27] accel X/Y/Z          int16 LE
  buf[28..31] motion timestamp     uint32

Usage:
  python3 gamepad_bridge.py            # calibrate (hold still) then teleop
  python3 gamepad_bridge.py --dump     # print parsed report, no MCP calls
  python3 gamepad_bridge.py --no-calib # skip startup calibration
"""

import argparse
import json
import math
import os
import re
import select
import struct
import sys
import time
import urllib.request

HIDRAW = os.environ.get("A1Z_HIDRAW", "/dev/hidraw0")
MCP_URL = os.environ.get("A1Z_MCP_URL", "http://127.0.0.1:9990/mcp")
MODE_URL = os.environ.get("A1Z_MODE_URL", "http://127.0.0.1:9991/mode")

# --- tuning constants -------------------------------------------------------
# DualSense gyro full scale is ±2000 dps over int16 (per public teardowns).
# NOTE: the FeelSpace web demo used raw/10 instead — if teleop feels ~1.6x
# too fast/slow, re-check this with the 90-degree turn test.
GYRO_DPS_PER_LSB = 2000.0 / 32768.0
ACCEL_G_PER_LSB = 1.0 / 8192.0
GYRO_DEADBAND_DPS = 3.0
STICK_DEADBAND = 14          # of 255 around center 128
TRIG_DEADBAND = 10           # of 255
SEND_HZ = 12.0
GYRO_GAIN = 2.5              # TCP angular speed = gyro rate x gain (rate control)
MAX_TCP_ROT_DPS = 75.0       # TCP angular speed cap (server clamp: 3 deg/call)
MAX_TCP_TRANS_MPS = 0.10     # TCP translation speed cap
CALIB_SECONDS = 1.0
# Axis sign conventions between controller and arm base frame.
# VERIFY LIVE with tiny movements before raising the caps above.
SIGN_ROLL = 1.0
SIGN_PITCH = 1.0
SIGN_YAW = 1.0
SIGN_DX = 1.0                # stick forward  -> +x (base forward)
SIGN_DY = 1.0                # stick left     -> +y (base left)
SIGN_DZ = 1.0                # R2 -> +z up, L2 -> -z down
GRIPPER_CLOSED = 0.0
GRIPPER_OPEN = 1.0

# --- button bits ------------------------------------------------------------
BTN0_CROSS = 0x20
BTN0_CIRCLE = 0x40
BTN1_L3 = 0x40
BTN2_PS = 0x01
BTN2_TOUCHPAD = 0x02

# --- absolute attitude mode -------------------------------------------------
# Controller attitude RELATIVE TO ANCHOR (complementary filter: gyro integral
# + accel tilt correction) maps 1:1 onto TCP orientation relative to the
# arm-side anchor — no delta accumulation, so dropped packets cannot ratchet
# the reference away from the reachable pose. Touchpad button = teleop_level
# (TCP to horizontal) + re-anchor both sides.
ATT_ALPHA = 0.98
ABS_GAIN = 1.0
ATT_SEND_THRESH_DEG = 0.3   # min attitude change before sending a packet


def _tilt(accel_g) -> tuple[float, float]:
    """Accel tilt (roll, pitch) in degrees of the controller frame."""
    ax, ay, az = accel_g
    return (math.degrees(math.atan2(ay, az)),
            math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az))))


def _parse_rpy(text: str):
    m = re.search(r"rpy\(deg\)=\(([^)]+)\)", text)
    if not m:
        return None
    try:
        return [float(v) for v in m.group(1).split(",")]
    except ValueError:
        return None


def parse_report(buf: bytes) -> dict | None:
    """Parse one 64-byte USB input report. Returns None if not the main report."""
    if len(buf) < 32 or buf[0] != 0x01:
        return None
    gp, gy, gr = struct.unpack_from("<hhh", buf, 16)
    ax, ay, az = struct.unpack_from("<hhh", buf, 22)
    ts, = struct.unpack_from("<I", buf, 28)
    return {
        "lx": buf[1], "ly": buf[2], "rx": buf[3], "ry": buf[4],
        "l2": buf[5], "r2": buf[6],
        "b0": buf[8], "b1": buf[9], "b2": buf[10],
        "gyro_dps": (gp * GYRO_DPS_PER_LSB, gy * GYRO_DPS_PER_LSB,
                     gr * GYRO_DPS_PER_LSB),
        "accel_g": (ax * ACCEL_G_PER_LSB, ay * ACCEL_G_PER_LSB,
                    az * ACCEL_G_PER_LSB),
        "ts": ts,
    }


class McpClient:
    """Minimal streamable-HTTP MCP client (stdlib), mirrors a1z/mcp_call.py."""

    def __init__(self, url: str):
        self.url = url
        self.session_id = None
        self._id = 0

    def _post(self, payload: dict) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            sid = resp.headers.get("mcp-session-id")
            if sid:
                self.session_id = sid
            body = resp.read().decode()
            ctype = resp.headers.get("content-type", "")
            code = resp.status
        if code == 202 or not body:
            return {}
        if "text/event-stream" in ctype:
            data = None
            for line in body.splitlines():
                if line.startswith("data:"):
                    data = line[5:].strip()
            return json.loads(data) if data else {}
        return json.loads(body)

    def call(self, method: str, params: dict | None = None,
             notif: bool = False) -> dict:
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notif:
            self._id += 1
            payload["id"] = self._id
        return self._post(payload)

    def initialize(self) -> None:
        self.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "gamepad-bridge", "version": "0.1"},
        })
        self.call("notifications/initialized", notif=True)

    def tool(self, name: str, args: dict) -> str:
        resp = self.call("tools/call", {"name": name, "arguments": args})
        if "error" in resp:
            return f"MCP-ERROR: {resp['error']}"
        content = resp.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in content
                         if c.get("type") == "text")


def toggle_mode() -> str:
    """POST an empty body to the mode switch -> toggles ai/gamepad."""
    req = urllib.request.Request(MODE_URL, data=b"")
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return json.loads(resp.read().decode()).get("mode", "?")


def open_hidraw(path: str):
    try:
        return os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as e:
        sys.exit(f"ERROR: cannot open {path}: {e} "
                 "(is the controller plugged in? hidraw permissions?)")


def open_hidraw_retry(path: str):
    """Like open_hidraw but waits for the controller to (re)appear."""
    while True:
        try:
            return os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            time.sleep(1.0)


def read_latest(fd) -> bytes | None:
    """Drain the hidraw queue, return the freshest full report (or None)."""
    latest = None
    while True:
        r, _, _ = select.select([fd], [], [], 0)
        if not r:
            return latest
        try:
            buf = os.read(fd, 64)
        except BlockingIOError:
            return latest
        if buf:
            latest = buf


def calibrate(fd) -> tuple[float, float, float]:
    """Average gyro while the controller lies still -> zero bias (dps)."""
    print(f"[bridge] calibrating gyro bias for {CALIB_SECONDS:.1f}s — "
          "keep the controller STILL", flush=True)
    t0 = time.time()
    n = 0
    acc = [0.0, 0.0, 0.0]
    while time.time() - t0 < CALIB_SECONDS:
        buf = read_latest(fd)
        if buf is None:
            time.sleep(0.002)
            continue
        rep = parse_report(buf)
        if rep is None:
            continue
        for i in range(3):
            acc[i] += rep["gyro_dps"][i]
        n += 1
    if n == 0:
        sys.exit("ERROR: no reports during calibration — controller asleep?")
    bias = tuple(v / n for v in acc)
    print(f"[bridge] gyro bias (dps): "
          f"pitch={bias[0]:.2f} yaw={bias[1]:.2f} roll={bias[2]:.2f} "
          f"({n} samples)", flush=True)
    return bias


def dump_mode(fd) -> None:
    """Print parsed reports; raw button bytes shown when they change."""
    print("[bridge] dump mode — move sticks / press buttons, Ctrl-C to quit")
    last_btns = None
    last_print = 0.0
    while True:
        buf = read_latest(fd)
        if buf is None:
            time.sleep(0.005)
            continue
        rep = parse_report(buf)
        if rep is None:
            continue
        btns = (rep["b0"], rep["b1"], rep["b2"])
        if btns != last_btns:
            print(f"buttons b0={btns[0]:#04x} b1={btns[1]:#04x} b2={btns[2]:#04x}")
            last_btns = btns
        now = time.time()
        if now - last_print > 0.2:
            g = rep["gyro_dps"]
            a = rep["accel_g"]
            print(f"gyro(dps) p={g[0]:7.1f} y={g[1]:7.1f} r={g[2]:7.1f} | "
                  f"accel(g) {a[0]:5.2f} {a[1]:5.2f} {a[2]:5.2f} | "
                  f"stick {rep['lx']:3d} {rep['ly']:3d} {rep['rx']:3d} "
                  f"{rep['ry']:3d} | L2={rep['l2']:3d} R2={rep['r2']:3d}")
            last_print = now


def _deadband(v: float, band: float) -> float:
    return 0.0 if abs(v) < band else v


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", action="store_true",
                    help="print parsed reports, no MCP calls")
    ap.add_argument("--no-calib", action="store_true",
                    help="skip startup gyro bias calibration")
    args = ap.parse_args()

    if args.dump:
        fd = open_hidraw(HIDRAW)  # strict: fail fast in dump mode
        dump_mode(fd)
        return

    fd = open_hidraw_retry(HIDRAW)

    bias = (0.0, 0.0, 0.0) if args.no_calib else calibrate(fd)

    mcp = McpClient(MCP_URL)
    while True:
        try:
            mcp.initialize()
            break
        except Exception as e:
            print(f"[bridge] MCP at {MCP_URL} unreachable ({e}), retrying...",
                  flush=True)
            time.sleep(1.0)
    print(f"[bridge] teleop active -> {MCP_URL} "
          f"(PS button toggles ai/gamepad mode via {MODE_URL})", flush=True)

    dt = 1.0 / SEND_HZ
    prev_b = (0, 0, 0)
    gripper_cmd = None
    last_reject_log = 0.0
    last_integ_t = time.time()

    # --- absolute attitude state ---
    att = [0.0, 0.0, 0.0]       # controller rpy relative to anchor (deg)
    tilt0 = [None]              # accel tilt at anchor (list for closure)
    arm_rpy0 = [None]           # arm TCP rpy at anchor (list for closure)
    last_sent_att = [0.0, 0.0, 0.0]
    was_rejected = [False]

    def anchor() -> None:
        """Re-zero both sides: controller attitude and arm TCP rpy."""
        att[0] = att[1] = att[2] = 0.0
        tilt0[0] = None  # captured from the next report's accel
        try:
            arm_rpy0[0] = _parse_rpy(mcp.tool("get_tcp_pose", {}))
        except Exception:
            arm_rpy0[0] = None
        last_sent_att[0] = last_sent_att[1] = last_sent_att[2] = 0.0
        print(f"[bridge] anchored (arm rpy0={arm_rpy0[0]})", flush=True)

    anchor()

    while True:
        t_send = time.time()
        # measured integration step: the MCP call below can make the actual
        # tick longer than 1/SEND_HZ, and integrating with a fixed dt would
        # under-rotate the arm by exactly that ratio
        dt_meas = min(max(t_send - last_integ_t, 0.01), 0.2)
        last_integ_t = t_send
        try:
            buf = read_latest(fd)
        except OSError:
            # controller unplugged / re-enumerated — wait and reconnect,
            # keeping the original gyro bias (recalibrating while the user
            # holds the controller would poison the zero point)
            print("[bridge] controller lost, waiting for reconnect...",
                  flush=True)
            os.close(fd)
            fd = open_hidraw_retry(HIDRAW)
            print("[bridge] controller back, resuming teleop", flush=True)
            continue
        if buf is not None:
            rep = parse_report(buf)
            if rep is not None:
                b = (rep["b0"], rep["b1"], rep["b2"])

                # --- mode toggle: PS button, edge-triggered ---
                if (b[2] & BTN2_PS) and not (prev_b[2] & BTN2_PS):
                    try:
                        mode = toggle_mode()
                        print(f"[bridge] mode toggled -> {mode}", flush=True)
                        if mode == "gamepad":
                            anchor()
                    except Exception as e:
                        print(f"[bridge] mode toggle failed: {e}", flush=True)

                # --- touchpad: level TCP + re-anchor (edge-triggered) ---
                if (b[2] & BTN2_TOUCHPAD) and not (prev_b[2] & BTN2_TOUCHPAD):
                    try:
                        res = mcp.tool("teleop_level", {})
                        print(f"[bridge] {res}", flush=True)
                        anchor()
                    except Exception as e:
                        print(f"[bridge] teleop_level failed: {e}", flush=True)

                # --- gripper: cross = close, circle = open (edge) ---
                if (b[0] & BTN0_CROSS) and not (prev_b[0] & BTN0_CROSS):
                    gripper_cmd = GRIPPER_CLOSED
                if (b[0] & BTN0_CIRCLE) and not (prev_b[0] & BTN0_CIRCLE):
                    gripper_cmd = GRIPPER_OPEN
                prev_b = b

                # --- absolute attitude (complementary filter, rel. anchor) ---
                if tilt0[0] is None:
                    tilt0[0] = _tilt(rep["accel_g"])
                gp = _deadband(rep["gyro_dps"][0] - bias[0], GYRO_DEADBAND_DPS)
                gy = _deadband(rep["gyro_dps"][1] - bias[1], GYRO_DEADBAND_DPS)
                gr = _deadband(rep["gyro_dps"][2] - bias[2], GYRO_DEADBAND_DPS)
                att[0] += gr * dt_meas
                att[1] += gp * dt_meas
                att[2] += gy * dt_meas
                tr, tp = _tilt(rep["accel_g"])
                att[0] = ATT_ALPHA * att[0] + (1 - ATT_ALPHA) * (tr - tilt0[0][0])
                att[1] = ATT_ALPHA * att[1] + (1 - ATT_ALPHA) * (tp - tilt0[0][1])

                abs_rpy = None
                if arm_rpy0[0] is not None:
                    abs_rpy = (
                        arm_rpy0[0][0] + SIGN_ROLL * ABS_GAIN * att[0],
                        arm_rpy0[0][1] + SIGN_PITCH * ABS_GAIN * att[1],
                        arm_rpy0[0][2] + SIGN_YAW * ABS_GAIN * att[2])
                att_moved = abs_rpy is not None and any(
                    abs(abs_rpy[i] - last_sent_att[i]) > ATT_SEND_THRESH_DEG
                    for i in range(3))

                # --- dpad -> xy, □ square -> z down, △ triangle -> z up ---
                dpad = b[0] & 0x0F
                fwd = 1.0 if dpad in (0, 1, 7) else -1.0 if dpad in (3, 4, 5) else 0.0
                left = 1.0 if dpad in (5, 6, 7) else -1.0 if dpad in (1, 2, 3) else 0.0
                zdown = 1.0 if (b[0] & 0x10) else 0.0
                zup = 1.0 if (b[0] & 0x80) else 0.0
                step = MAX_TCP_TRANS_MPS * dt_meas
                dx = SIGN_DX * fwd * step
                dy = SIGN_DY * left * step
                dz = SIGN_DZ * (zup - zdown) * step

                if att_moved or any((dx, dy, dz)) or gripper_cmd is not None:
                    payload = {
                        "dx": round(dx, 4), "dy": round(dy, 4),
                        "dz": round(dz, 4),
                    }
                    if abs_rpy is not None:
                        payload["abs_roll_deg"] = round(abs_rpy[0], 2)
                        payload["abs_pitch_deg"] = round(abs_rpy[1], 2)
                        payload["abs_yaw_deg"] = round(abs_rpy[2], 2)
                    if gripper_cmd is not None:
                        payload["gripper"] = gripper_cmd
                        gripper_cmd = None
                    try:
                        res = mcp.tool("gamepad_teleop", payload)
                        if res.startswith("REJECTED"):
                            was_rejected[0] = True
                            if time.time() - last_reject_log > 5.0:
                                print(f"[bridge] {res}", flush=True)
                                last_reject_log = time.time()
                        else:
                            if was_rejected[0]:
                                # back in gamepad mode — anchors are stale
                                was_rejected[0] = False
                                anchor()
                            if abs_rpy is not None:
                                last_sent_att[0], last_sent_att[1], \
                                    last_sent_att[2] = abs_rpy
                            if res.startswith(("ERROR", "MCP-ERROR")):
                                print(f"[bridge] {res}", flush=True)
                    except Exception as e:
                        print(f"[bridge] MCP call failed: {e}", flush=True)
                        try:
                            mcp.initialize()
                        except Exception:
                            time.sleep(1.0)

        elapsed = time.time() - t_send
        if elapsed < dt:
            time.sleep(dt - elapsed)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[bridge] bye")
    except OSError as e:
        sys.exit(f"[bridge] controller disconnected or hidraw error: {e}")

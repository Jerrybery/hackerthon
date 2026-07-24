"""A1Z position hold on macOS via gs_usb.

Starts in position-hold (PD + gravity comp) at current pose, moves slowly to a
neutral pose, then holds. Ctrl+C / SIGTERM stops the loop and DISABLES motors
(arm goes limp) — support the arm or cut power first.

Usage:
    A1Z_WS=/path/to/workspace python hold_neutral.py
    python hold_neutral.py --workspace /path/to/workspace
"""

import argparse
import os
import signal
import sys
import time
from pathlib import Path

import numpy as np

SKILL_SCRIPTS = Path(__file__).resolve().parent

# Within joint limits: j3 range is [-180, 0] deg, so bend negative
NEUTRAL_DEG = [0.0, 34.0, -23.0, -29.0, 0.0, 0.0]
MOVE_SPEED = 0.3  # rad/s


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace",
        default=os.environ.get("A1Z_WS", ""),
        help="A1Z workspace dir (or set A1Z_WS)",
    )
    parser.add_argument(
        "--pose",
        default="",
        help="comma-separated target joint degrees, e.g. '25,55,-45,-20,0,0' "
        "(default: built-in neutral)",
    )
    args = parser.parse_args()
    if not args.workspace:
        parser.error("workspace required: --workspace DIR or A1Z_WS env")

    pose_deg = (
        [float(x) for x in args.pose.split(",")] if args.pose else NEUTRAL_DEG
    )
    if len(pose_deg) != 6:
        parser.error("--pose needs exactly 6 comma-separated degrees")

    ws = Path(args.workspace).expanduser().resolve()
    sdk = ws / "GALAXEA-A1Z"
    if not sdk.is_dir():
        parser.error(f"SDK repo not found at {sdk}")

    sys.path.insert(0, str(SKILL_SCRIPTS))
    sys.path.insert(0, str(sdk))

    from a1z_mac import EchoFilterBus, open_bus
    import a1z.robots.get_robot as gr

    bus = EchoFilterBus(open_bus())
    gr.can.interface.Bus = lambda **kw: bus  # get_a1z_robot hardcodes socketcan

    robot = gr.get_a1z_robot(
        gravity_comp_factor=1.0,
        zero_gravity_mode=False,
        control_freq_hz=250,
    )

    running = True

    def handle_sig(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    print("[hold] starting control loop (position hold at current pose)...", flush=True)
    robot.start()
    state = robot.get_joint_state()
    print("[hold] running. pos(deg):", np.round(np.degrees(state["pos"]), 2), flush=True)

    target = np.deg2rad(np.array(NEUTRAL_DEG))
    print(f"[hold] moving to neutral {NEUTRAL_DEG} deg at {MOVE_SPEED} rad/s...", flush=True)
    robot.move_joints(target, speed=MOVE_SPEED)
    print("[hold] target reached, holding. Ctrl+C to stop (motors go limp!).", flush=True)

    while running and robot.is_running:
        state = robot.get_joint_state()
        pos_deg = np.degrees(state["pos"])
        eff = state["eff"]
        print(
            f"  pos(deg): [{', '.join(f'{p:7.2f}' for p in pos_deg)}]  "
            f"eff(Nm): [{', '.join(f'{e:6.2f}' for e in eff)}]",
            flush=True,
        )
        time.sleep(1.0)

    print("[hold] stopping (motors disabling)...", flush=True)
    robot.stop()
    bus.shutdown()
    print("[hold] done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

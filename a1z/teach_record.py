"""A1Z zero-force drag teach & trajectory library, macOS edition.

Same workflow as GALAXEA-A1Z/examples/teach_and_play.py, but opens the HHS
USB-CANFD adapter through gs_usb userspace (a1z_mac.py) instead of SocketCAN,
and stores named trajectories under trajectories/ for preset-action collection.

Record (zero-gravity drag teaching):
    python teach_record.py record pick_and_place
    python teach_record.py record wave --sample-hz 100

    ENTER once to start recording, ENTER again to stop. The trajectory is
    saved under trajectories/ and the arm returns to the zero pose.

Play back (position-hold mode):
    python teach_record.py play pick_and_place --speed 0.5
    python teach_record.py play pick_and_place --loop

Inspect:
    python teach_record.py list
    python teach_record.py info pick_and_place

Safety: exiting a record/play session DISABLES the motors — the arm goes
limp. Support the arm (or cut motor power first) before quitting.
"""

import argparse
import json
import signal
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent / "GALAXEA-A1Z"))
sys.path.insert(0, str(Path(__file__).parent))

from a1z_mac import EchoFilterBus, open_bus  # noqa: E402

import a1z.robots.get_robot as gr  # noqa: E402
from a1z.robots.arm_robot import ArmRobot  # noqa: E402

TRAJ_DIR = Path(__file__).parent / "trajectories"

ZERO_POSE = np.zeros(6)  # all joints at 0 rad
RETURN_SPEED = 0.3       # rad/s, for the post-record return to zero


def traj_path(name: str) -> Path:
    name = Path(name).stem  # strip any directory / extension parts
    return TRAJ_DIR / f"{name}.json"


def _wait_enter(prompt: str) -> None:
    print(prompt, end="", flush=True)
    input()


def _make_robot(zero_gravity: bool):
    bus = EchoFilterBus(open_bus())
    gr.can.interface.Bus = lambda **kw: bus
    robot = gr.get_a1z_robot(
        gravity_comp_factor=1.0,
        zero_gravity_mode=zero_gravity,
        control_freq_hz=250,
    )
    return robot, bus


def _shutdown(robot, bus) -> None:
    if robot.is_running:
        print("[teach] stopping — motors DISABLE, arm goes limp. Support it!", flush=True)
    robot.stop()
    bus.shutdown()


def _display_pose(robot, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        state = robot.get_joint_state()
        pos_deg = np.degrees(state["pos"])
        print(f"  pos(deg): [{', '.join(f'{p:7.2f}' for p in pos_deg)}]", end="\r")
        time.sleep(0.1)


def cmd_record(args: argparse.Namespace) -> None:
    out = traj_path(args.name)
    if out.exists() and not args.force:
        print(f"[record] {out} already exists. Use --force to overwrite.")
        sys.exit(1)

    robot, bus = _make_robot(zero_gravity=True)
    signal.signal(signal.SIGINT, signal.default_int_handler)

    print("=" * 60)
    print("  A1Z Teach — Record (zero-gravity drag teaching)")
    print(f"  Save to:    {out}")
    print(f"  Sample Hz:  {args.sample_hz}")
    print("=" * 60)

    robot.start()
    print("[record] Arm is in zero-gravity mode — it can be dragged freely.\n")

    try:
        _wait_enter("[record] Press ENTER to START recording...")
        robot.start_recording(sample_hz=args.sample_hz)
        print("[record] Recording — drag the arm now. Press ENTER to STOP.")

        stop_display = threading.Event()
        disp = threading.Thread(target=_display_pose, args=(robot, stop_display), daemon=True)
        disp.start()
        input()
        stop_display.set()
        disp.join(timeout=0.5)
        print()

        trajectory = robot.stop_recording()
        if not trajectory:
            print("[record] No frames recorded. Nothing saved.")
            return

        duration = trajectory[-1][0]
        TRAJ_DIR.mkdir(parents=True, exist_ok=True)
        ArmRobot.save_recording(trajectory, str(out))
        print(f"[record] Saved {len(trajectory)} frames ({duration:.2f}s) -> {out}")

        print("[record] Returning to zero pose...")
        robot.move_joints(ZERO_POSE, speed=RETURN_SPEED)
        time.sleep(0.3)
    finally:
        _shutdown(robot, bus)


def cmd_play(args: argparse.Namespace) -> None:
    path = traj_path(args.name)
    if not path.exists():
        print(f"[play] {path} not found. Record it first (or check `list`).")
        sys.exit(1)

    trajectory = ArmRobot.load_recording(str(path))
    duration = trajectory[-1][0] if trajectory else 0.0
    if not trajectory:
        print("[play] Empty trajectory file.")
        sys.exit(1)

    robot, bus = _make_robot(zero_gravity=False)
    signal.signal(signal.SIGINT, signal.default_int_handler)

    print("=" * 60)
    print("  A1Z Teach — Play")
    print(f"  File:   {path}")
    print(f"  Frames: {len(trajectory)} ({duration:.2f}s)")
    print(f"  Speed:  {args.speed}x   Loop: {'yes' if args.loop else 'no'}")
    print("=" * 60)

    robot.start()
    try:
        start_pos = trajectory[0][1]
        print("[play] Moving to trajectory start pose (speed 0.4 rad/s)...")
        robot.move_joints(start_pos, speed=0.4)
        print("[play] Ready.\n")

        while True:
            _wait_enter(f"[play] Press ENTER to PLAY ({duration / args.speed:.1f}s)...")
            robot.play_trajectory(trajectory, speed_factor=args.speed)
            print("[play] Playback complete.")
            if not args.loop:
                break
            robot.move_joints(start_pos, speed=0.6)
    finally:
        _shutdown(robot, bus)


def cmd_list(_args: argparse.Namespace) -> None:
    if not TRAJ_DIR.is_dir():
        print("(no trajectories yet)")
        return
    files = sorted(TRAJ_DIR.glob("*.json"))
    if not files:
        print("(no trajectories yet)")
        return
    for f in files:
        try:
            with open(f) as fh:
                data = json.load(fh)
            n = len(data["frames"])
            dur = data["frames"][-1][0] if n else 0.0
            print(f"  {f.stem:<24} {n:>5} frames  {dur:6.2f}s")
        except (json.JSONDecodeError, KeyError, IndexError):
            print(f"  {f.stem:<24} (unreadable)")


def cmd_info(args: argparse.Namespace) -> None:
    path = traj_path(args.name)
    if not path.exists():
        print(f"[info] {path} not found.")
        sys.exit(1)
    trajectory = ArmRobot.load_recording(str(path))
    pos = np.array([p for _, p in trajectory])
    print(f"{path.name}: {len(trajectory)} frames, {trajectory[-1][0]:.2f}s")
    print(f"  start (deg): {np.round(np.degrees(pos[0]), 2).tolist()}")
    print(f"  end   (deg): {np.round(np.degrees(pos[-1]), 2).tolist()}")
    print(f"  min   (deg): {np.round(np.degrees(pos.min(axis=0)), 2).tolist()}")
    print(f"  max   (deg): {np.round(np.degrees(pos.max(axis=0)), 2).tolist()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="A1Z teach & trajectory library (macOS)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_record = sub.add_parser("record", help="Zero-gravity drag teaching, save trajectory")
    p_record.add_argument("name", help=f"Trajectory name, saved as {TRAJ_DIR}/<name>.json")
    p_record.add_argument("--sample-hz", type=int, default=50, dest="sample_hz",
                          help="Recording sample rate in Hz (default: 50)")
    p_record.add_argument("--force", action="store_true", help="Overwrite existing file")

    p_play = sub.add_parser("play", help="Play back a saved trajectory")
    p_play.add_argument("name", help="Trajectory name")
    p_play.add_argument("--speed", type=float, default=1.0,
                        help="Playback speed factor (default: 1.0)")
    p_play.add_argument("--loop", action="store_true", help="Loop until Ctrl+C")

    sub.add_parser("list", help="List saved trajectories")

    p_info = sub.add_parser("info", help="Show trajectory details (no hardware needed)")
    p_info.add_argument("name", help="Trajectory name")

    args = parser.parse_args()
    {"record": cmd_record, "play": cmd_play, "list": cmd_list, "info": cmd_info}[args.cmd](args)


if __name__ == "__main__":
    main()

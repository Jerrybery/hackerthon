"""Hand-eye (eye-in-hand) data collection for the A1Z wrist camera.

Position-hold version: the arm locks its current pose on start, then
automatically sweeps through a set of relative joint offsets (large j1
sweeps + wrist rolls, required for a well-conditioned AX=XB), capturing
(image, joint state) at each stop where the checkerboard is visible.

Usage:
1. Power the arm, motors OFF. Hand-position the wrist so the camera
   sees the checkerboard (which must be RIGIDLY FIXED in the world).
2. From repo root:
       a1z/.venv/bin/python a1z/calibration/collect_handeye.py
3. Watch it sweep. On exit the arm goes limp: support it (gravity comp
   is ramped down first). Keys: q/ESC = abort and shut down.
"""

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

CAL_DIR = Path(__file__).parent
A1Z_DIR = CAL_DIR.parent                      # a1z/
sys.path.insert(0, str(CAL_DIR))              # capture_intrinsics
sys.path.insert(0, str(A1Z_DIR))              # a1z_mac

from capture_intrinsics import find_board, PATTERN_SIZE  # noqa: E402
from a1z_mac import EchoFilterBus, open_bus              # noqa: E402
import a1z.robots.get_robot as gr                        # noqa: E402

CAM_INDEX = 0
WIDTH, HEIGHT = 1920, 1080
SETTLE_S = 1.0
MOVE_SPEED = 0.25          # rad/s
DATA_DIR = CAL_DIR / "data" / "handeye"

# joint limits (deg), same as a1z_mcp_server.py
JOINT_LIMITS_DEG = [
    (-120.0, 120.0),
    (0.0, 180.0),
    (-180.0, 0.0),
    (-85.0, 85.0),
    (-85.0, 85.0),
    (-115.0, 115.0),
]

# relative offsets (deg) applied to the start pose: moderate j1 sweeps
# (big sweeps lose the board) + strong wrist rolls for rotation-axis diversity
OFFSETS_DEG = [
    (0, 0, 0, 0, 0, 0),
    (-12, 0, 0, 0, 0, 0),
    (12, 0, 0, 0, 0, 0),
    (-10, 0, 5, 20, 0, 0),
    (10, 0, -5, -20, 0, 0),
    (0, -5, 5, 0, 30, 0),
    (0, 5, -5, 0, -30, 0),
    (0, 0, 0, 25, 0, 40),
    (0, 0, 0, -25, 0, -40),
    (-8, 0, 0, 0, -25, 35),
    (8, 0, 0, 0, 25, -35),
    (0, -5, 10, -20, 35, -25),
    (0, 5, -10, 20, -35, 25),
    (-12, -5, 0, 15, 20, 45),
    (12, 5, 0, -15, -20, -45),
    (0, 0, 0, 30, 25, -30),
    (0, 0, 0, -30, -25, 30),
    (0, 0, 0, 0, 40, 0),
]


def clamp_pose(deg):
    return [min(max(d, lo), hi) for d, (lo, hi) in zip(deg, JOINT_LIMITS_DEG)]


def graceful_shutdown(robot, seconds=2.0):
    print("[collect] ramping gravity comp to zero — SUPPORT THE ARM", flush=True)
    g0 = float(getattr(robot, "gravity_comp_factor", 1.0))
    steps = max(int(seconds / 0.1), 1)
    for i in range(1, steps + 1):
        robot.gravity_comp_factor = g0 * (1.0 - i / steps)
        time.sleep(0.1)
    robot.stop()  # motors DISABLE — arm goes limp


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("[collect] opening robot (position-hold mode)...", flush=True)
    bus = EchoFilterBus(open_bus())
    gr.can.interface.Bus = lambda **kw: bus
    robot = gr.get_a1z_robot(
        gravity_comp_factor=1.0,
        zero_gravity_mode=False,   # position hold
        control_freq_hz=250,
    )
    robot.start()  # locks current pose
    base_deg = np.rad2deg(np.asarray(robot.get_joint_state()["pos"]))
    print(f"[collect] locked base pose (deg): {np.round(base_deg, 1).tolist()}", flush=True)

    cap = cv2.VideoCapture(CAM_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    if not cap.isOpened():
        graceful_shutdown(robot)
        sys.exit("cannot open camera")

    n_saved = len(list(DATA_DIR.glob("sample_*.png")))
    if n_saved:
        print(f"note: {n_saved} existing samples, appending")

    try:
        for k, off in enumerate(OFFSETS_DEG):
            target_deg = clamp_pose((base_deg + np.array(off)).tolist())
            print(f"[collect] pose {k + 1}/{len(OFFSETS_DEG)} -> {np.round(target_deg, 1).tolist()}",
                  flush=True)
            robot.move_joints(np.deg2rad(np.array(target_deg)), speed=MOVE_SPEED)
            time.sleep(SETTLE_S)

            # fresh frame after settling
            for _ in range(5):
                cap.read()
            ok, frame = cap.read()
            if not ok:
                print("[collect]   camera read failed, skip", flush=True)
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            corners = find_board(gray)
            if corners is None:
                print("[collect]   board not visible, skip", flush=True)
                continue
            sharp = cv2.Laplacian(gray, cv2.CV_64F).var()
            q = np.asarray(robot.get_joint_state()["pos"])
            idx = n_saved
            cv2.imwrite(str(DATA_DIR / f"sample_{idx:02d}.png"), frame)
            with open(DATA_DIR / f"sample_{idx:02d}.json", "w") as f:
                json.dump({"pos": q.tolist(),
                           "pos_deg": np.rad2deg(q).round(3).tolist(),
                           "sharpness": round(float(sharp), 1),
                           "timestamp": time.time()}, f, indent=1)
            n_saved += 1
            print(f"[collect]   SAVED sample {idx} (sharp={sharp:.0f})", flush=True)

            vis = frame.copy()
            cv2.drawChessboardCorners(vis, PATTERN_SIZE, corners, True)
            cv2.putText(vis, f"pose {k + 1}/{len(OFFSETS_DEG)}  saved {n_saved}",
                        (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)
            cv2.imshow("handeye collect", vis)
            if cv2.waitKey(1) in (27, ord("q")):
                print("[collect] aborted by user", flush=True)
                break

        print("[collect] returning to base pose", flush=True)
        robot.move_joints(np.deg2rad(base_deg), speed=MOVE_SPEED)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        graceful_shutdown(robot)
        bus.shutdown()
        print(f"[collect] done: {n_saved} samples in {DATA_DIR}", flush=True)


if __name__ == "__main__":
    main()

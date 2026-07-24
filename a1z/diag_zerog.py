"""Diagnose per-joint gravity compensation in zero-gravity mode.

Starts the arm in zero-gravity mode and prints, per joint:
  pos      measured position (deg)
  cmd_tau  feedforward torque commanded to the motor (Nm, motor frame)
  fb_tau   torque reported by the motor feedback (Nm, motor frame)
  err      motor error code (1 = normal, 0 = disabled, else fault)

How to read it:
  - err != 1 on J4          -> motor faulted / not enabling (firmware issue)
  - cmd_tau large, fb_tau ~0 -> torque frame not applied (encoding/range issue)
  - cmd_tau ~0 where gravity should pull -> gravity model wrong (e.g. missing
    gripper mass — try --gripper to load the A1Z_G1Z.urdf model)

Usage:
    python diag_zerog.py              # flange URDF (no gripper mass)
    python diag_zerog.py --gripper    # G1Z gripper URDF

Ctrl+C to stop — motors DISABLE, arm goes limp. Support it first.
"""

import signal
import sys
import time

import numpy as np

sys.path.insert(0, "GALAXEA-A1Z")
sys.path.insert(0, ".")

from a1z_mac import EchoFilterBus, open_bus  # noqa: E402

import a1z.robots.get_robot as gr  # noqa: E402

WITH_GRIPPER = "--gripper" in sys.argv

bus = EchoFilterBus(open_bus())
gr.can.interface.Bus = lambda **kw: bus

robot = gr.get_a1z_robot(
    gravity_comp_factor=1.0,
    zero_gravity_mode=True,
    control_freq_hz=250,
    with_gripper=WITH_GRIPPER,
)

running = True


def handle_sig(signum, frame):
    global running
    running = False


signal.signal(signal.SIGINT, handle_sig)
signal.signal(signal.SIGTERM, handle_sig)

print(f"[diag] zero-gravity mode, with_gripper={WITH_GRIPPER}", flush=True)
robot.start()
print("[diag] control loop running. Drag J4 to a loaded pose and watch cmd_tau vs fb_tau.", flush=True)
print("[diag] Ctrl+C to stop (motors go limp!).\n", flush=True)

joint_sign = np.array([1.0, 1.0, -1.0, 1.0, -1.0, 1.0])
zeros = np.zeros(6)

header = "joint |   pos(deg) |  cmd_tau |   fb_tau | err"
print(header, flush=True)
print("-" * len(header), flush=True)

while running and robot.is_running:
    state = robot.get_joint_state()
    q = state["pos"]                       # URDF frame
    tau_id = robot._gravity_model.compute_inverse_dynamics(q, zeros, zeros)
    cmd_tau = tau_id * robot.gravity_comp_factor * joint_sign   # motor frame
    fb_tau = state["eff"] * joint_sign                          # motor frame
    errs = state["error_codes"]
    for j in range(6):
        mark = " <-- J4" if j == 3 else ""
        print(
            f"  J{j + 1}  | {np.degrees(q[j]):10.2f} | {cmd_tau[j]:8.2f} | {fb_tau[j]:8.2f} | 0x{int(errs[j]):X}{mark}",
            flush=True,
        )
    print(flush=True)
    time.sleep(1.0)

print("[diag] stopping (motors disabling)...", flush=True)
robot.stop()
bus.shutdown()
print("[diag] done.", flush=True)

"""A1Z loaded-pose hold (stress test) on macOS via gs_usb.

Same control as hold_neutral.py, but moves to a pose with large gravity load
(arm extended forward, J2/J3/J4 under continuous holding torque), then holds.
Ctrl+C / SIGTERM: keeps torques until process exits, then motors DISABLE
(arm goes limp) — support the arm or cut power first.
"""

import signal
import sys
import time

import numpy as np

sys.path.insert(0, "GALAXEA-A1Z")
sys.path.insert(0, ".")

from a1z_mac import EchoFilterBus, open_bus

# Loaded pose: arm reaches far forward, gravity torque concentrated on j2/j3/j4
# Within joint limits: j2 0..180, j3 -180..0 deg
LOADED_DEG = [0.0, 70.0, -35.0, -35.0, 0.0, 0.0]
MOVE_SPEED = 0.3  # rad/s

bus = EchoFilterBus(open_bus())

import a1z.robots.get_robot as gr

gr.can.interface.Bus = lambda **kw: bus

robot = gr.get_a1z_robot(
    gravity_comp_factor=1.0,
    zero_gravity_mode=False,
    control_freq_hz=250,
)

running = True


def handle_sig(signum, frame):
    global running
    running = False


signal.signal(signal.SIGINT, handle_sig)
signal.signal(signal.SIGTERM, handle_sig)

print("[stress] starting control loop (position hold at current pose)...", flush=True)
robot.start()
print("[stress] control loop running. current state:", flush=True)

state = robot.get_joint_state()
print("  pos(deg):", np.round(np.degrees(state["pos"]), 2), flush=True)

target = np.deg2rad(np.array(LOADED_DEG))
print(f"[stress] moving to loaded pose {LOADED_DEG} deg at {MOVE_SPEED} rad/s...", flush=True)
robot.move_joints(target, speed=MOVE_SPEED)
print("[stress] target reached, holding under load. Ctrl+C to stop (motors will go limp!).", flush=True)

t0 = time.time()
while running and robot.is_running:
    state = robot.get_joint_state()
    pos_deg = np.degrees(state["pos"])
    eff = state["eff"]
    print(
        f"  t={time.time() - t0:6.1f}s  pos(deg): [{', '.join(f'{p:7.2f}' for p in pos_deg)}]  "
        f"eff(Nm): [{', '.join(f'{e:6.2f}' for e in eff)}]",
        flush=True,
    )
    time.sleep(1.0)

print("[stress] stopping (motors disabling)...", flush=True)
robot.stop()
bus.shutdown()
print("[stress] done.", flush=True)

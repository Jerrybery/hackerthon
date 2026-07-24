"""A1Z position hold on macOS via gs_usb.

Starts in position-hold (PD + gravity comp) at current pose, moves slowly to a
neutral pose, then holds. Ctrl+C / SIGTERM: keeps torques until process exits,
then motors DISABLE (arm goes limp) — support the arm or cut power first.
"""

import signal
import sys
import time

import numpy as np

sys.path.insert(0, "GALAXEA-A1Z")
sys.path.insert(0, ".")

from a1z_mac import EchoFilterBus, open_bus

# Within joint limits: j3 range is [-180, 0] deg, so bend negative
NEUTRAL_DEG = [0.0, 34.0, -23.0, -29.0, 0.0, 0.0]
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

print("[hold] starting control loop (position hold at current pose)...", flush=True)
robot.start()
print("[hold] control loop running. current state:", flush=True)

state = robot.get_joint_state()
print("  pos(deg):", np.round(np.degrees(state["pos"]), 2), flush=True)

target = np.deg2rad(np.array(NEUTRAL_DEG))
print(f"[hold] moving to neutral {NEUTRAL_DEG} deg at {MOVE_SPEED} rad/s...", flush=True)
robot.move_joints(target, speed=MOVE_SPEED)
print("[hold] target reached, holding. Ctrl+C to stop (motors will go limp!).", flush=True)

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

"""Visual-servo grasp helper for the A1Z wrist camera (agent-in-the-loop).

The wrist camera looks along the gripper approach direction, so the TCP
aim point projects to a CONSTANT pixel. This script captures a frame,
draws that aim point + a grid, and saves it for the agent to read the
bottle's pixel offset. A second mode converts a pixel offset (read by
the agent) into a lateral TCP correction and commands it via MCP.

Usage (from repo root):
  a1z/.venv/bin/python a1z/grasp_servo.py capture          # -> /tmp/servo_view.jpg
  a1z/.venv/bin/python a1z/grasp_servo.py correct DU DV Z_DIST
      # DU,DV: bottle pixel minus aim pixel (px); Z_DIST: rough bottle
      # distance from camera (m). Moves TCP laterally to cancel the offset.
  a1z/.venv/bin/python a1z/grasp_servo.py tcp              # print current TCP pose
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

A1Z_DIR = Path(__file__).parent
CAL_DIR = A1Z_DIR / "calibration"
sys.path.insert(0, str(A1Z_DIR))

from mcp_call import McpSession  # noqa: E402

CAM_INDEX = 0
WIDTH, HEIGHT = 1920, 1080
FWD_M = 0.5  # aim point distance along flange +X


def load_calib():
    fs = cv2.FileStorage(str(CAL_DIR / "camera_intrinsics.yaml"), cv2.FILE_STORAGE_READ)
    K = fs.getNode("camera_matrix").mat()
    dist = fs.getNode("dist_coeffs").mat()
    fs.release()
    fs = cv2.FileStorage(str(CAL_DIR / "handeye_result.yaml"), cv2.FILE_STORAGE_READ)
    X = fs.getNode("T_ee_camera").mat()
    fs.release()
    return K, dist, X


def aim_pixel(K, dist, X):
    """Pixel of a point FWD_M ahead of the flange along +X (constant)."""
    p_cam = np.linalg.inv(X) @ np.array([FWD_M, 0, 0, 1.0])
    pts, _ = cv2.projectPoints(p_cam[:3].reshape(1, 3), np.zeros(3), np.zeros(3), K, dist)
    return pts.reshape(2)


def get_state(sess):
    """Return (T_base_cam, T_base_tcp, rpy_deg, q_deg) via MCP + FK."""
    import pinocchio as pin
    from a1z.robots.kinematics import Kinematics

    kin = Kinematics(str(A1Z_DIR / "GALAXEA-A1Z/a1z/robot_models/a1z/A1Z_Flange.urdf"),
                     end_effector_frame="arm_link6")
    resp = sess.tool("get_joint_state", {})
    pos_str = resp.split("pos(deg)=")[1].split("]")[0].strip("[ ")
    q_deg = np.array([float(v) for v in pos_str.split(",")])
    q = np.deg2rad(q_deg)
    _, _, X = load_calib()
    T_flange = kin.fk(q)
    T_base_cam = T_flange @ X
    T_tcp = T_flange.copy()
    T_tcp[:3, 3] = T_flange[:3, 3] + T_flange[:3, :3] @ np.array([0.10, 0, 0])
    rpy = np.rad2deg(pin.rpy.matrixToRpy(T_flange[:3, :3]))
    return T_base_cam, T_tcp, rpy, q_deg


def capture():
    K, dist, X = load_calib()
    ax, ay = aim_pixel(K, dist, X)
    cap = cv2.VideoCapture(CAM_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    for _ in range(10):
        cap.read()
    ok, frame = cap.read()
    cap.release()
    if not ok:
        sys.exit("camera read failed")
    cv2.drawMarker(frame, (int(ax), int(ay)), (0, 0, 255), cv2.MARKER_CROSS, 40, 3)
    for x in range(0, WIDTH, 100):
        cv2.line(frame, (x, 0), (x, HEIGHT), (0, 200, 0), 1)
    for y in range(0, HEIGHT, 100):
        cv2.line(frame, (0, y), (WIDTH, y), (0, 200, 0), 1)
    cv2.imwrite("/tmp/servo_view.jpg", frame)
    print(f"aim pixel = ({ax:.0f}, {ay:.0f}), grid = 100px -> /tmp/servo_view.jpg")


def correct(du: float, dv: float, z_dist: float):
    K, dist, X = load_calib()
    sess = McpSession()
    sess.initialize()
    T_base_cam, T_tcp, rpy, _ = get_state(sess)
    fx = K[0, 0]
    # lateral offset in camera frame (no depth change), then to base frame
    d_cam = np.array([du * z_dist / fx, dv * z_dist / fx, 0.0])
    d_base = T_base_cam[:3, :3] @ d_cam
    p = T_tcp[:3, 3] + d_base
    args = {"x": float(p[0]), "y": float(p[1]), "z": float(p[2]),
            "roll_deg": float(rpy[0]), "pitch_deg": float(rpy[1]), "yaw_deg": float(rpy[2]),
            "speed": 0.15}
    print(f"correction d_base={np.round(d_base, 4).tolist()}, target={np.round(p, 4).tolist()}")
    print(sess.tool("move_to_tcp", args))


def tcp():
    sess = McpSession()
    sess.initialize()
    _, T_tcp, rpy, q_deg = get_state(sess)
    p = T_tcp[:3, 3]
    print(f"tcp xyz=[{p[0]:.4f}, {p[1]:.4f}, {p[2]:.4f}] rpy(deg)=[{rpy[0]:.1f}, {rpy[1]:.1f}, {rpy[2]:.1f}]")
    print(f"joints(deg)={q_deg.tolist()}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "capture":
        capture()
    elif cmd == "correct":
        correct(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
    elif cmd == "tcp":
        tcp()
    else:
        sys.exit(__doc__)

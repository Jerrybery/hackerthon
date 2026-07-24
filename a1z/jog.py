"""Joint-space Cartesian jog for the A1Z arm via MCP (bypasses server IK).

Computes a joint-space step that moves the TCP by a desired base-frame
delta while holding orientation, using a local Pinocchio model (damped
least squares with internal FK refinement), then commands it with the
`move_to_pose` skill (no server-side IK involved). Small steps only.

Usage (from repo root):
  a1z/.venv/bin/python a1z/jog.py DX DY DZ [SPEED]
      DX,DY,DZ: desired TCP translation in base frame (m), small (<=0.05).
      SPEED: joint speed rad/s (default 0.15).
Prints the predicted TCP delta and the move result.
"""

import sys
from pathlib import Path

import numpy as np

A1Z_DIR = Path(__file__).parent
sys.path.insert(0, str(A1Z_DIR))

from mcp_call import McpSession  # noqa: E402

URDF_PATH = A1Z_DIR / "GALAXEA-A1Z/a1z/robot_models/a1z/A1Z_Flange.urdf"
EE_FRAME = "arm_link6"
JOINT_LIMITS_DEG = [
    (-120.0, 120.0),
    (0.0, 180.0),
    (-180.0, 0.0),
    (-85.0, 85.0),
    (-85.0, 85.0),
    (-115.0, 115.0),
]


def main():
    import pinocchio as pin

    dx, dy, dz = (float(a) for a in sys.argv[1:4])
    speed = float(sys.argv[4]) if len(sys.argv) > 4 else 0.15
    delta = np.array([dx, dy, dz])
    if np.linalg.norm(delta) > 0.06:
        sys.exit("step too large, keep <= 0.06 m")

    sess = McpSession()
    sess.initialize()
    resp = sess.tool("get_joint_state", {})
    pos_str = resp.split("pos(deg)=")[1].split("]")[0].strip("[ ")
    q = np.deg2rad(np.array([float(v) for v in pos_str.split(",")]))

    model = pin.buildModelFromUrdf(str(URDF_PATH))
    data = model.createData()
    fid = model.getFrameId(EE_FRAME)

    pin.forwardKinematics(model, data, q)
    pin.updateFramePlacements(model, data)
    T0 = data.oMf[fid].homogeneous.copy()
    T_tgt = T0.copy()
    T_tgt[:3, 3] += delta

    lo = np.deg2rad([l for l, _ in JOINT_LIMITS_DEG])
    hi = np.deg2rad([h for _, h in JOINT_LIMITS_DEG])
    for _ in range(300):
        pin.forwardKinematics(model, data, q)
        pin.updateFramePlacements(model, data)
        err = T_tgt[:3, 3] - data.oMf[fid].homogeneous[:3, 3]  # position only
        if np.linalg.norm(err) < 1e-5:
            break
        J = pin.computeFrameJacobian(model, data, q, fid, pin.LOCAL_WORLD_ALIGNED)[:3]
        dq = J.T @ np.linalg.solve(J @ J.T + 1e-3 * np.eye(3), err)
        q = np.clip(pin.integrate(model, q, dq * 0.2), lo, hi)

    pin.forwardKinematics(model, data, q)
    pin.updateFramePlacements(model, data)
    T1 = data.oMf[fid].homogeneous
    got = T1[:3, 3] - T0[:3, 3]
    print(f"predicted TCP delta={np.round(got, 4).tolist()} (wanted {delta.tolist()})")
    q_deg = np.rad2deg(q)
    print(f"target joints(deg)={np.round(q_deg, 2).tolist()}")
    print(sess.tool("move_to_pose", {"joints_deg": q_deg.tolist(), "speed": speed}))


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    main()

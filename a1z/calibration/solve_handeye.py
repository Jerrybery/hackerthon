"""Solve eye-in-hand calibration (AX = XB) from collected samples.

For each sample: checkerboard pose in camera frame (solvePnP with the
intrinsics from camera_intrinsics.yaml) + flange (arm_link6) pose in
base frame (Pinocchio FK on the recorded joint positions, which the SDK
reports in URDF convention). cv2.calibrateHandEye then gives the fixed
camera->flange transform.

The 9x7-square board is symmetric under 180 deg rotation, so corner
ordering can flip between views (corner array reversed). For every
sample we compute BOTH candidate board poses (as-detected and with the
corner array reversed) and greedily pick the assignment minimizing the
global AX=XB residual.

Usage (from repo root):
    a1z/.venv/bin/python a1z/calibration/solve_handeye.py
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

CAL_DIR = Path(__file__).parent
A1Z_DIR = CAL_DIR.parent
sys.path.insert(0, str(CAL_DIR))
sys.path.insert(0, str(A1Z_DIR))

from capture_intrinsics import find_board, PATTERN_SIZE, SQUARE_SIZE_M  # noqa: E402
from a1z.robots.kinematics import Kinematics                            # noqa: E402

URDF = A1Z_DIR / "GALAXEA-A1Z" / "a1z" / "robot_models" / "a1z" / "A1Z_Flange.urdf"
EE_FRAME = "arm_link6"
DATA_DIR = CAL_DIR / "data" / "handeye"
VIS_DIR = DATA_DIR / "vis"
INTRINSICS = CAL_DIR / "camera_intrinsics.yaml"
OUT_YAML = CAL_DIR / "handeye_result.yaml"

METHODS = {
    "TSAI": cv2.CALIB_HAND_EYE_TSAI,
    "PARK": cv2.CALIB_HAND_EYE_PARK,
    "HORAUD": cv2.CALIB_HAND_EYE_HORAUD,
    "ANDREFF": cv2.CALIB_HAND_EYE_ANDREFF,
    "DANIILIDIS": cv2.CALIB_HAND_EYE_DANIILIDIS,
}


def board_object_points():
    objp = np.zeros((PATTERN_SIZE[0] * PATTERN_SIZE[1], 3), np.float32)
    objp[:, :2] = (np.mgrid[0:PATTERN_SIZE[0], 0:PATTERN_SIZE[1]].T.reshape(-1, 2)
                   * SQUARE_SIZE_M)
    return objp


def board_pose(objp, corners, K, dist):
    """4x4 target->camera pose via planar IPPE."""
    ok, rvec, tvec = cv2.solvePnP(objp, corners, K, dist, flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        return None
    T = np.eye(4)
    T[:3, :3] = cv2.Rodrigues(rvec)[0]
    T[:3, 3] = tvec.ravel()
    return T


def pair_residuals(T_g2b, T_t2c, X):
    """Consistency residuals (deg, mm) via T_base_board = T_g2b @ X @ T_t2c:
    p_base = T_g2b @ X(cam2gripper) @ T_t2c(board2cam) @ p_board, and the
    board is static in the world, so all samples must yield the same
    board pose in the base frame. Convention-free AX=XB equivalent."""
    n = len(T_g2b)
    T_bb = [T_g2b[i] @ X @ T_t2c[i] for i in range(n)]
    rot = np.zeros((n, n))
    tr = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            E = np.linalg.inv(T_bb[i]) @ T_bb[j]  # == I iff consistent
            ang = np.degrees(np.arccos(np.clip((np.trace(E[:3, :3]) - 1) / 2, -1, 1)))
            rot[i, j] = rot[j, i] = ang
            tr[i, j] = tr[j, i] = np.linalg.norm(E[:3, 3]) * 1000
    mask = ~np.eye(n, dtype=bool)
    return rot, tr, rot[mask].mean(), tr[mask].mean()


def solve_once(T_g2b, T_t2c, method):
    R_g2b = [T[:3, :3] for T in T_g2b]
    t_g2b = [T[:3, 3] for T in T_g2b]
    R_t2c = [T[:3, :3] for T in T_t2c]
    t_t2c = [T[:3, 3] for T in T_t2c]
    R_c2g, t_c2g = cv2.calibrateHandEye(R_g2b, t_g2b, R_t2c, t_t2c, method=method)
    X = np.eye(4)
    X[:3, :3] = R_c2g
    X[:3, 3] = np.asarray(t_c2g).ravel()
    return X


def main():
    fs = cv2.FileStorage(str(INTRINSICS), cv2.FILE_STORAGE_READ)
    K = fs.getNode("camera_matrix").mat()
    dist = fs.getNode("dist_coeffs").mat()
    fs.release()
    if K is None:
        sys.exit(f"intrinsics not found: {INTRINSICS}")

    kin = Kinematics(str(URDF), end_effector_frame=EE_FRAME)
    objp = board_object_points()

    names, T_g2b, candidates = [], [], []
    for img_path in sorted(DATA_DIR.glob("sample_*.png")):
        meta_path = img_path.with_suffix(".json")
        if not meta_path.exists():
            continue
        img = cv2.imread(str(img_path))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        corners = find_board(gray)
        if corners is None:
            print(f"skip {img_path.name}: board not found")
            continue
        T0 = board_pose(objp, corners, K, dist)
        T1 = board_pose(objp, corners[::-1].copy(), K, dist)  # reversed = 180 deg flip
        if T0 is None or T1 is None:
            print(f"skip {img_path.name}: solvePnP failed")
            continue
        q = np.array(json.load(open(meta_path))["pos"])
        names.append(img_path.name)
        T_g2b.append(kin.fk(q))
        candidates.append((T0, T1))
        print(f"loaded {img_path.name}: board z={T0[2,3]:.3f}m")

    n = len(T_g2b)
    if n < 5:
        sys.exit(f"need >=5 valid samples, have {n}")
    print(f"\nsolving on {n} samples (greedy deflip vs 180-deg corner-order ambiguity)")

    # greedy deflip: start all as-detected, repeatedly flip the sample whose
    # pairs are worst, keeping flips that reduce the global residual
    choice = [0] * n
    method = METHODS["TSAI"]

    def current():
        return [candidates[i][choice[i]] for i in range(n)]

    X = solve_once(T_g2b, current(), method)
    rot, tr, rot_m, tr_m = pair_residuals(T_g2b, current(), X)
    best_score = rot_m + tr_m / 100
    print(f"initial: rot={rot_m:.2f}deg tr={tr_m:.1f}mm")
    for _ in range(2 * n):
        per_sample = rot.mean(axis=1) + tr.mean(axis=1) / 100
        worst = int(np.argmax(per_sample))
        choice[worst] ^= 1
        X_new = solve_once(T_g2b, current(), method)
        rot, tr, rot_m, tr_m = pair_residuals(T_g2b, current(), X_new)
        score = rot_m + tr_m / 100
        if score < best_score - 1e-6:
            best_score, X = score, X_new
            print(f"flip {names[worst]}: rot={rot_m:.2f}deg tr={tr_m:.1f}mm")
        else:
            choice[worst] ^= 1  # revert, no improvement
            break

    flipped = [names[i] for i in range(n) if choice[i] == 1]
    print(f"flipped samples: {flipped if flipped else 'none'}")

    best = None
    T_t2c = current()
    for name, m in METHODS.items():
        X_m = solve_once(T_g2b, T_t2c, m)
        rot, tr, rot_m, tr_m = pair_residuals(T_g2b, T_t2c, X_m)
        mask = ~np.eye(n, dtype=bool)
        print(f"{name:11s} rot_err mean={rot_m:.3f}deg max={rot[mask].max():.3f}deg  "
              f"tr_err mean={tr_m:.2f}mm max={tr[mask].max():.2f}mm")
        score = rot_m + tr_m / 100
        if best is None or score < best[0]:
            best = (score, name, X_m)

    _, name, X = best
    print(f"\nbest method: {name}")
    print(f"T_flange_camera (camera in {EE_FRAME} frame) =\n{np.round(X, 5)}")

    # visualize: draw board pose axes on a few samples
    VIS_DIR.mkdir(exist_ok=True)
    for idx in range(0, n, max(1, n // 4)):
        img = cv2.imread(str(DATA_DIR / names[idx]))
        rvec = cv2.Rodrigues(T_t2c[idx][:3, :3])[0]
        cv2.drawFrameAxes(img, K, dist, rvec, T_t2c[idx][:3, 3], 0.06)
        cv2.imwrite(str(VIS_DIR / f"boardpose_{names[idx]}"), img)

    fs = cv2.FileStorage(str(OUT_YAML), cv2.FILE_STORAGE_WRITE)
    fs.write("method", name)
    fs.write("ee_frame", EE_FRAME)
    fs.write("n_samples", n)
    fs.write("T_ee_camera", X)
    fs.write("R_ee_camera", X[:3, :3])
    fs.write("t_ee_camera", X[:3, 3])
    fs.release()
    print(f"saved -> {OUT_YAML}")
    print(f"visual check -> {VIS_DIR}")


if __name__ == "__main__":
    main()

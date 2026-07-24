"""Camera intrinsics calibration for the A1Z wrist camera (KS2A418).

Checkerboard: inner corners x square size set below (confirm with the
physical board before capturing!).

Usage (from repo root, a1z venv):
    a1z/.venv/bin/python a1z/calibration/capture_intrinsics.py capture
    a1z/.venv/bin/python a1z/calibration/capture_intrinsics.py calibrate

capture: live view. Detection runs on a half-res frame every 3rd frame
so the preview stays fluid; saving re-detects on the full-res frame for
accuracy. Auto-saves when the board is detected, sharp, and in a pose
sufficiently different from already-saved views. Move the board around
to cover the whole image with varied tilts/distances; the WHOLE board
(white margin included) must stay inside the frame. Gets 20 views then
exits. Keys: q/ESC = stop early.

calibrate: runs cv2.calibrateCamera on the saved frames, prints the
reprojection error, writes camera_intrinsics.yaml next to the data dir.
"""

import sys
import time
from pathlib import Path

import cv2
import numpy as np

PATTERN_SIZE = (8, 6)        # inner corners (cols, rows) for a 9x7-square board
SQUARE_SIZE_M = 0.030        # 30 mm
N_TARGET = 20                # views to collect
MIN_CENTER_DIST = 0.08       # min normalized distance of board center vs saved views
MIN_TIME_GAP_S = 0.8
DETECT_EVERY = 3             # run board detection every N frames
DETECT_SCALE = 2             # detect on frame downscaled by this factor
CAM_INDEX = 0
WIDTH, HEIGHT = 1920, 1080

DATA_DIR = Path(__file__).parent / "data" / "intrinsics"
OUT_YAML = Path(__file__).parent / "camera_intrinsics.yaml"


def find_board(gray):
    """Return refined corners (Nx1x2 float32) or None."""
    flags = cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY
    ok, corners = cv2.findChessboardCornersSB(gray, PATTERN_SIZE, flags)
    if not ok:
        ok, corners = cv2.findChessboardCorners(
            gray, PATTERN_SIZE,
            cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK,
        )
        if not ok:
            return None
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3)
    return cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), criteria)


def capture():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(CAM_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    if not cap.isOpened():
        sys.exit("cannot open camera")

    saved_centers = []   # normalized board centers of saved views
    n_saved = len(list(DATA_DIR.glob("view_*.png")))
    if n_saved:
        print(f"note: {n_saved} existing views in {DATA_DIR}, new ones append")
    last_save = 0.0
    det_corners = None       # full-res coords from latest detection
    det_time = 0.0
    frame_i = 0
    t_fps, n_fps, fps = time.time(), 0, 0.0
    print("move the board: cover all image regions, vary tilt and distance")

    while n_saved < N_TARGET:
        ok, frame = cap.read()
        if not ok:
            continue
        frame_i += 1
        n_fps += 1
        if time.time() - t_fps > 2.0:
            fps = n_fps / (time.time() - t_fps)
            t_fps, n_fps = time.time(), 0

        # detection on downscaled frame, every N frames
        if frame_i % DETECT_EVERY == 0:
            small = cv2.resize(frame, (WIDTH // DETECT_SCALE, HEIGHT // DETECT_SCALE))
            gray_small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            corners_s = find_board(gray_small)
            det_corners = corners_s * DETECT_SCALE if corners_s is not None else None
            det_time = time.time()

        vis = frame.copy()
        msg, color = "no board", (0, 0, 255)

        if det_corners is not None and time.time() - det_time < 1.0:
            cv2.drawChessboardCorners(vis, PATTERN_SIZE, det_corners, True)
            center = det_corners.reshape(-1, 2).mean(axis=0) / np.array([WIDTH, HEIGHT])
            spread = det_corners.reshape(-1, 2).std(axis=0).mean() / WIDTH
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sharp = cv2.Laplacian(gray, cv2.CV_64F).var()
            too_close = any(np.linalg.norm(center - c) < MIN_CENTER_DIST for c in saved_centers)
            if sharp < 80:
                msg, color = f"too blurry ({sharp:.0f})", (0, 165, 255)
            elif spread < 0.03:
                msg, color = "board too small/far", (0, 165, 255)
            elif too_close or time.time() - last_save < MIN_TIME_GAP_S:
                msg, color = "move board to a new pose", (0, 165, 255)
            else:
                # re-detect on the full-res frame for accurate corners
                corners_full = find_board(gray)
                if corners_full is not None:
                    path = DATA_DIR / f"view_{n_saved:02d}.png"
                    cv2.imwrite(str(path), frame)
                    saved_centers.append(center)
                    n_saved += 1
                    last_save = time.time()
                    msg, color = f"SAVED {n_saved}/{N_TARGET}", (0, 255, 0)
                    print(f"saved {path} (sharp={sharp:.0f})", flush=True)

        cv2.putText(vis, f"{n_saved}/{N_TARGET}  {msg}  {fps:.0f}fps", (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
        cv2.imshow("intrinsics capture", vis)
        if cv2.waitKey(1) in (27, ord("q")):
            break

    cap.release()
    cv2.destroyAllWindows()
    print(f"done: {n_saved} views in {DATA_DIR}")


def calibrate():
    files = sorted(DATA_DIR.glob("view_*.png"))
    if len(files) < 8:
        sys.exit(f"need >=8 views, have {len(files)}")

    objp = np.zeros((PATTERN_SIZE[0] * PATTERN_SIZE[1], 3), np.float32)
    objp[:, :2] = (np.mgrid[0:PATTERN_SIZE[0], 0:PATTERN_SIZE[1]].T.reshape(-1, 2)
                   * SQUARE_SIZE_M)

    objpoints, imgpoints, img_size = [], [], None
    for f in files:
        img = cv2.imread(str(f))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img_size = gray.shape[::-1]
        corners = find_board(gray)
        if corners is None:
            print(f"skip {f.name}: board not found")
            continue
        objpoints.append(objp)
        imgpoints.append(corners)

    print(f"calibrating on {len(objpoints)} views, image size {img_size}")
    rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(
        objpoints, imgpoints, img_size, None, None)

    # per-view reprojection error
    errs = []
    for i in range(len(objpoints)):
        proj, _ = cv2.projectPoints(objpoints[i], rvecs[i], tvecs[i], K, dist)
        errs.append(cv2.norm(imgpoints[i].reshape(-1, 2), proj.reshape(-1, 2), cv2.NORM_L2) / len(proj))
    print(f"RMS reprojection error: {rms:.4f} px")
    print(f"mean per-view error: {np.mean(errs):.4f} px (max {np.max(errs):.4f}, view {int(np.argmax(errs))})")
    print(f"K =\n{K}")
    print(f"dist = {dist.ravel()}")

    fs = cv2.FileStorage(str(OUT_YAML), cv2.FILE_STORAGE_WRITE)
    fs.write("image_width", img_size[0])
    fs.write("image_height", img_size[1])
    fs.write("pattern_cols", PATTERN_SIZE[0])
    fs.write("pattern_rows", PATTERN_SIZE[1])
    fs.write("square_size_m", SQUARE_SIZE_M)
    fs.write("camera_matrix", K)
    fs.write("dist_coeffs", dist)
    fs.write("rms_reprojection_error", rms)
    fs.release()
    print(f"saved -> {OUT_YAML}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("capture", "calibrate"):
        sys.exit(__doc__)
    {"capture": capture, "calibrate": calibrate}[sys.argv[1]]()

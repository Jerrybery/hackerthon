"""Annotated-image grasp helpers for the A1Z wrist camera.

Pure-function module used by the MCP skills in a1z_mcp_server.py:
- load_calib(): wrist-camera intrinsics + eye-in-hand extrinsics
- find_annotation_pixel(): locate the red annotation mark in an image
- pixel_to_base(): back-project a pixel onto the tabletop plane (z = const)
  to get a 3D point in the arm base frame (monocular camera, no depth:
  the plane supplies the missing dimension).
"""

from pathlib import Path

import cv2
import numpy as np

A1Z_DIR = Path(__file__).parent
CAL_DIR = A1Z_DIR / "calibration"

CAM_INDEX = 0
WIDTH, HEIGHT = 1920, 1080
FWD_M = 0.5  # aim point distance along flange +X

# Red annotation mask: HSV, two hue bands (red wraps around 0/180).
_RED_LO1, _RED_HI1 = np.array([0, 80, 80]), np.array([10, 255, 255])
_RED_LO2, _RED_HI2 = np.array([170, 80, 80]), np.array([180, 255, 255])
_MIN_BLOB_AREA_PX = 100


def load_calib():
    """Return (K, dist, T_ee_camera) from the calibration YAMLs."""
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


def capture_frame():
    """Grab one frame from the wrist camera. Returns BGR image or None."""
    cap = cv2.VideoCapture(CAM_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    for _ in range(10):
        cap.read()
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def find_annotation_pixel(img) -> tuple[float, float] | None:
    """Locate the red annotation mark; return its centroid (u, v) or None.

    Works for rings, filled circles, dots and bbox outlines. Returns the
    centroid of the largest red blob (>= _MIN_BLOB_AREA_PX).
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, _RED_LO1, _RED_HI1) | cv2.inRange(hsv, _RED_LO2, _RED_HI2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    best = max(contours, key=cv2.contourArea)
    if cv2.contourArea(best) < _MIN_BLOB_AREA_PX:
        return None
    m = cv2.moments(best)
    if m["m00"] == 0:
        return None
    return m["m10"] / m["m00"], m["m01"] / m["m00"]


def pixel_to_base(u: float, v: float, table_z: float,
                  T_base_cam: np.ndarray, K: np.ndarray, dist: np.ndarray):
    """Back-project pixel (u, v) onto the plane z=table_z (base frame).

    Returns the 3D point as np.array([x, y, z]), or None if the ray does
    not intersect the plane in front of the camera.
    """
    pts = cv2.undistortPoints(np.array([[[u, v]]], dtype=np.float64), K, dist)
    xn, yn = pts[0, 0]
    ray_cam = np.array([xn, yn, 1.0])
    o = T_base_cam[:3, 3]
    d = T_base_cam[:3, :3] @ ray_cam
    if abs(d[2]) < 1e-9:
        return None
    t = (table_z - o[2]) / d[2]
    if t <= 0:
        return None
    return o + t * d

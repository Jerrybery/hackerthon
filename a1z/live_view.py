"""Live wrist-camera viewer for the A1Z annotated-grasp pipeline.

Web page (http://localhost:8080) with two side-by-side MJPEG panels:
- raw: the wrist camera feed
- enhanced: same feed + TCP aim cross, 100px grid, red-annotation
  detection (magenta circle) and the back-projected 3D target point,
  so you can watch both while MCP grasp tools run.

The latest raw frame is also written to /tmp/wrist_live.jpg, which
capture_wrist_view prefers over opening the camera itself (a second
VideoCapture(0) would conflict with this process).

Usage (from repo root):
    a1z/.venv/bin/python a1z/live_view.py
"""

import os
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template_string

A1Z_DIR = Path(__file__).parent
sys.path.insert(0, str(A1Z_DIR))

import vision_grasp as vg  # noqa: E402
from mcp_call import McpSession  # noqa: E402

PORT = 8080
SHARED_FRAME = "/tmp/wrist_live.jpg"  # consumed by capture_wrist_view
TABLE_Z = 0.02  # plane used for the overlay's 3D target readout
JPEG_QUALITY = 80

_state = {
    "frame": None,          # latest raw BGR frame
    "joints": "offline",    # last get_joint_state reply
    "tcp": "",              # TCP pose string from local FK on the joint angles
    "q_deg": None,          # parsed joint angles for FK overlay
    "updated": 0.0,
    "online": False,
}
_lock = threading.Lock()

PAGE = """
<!doctype html>
<html><head><title>A1Z wrist view</title><style>
body { background:#111; color:#ddd; font-family:monospace; margin:16px; }
h2 { font-size:14px; margin:4px 0; }
.row { display:flex; gap:16px; }
.panel img { width:640px; background:#000; border:1px solid #333; }
#status { margin-top:12px; padding:8px; background:#1c1c1c; border:1px solid #333;
          white-space:pre-wrap; font-size:13px; }
.off { color:#e66; } .on { color:#6d6; }
.hint { color:#888; font-size:12px; margin-top:8px; }
</style></head><body>
<div class="row">
  <div class="panel"><h2>raw</h2><img src="/stream/raw"></div>
  <div class="panel"><h2>enhanced (aim + annotation + target)</h2><img src="/stream/enhanced"></div>
</div>
<div id="status">connecting...</div>
<div class="hint">workflow: annotate the target base with a RED mark on a saved frame,
then call grasp_horizontal (the magenta circle previews what it will lock onto).
capture_wrist_view reuses this stream via {{shared}}.</div>
<script>
async function tick() {
  try {
    const s = await (await fetch('/status')).json();
    const el = document.getElementById('status');
    el.innerHTML = '<span class="' + (s.online ? 'on' : 'off') + '">' +
      (s.online ? 'MCP online' : 'MCP offline') + '</span>  ' +
      s.joints + '\\n' + s.tcp;
  } catch (e) {}
}
setInterval(tick, 1000); tick();
</script>
</body></html>
"""


def _camera_thread():
    """Grab frames forever; share the latest raw frame to SHARED_FRAME."""
    last_write = 0.0
    while True:
        cap = cv2.VideoCapture(vg.CAM_INDEX)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, vg.WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, vg.HEIGHT)
        if not cap.isOpened():
            time.sleep(2.0)
            continue
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            with _lock:
                _state["frame"] = frame
            now = time.time()
            if now - last_write > 0.3:
                tmp = SHARED_FRAME + ".tmp.jpg"
                if cv2.imwrite(tmp, frame):
                    os.replace(tmp, SHARED_FRAME)
                last_write = now
        cap.release()
        time.sleep(1.0)


def _status_thread():
    """Poll the MCP server for arm state at 1 Hz."""
    sess = None
    while True:
        try:
            if sess is None:
                sess = McpSession()
                sess.initialize()
            joints = sess.tool("get_joint_state", {})
            tcp = ""
            q_deg = None
            if joints.startswith("pos(deg)="):
                pos_str = joints.split("pos(deg)=")[1].split("]")[0].strip("[ ")
                q_deg = [float(v) for v in pos_str.split(",")]
                try:
                    tcp = _tcp_pose_str(q_deg)
                except Exception:
                    tcp = ""
            with _lock:
                _state.update(joints=joints, tcp=tcp, q_deg=q_deg,
                              updated=time.time(), online=True)
        except Exception:
            sess = None
            with _lock:
                _state.update(joints="offline", tcp="", q_deg=None, online=False)
        time.sleep(1.0)


_kin = None
_calib = None

TCP_OFFSET_M = np.array([0.10, 0.0, 0.0])  # fingertip midpoint in arm_link6


def _fk_flange(q_deg):
    """T_base_flange from joint angles (deg); lazy-loads kinematics."""
    global _kin
    if _kin is None:
        from a1z.robots.kinematics import Kinematics

        _kin = Kinematics(str(A1Z_DIR / "GALAXEA-A1Z/a1z/robot_models/a1z/A1Z_Flange.urdf"),
                          end_effector_frame="arm_link6")
    return _kin.fk(np.deg2rad(np.asarray(q_deg)))


def _tcp_pose_str(q_deg):
    """TCP pose (xyz + extrinsic XYZ rpy) from local FK, matching the
    format the removed get_flange_pose skill used to return."""
    T = _fk_flange(q_deg)
    R = T[:3, :3]
    p = T[:3, 3] + R @ TCP_OFFSET_M
    sy = max(-1.0, min(1.0, -R[2, 0]))
    pitch = np.arcsin(sy)
    roll = np.arctan2(R[2, 1], R[2, 2])
    yaw = np.arctan2(R[1, 0], R[0, 0])
    rpy = np.rad2deg([roll, pitch, yaw])
    return (f"tcp xyz(m)=[{p[0]:.4f}, {p[1]:.4f}, {p[2]:.4f}] "
            f"rpy(deg)=[{rpy[0]:.1f}, {rpy[1]:.1f}, {rpy[2]:.1f}]")


def _fk_base_cam(q_deg):
    """T_base_cam from joint angles (deg); lazy-loads calib."""
    global _calib
    if _calib is None:
        _calib = vg.load_calib()
    K, dist, X = _calib
    return _fk_flange(q_deg) @ X, K, dist


def _enhance(frame):
    out = frame.copy()
    K, dist, X = vg.load_calib()
    ax, ay = vg.aim_pixel(K, dist, X)
    h, w = out.shape[:2]
    for gx in range(0, w, 100):
        cv2.line(out, (gx, 0), (gx, h), (0, 120, 0), 1)
    for gy in range(0, h, 100):
        cv2.line(out, (0, gy), (w, gy), (0, 120, 0), 1)
    cv2.drawMarker(out, (int(ax), int(ay)), (255, 255, 0), cv2.MARKER_CROSS, 40, 3)
    cv2.putText(out, "aim", (int(ax) + 24, int(ay) - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

    found = vg.find_annotation_pixel(frame)
    if found is not None:
        u, v = found
        c = (int(u), int(v))
        cv2.circle(out, c, 25, (255, 0, 255), 3)
        cv2.drawMarker(out, c, (255, 0, 255), cv2.MARKER_CROSS, 30, 2)
        cv2.putText(out, f"target px ({u:.0f},{v:.0f})", (c[0] + 30, c[1]),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 255), 2)
        with _lock:
            q_deg = _state["q_deg"]
        if q_deg is not None:
            try:
                T_base_cam, K, dist = _fk_base_cam(q_deg)
                p = vg.pixel_to_base(u, v, TABLE_Z, T_base_cam, K, dist)
                if p is not None:
                    cv2.putText(out, f"base ({p[0]:.3f},{p[1]:.3f},{p[2]:.3f})",
                                (c[0] + 30, c[1] + 28),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            except Exception:
                pass
    return out


def _mjpeg(enhanced: bool):
    def gen():
        while True:
            with _lock:
                frame = None if _state["frame"] is None else _state["frame"].copy()
            if frame is None:
                time.sleep(0.2)
                continue
            if enhanced:
                frame = _enhance(frame)
            ok, jpg = cv2.imencode(".jpg", frame,
                                   [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if ok:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + jpg.tobytes() + b"\r\n")
            time.sleep(1 / 20)
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


app = Flask(__name__)


@app.route("/")
def index():
    return render_template_string(PAGE, shared=SHARED_FRAME)


@app.route("/stream/raw")
def stream_raw():
    return _mjpeg(enhanced=False)


@app.route("/stream/enhanced")
def stream_enhanced():
    return _mjpeg(enhanced=True)


@app.route("/status")
def status():
    with _lock:
        return jsonify(joints=_state["joints"], tcp=_state["tcp"],
                       online=_state["online"], updated=_state["updated"])


if __name__ == "__main__":
    threading.Thread(target=_camera_thread, daemon=True).start()
    threading.Thread(target=_status_thread, daemon=True).start()
    app.run(host="127.0.0.1", port=PORT, threaded=True)

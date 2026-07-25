#!/usr/bin/env python3
"""DualSense gyro web simulator — no robot arm involved.

Reads the controller on this host (hidraw), applies the SAME mapping pipeline
as gamepad_bridge.py (bias, deadband, gain, measured-dt integration) to a
VIRTUAL TCP pose, and serves a page that renders it as a 3D cube + position
readouts. Use this to judge gyro quality (noise, drift, response) and tune
the mapping before touching the real arm.

Serves on 0.0.0.0:9994 (env A1Z_GYRO_SIM_PORT):
  GET  /               page
  GET  /api/state      {gyro_dps, accel_g, virt: {x,y,z,roll,pitch,yaw}, drift_deg, buttons}
  POST /api/calibrate  re-capture gyro bias (hold controller still ~1s)
  POST /api/reset      zero the virtual pose
  POST /api/params     {"gain": f, "deadband": f, "trans": f} live tuning

Run on the Orange Pi:  python3 gyro_sim.py     then open http://<pi-ip>:9994/
Stdlib only; hidraw parsing shared with gamepad_bridge.py.
"""

import json
import math
import os
import select
import threading
import time
import urllib.request  # noqa: F401  (kept for parity; not used)
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gamepad_bridge import (
    ACCEL_G_PER_LSB, GYRO_DPS_PER_LSB, parse_report,
)

HIDRAW = os.environ.get("A1Z_HIDRAW", "/dev/hidraw0")
PORT = int(os.environ.get("A1Z_GYRO_SIM_PORT", "9994"))

PAGE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DualSense 陀螺仪虚拟遥操模拟</title>
<style>
 body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0;padding:16px}
 h1{font-size:18px} h2{font-size:13px;color:#9ad;margin:10px 0 4px}
 canvas{background:#000;border:1px solid #333;border-radius:8px}
 .row{display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start}
 .num{font-family:monospace;font-size:14px;background:#000;padding:8px 12px;
      border-radius:8px;white-space:pre}
 button{font-size:14px;padding:8px 14px;border-radius:8px;border:1px solid #555;
        background:#333;color:#eee;margin-right:8px}
 button:active{background:#4af}
 label{font-size:13px;color:#aaa;display:block;margin-top:8px}
 input[type=range]{width:180px;vertical-align:middle}
 .bar{height:8px;background:#333;border-radius:4px;overflow:hidden;width:200px;
      display:inline-block;vertical-align:middle}
 .bar>i{display:block;height:100%;background:#4af}
</style>
</head>
<body>
<h1>陀螺仪 → 虚拟 TCP 模拟（不动真臂）</h1>
<div>
  <button onclick="post('/api/calibrate')">重新校准零偏</button>
  <button onclick="post('/api/reset')">复位虚拟点</button>
  <span id="msg" style="color:#8f8;font-size:13px"></span>
</div>
<div>
  <label>姿态增益 GAIN <span id="vg">1.0</span>
    <input type="range" min="0.5" max="3" step="0.1" value="1.0" oninput="setP('gain',this.value)"></label>
  <label>死区 dps <span id="vd">3.0</span>
    <input type="range" min="0" max="10" step="0.5" value="3" oninput="setP('deadband',this.value)"></label>
  <label>平移速度 m/s <span id="vt">0.10</span>
    <input type="range" min="0.02" max="0.3" step="0.01" value="0.10" oninput="setP('trans',this.value)"></label>
</div>
<div class="row" style="margin-top:10px">
  <div><h2>虚拟 TCP 姿态（手柄陀螺仪驱动）</h2><canvas id="cv" width="360" height="360"></canvas></div>
  <div>
    <h2>原始数据</h2><div class="num" id="raw">…</div>
    <h2>虚拟点</h2><div class="num" id="virt">…</div>
  </div>
</div>
<script>
function post(u, body){
  return fetch(u,{method:'POST',body:body?JSON.stringify(body):''})
    .then(r=>r.json()).then(d=>{msg(d.status||JSON.stringify(d));}).catch(e=>msg('ERR '+e));
}
function setP(k,v){
  document.getElementById(k==='gain'?'vg':k==='deadband'?'vd':'vt').textContent=v;
  clearTimeout(setP._t);
  setP._t=setTimeout(()=>post('/api/params',{[k]:parseFloat(v)}),200);
}
function msg(s){const m=document.getElementById('msg');m.textContent=s;
  clearTimeout(msg._t);msg._t=setTimeout(()=>m.textContent='',3000);}

// --- cube render (wireframe, extrinsic XYZ rpy, degrees) ---
const V=[[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]];
const E=[[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]];
function rot(p,r,pi,y){ // r=roll(x) p=pitch(y) y=yaw(z), rad
  let [x0,y0,z0]=p;
  let c=Math.cos(r),s=Math.sin(r); let y1=y0*c-z0*s, z1=y0*s+z0*c, x1=x0;
  c=Math.cos(pi);s=Math.sin(pi); let x2=x1*c+z1*s, z2=-x1*s+z1*c, y2=y1;
  c=Math.cos(y);s=Math.sin(y); let x3=x2*c-y2*s, y3=x2*s+y2*c, z3=z2;
  return [x3,y3,z3];
}
function draw(st){
  const cv=document.getElementById('cv'), ctx=cv.getContext('2d');
  ctx.clearRect(0,0,360,360);
  const d2r=Math.PI/180, cx=180, cy=180, S=70;
  const pts=V.map(p=>{const q=rot(p,st.roll*d2r,st.pitch*d2r,st.yaw*d2r);
    const persp=3.2/(3.2+q[2]); return [cx+q[0]*S*persp, cy-q[1]*S*persp];});
  ctx.strokeStyle='#4af'; ctx.lineWidth=2; ctx.beginPath();
  for(const [a,b] of E){ctx.moveTo(pts[a][0],pts[a][1]);ctx.lineTo(pts[b][0],pts[b][1]);}
  ctx.stroke();
  // x 轴方向标红（TCP 指向）
  const tip=rot([1.6,0,0],st.roll*d2r,st.pitch*d2r,st.yaw*d2r);
  const tp=3.2/(3.2+tip[2]);
  ctx.strokeStyle='#f44'; ctx.beginPath(); ctx.moveTo(cx,cy);
  ctx.lineTo(cx+tip[0]*S*tp, cy-tip[1]*S*tp); ctx.stroke();
  // 位置十字（俯视 xy）
  ctx.fillStyle='#8f8';
  ctx.fillRect(cx+st.x*200-3, cy-st.y*200-3, 6, 6);
  // z 竖条（右侧，中线为 0，±0.5m 满量程）
  ctx.strokeStyle='#555'; ctx.beginPath();
  ctx.moveTo(340,20); ctx.lineTo(340,340); ctx.stroke();
  ctx.fillStyle='#4a4'; ctx.fillRect(336,178,8,4);
  const zh=Math.max(-160,Math.min(160,st.z*320));
  ctx.fillStyle='#ff4';
  if(zh>=0) ctx.fillRect(336,180-zh,8,zh); else ctx.fillRect(336,180,8,-zh);
  ctx.fillStyle='#aaa'; ctx.font='11px monospace';
  ctx.fillText('z '+st.z.toFixed(2)+'m',300,355);
}
let last=0;
function poll(){
  fetch('/api/state').then(r=>r.json()).then(d=>{
    const g=d.gyro_dps, a=d.accel_g, v=d.virt;
    document.getElementById('raw').textContent =
      `gyro dps   p ${g[0].toFixed(1).padStart(7)}  y ${g[1].toFixed(1).padStart(7)}  r ${g[2].toFixed(1).padStart(7)}\n`+
      `accel g    x ${a[0].toFixed(2).padStart(6)}  y ${a[1].toFixed(2).padStart(6)}  z ${a[2].toFixed(2).padStart(6)}\n`+
      `漂移(静止累计) ${d.drift_deg.toFixed(1)}°   按钮 ${d.buttons}`;
    document.getElementById('virt').textContent =
      `rpy°  r ${v.roll.toFixed(1).padStart(7)}  p ${v.pitch.toFixed(1).padStart(7)}  y ${v.yaw.toFixed(1).padStart(7)}\n`+
      `xyz m x ${v.x.toFixed(3).padStart(7)}  y ${v.y.toFixed(3).padStart(7)}  z ${v.z.toFixed(3).padStart(7)}`;
    draw(v);
  }).catch(()=>{});
}
setInterval(poll, 33); poll();
</script>
</body>
</html>
"""


class _State:
    """Shared virtual-pose state; written by the reader thread."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.bias = (0.0, 0.0, 0.0)
        self.gain = 1.0           # absolute attitude: 1:1 by default
        self.deadband = 3.0
        self.trans = 0.10
        self.virt = {"x": 0.0, "y": 0.0, "z": 0.0,
                     "roll": 0.0, "pitch": 0.0, "yaw": 0.0}
        # absolute attitude relative to anchor (complementary filter)
        self.att = [0.0, 0.0, 0.0]     # roll, pitch, yaw (deg, rel to anchor)
        self.tilt0 = (0.0, 0.0)        # accel tilt at anchor
        self.gyro_dps = (0.0, 0.0, 0.0)
        self.accel_g = (0.0, 0.0, 0.0)
        self.buttons = "-"
        self.drift_deg = 0.0  # |integrated angle| since calib, still-controller check
        self.calib_event = threading.Event()
        self.reset_event = threading.Event()


STATE = _State()
ATT_ALPHA = 0.98  # gyro/accel complementary filter weight


def _tilt(a) -> tuple[float, float]:
    """Accel tilt (roll, pitch) in deg of the controller frame."""
    ax, ay, az = a
    return (math.degrees(math.atan2(ay, az)),
            math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az))))


def _db(v: float, band: float) -> float:
    return 0.0 if abs(v) < band else v


def reader() -> None:
    """hidraw reader + virtual integrator (same formulas as gamepad_bridge)."""
    fd = None
    while fd is None:
        try:
            fd = os.open(HIDRAW, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            time.sleep(1.0)
    last_t = time.time()
    calib_acc, calib_n, calib_t0 = [0.0, 0.0, 0.0], 0, None

    while True:
        if STATE.calib_event.is_set():
            STATE.calib_event.clear()
            calib_acc, calib_n, calib_t0 = [0.0, 0.0, 0.0], 0, time.time()
        if STATE.reset_event.is_set():
            STATE.reset_event.clear()
            with STATE.lock:
                STATE.virt["x"] = STATE.virt["y"] = STATE.virt["z"] = 0.0
                STATE.att = [0.0, 0.0, 0.0]
                STATE.tilt0 = _tilt(STATE.accel_g)  # re-anchor HERE
                STATE.drift_deg = 0.0

        r, _, _ = select.select([fd], [], [], 0.02)
        if not r:
            continue
        try:
            buf = os.read(fd, 64)
        except OSError:
            os.close(fd)
            fd = None
            while fd is None:
                try:
                    fd = os.open(HIDRAW, os.O_RDONLY | os.O_NONBLOCK)
                except OSError:
                    time.sleep(1.0)
            continue
        rep = parse_report(buf)
        if rep is None:
            continue

        now = time.time()
        dt = min(max(now - last_t, 0.001), 0.05)
        last_t = now

        # calibration window: 1 s of still samples -> new bias
        if calib_t0 is not None:
            for i in range(3):
                calib_acc[i] += rep["gyro_dps"][i]
            calib_n += 1
            if now - calib_t0 >= 1.0:
                with STATE.lock:
                    STATE.bias = tuple(v / max(calib_n, 1) for v in calib_acc)
                    STATE.tilt0 = _tilt(rep["accel_g"])  # anchor attitude too
                    STATE.att = [0.0, 0.0, 0.0]
                    STATE.drift_deg = 0.0
                calib_t0 = None
            continue

        with STATE.lock:
            bias, gain, band, trans = (STATE.bias, STATE.gain,
                                       STATE.deadband, STATE.trans)
            v = STATE.virt
            gp = _db(rep["gyro_dps"][0] - bias[0], band) * gain
            gy = _db(rep["gyro_dps"][1] - bias[1], band) * gain
            gr = _db(rep["gyro_dps"][2] - bias[2], band) * gain
            # --- absolute attitude relative to anchor (complementary filter) ---
            STATE.att[0] += gr * dt
            STATE.att[1] += gp * dt
            STATE.att[2] += gy * dt
            tr, tp = _tilt(rep["accel_g"])
            STATE.att[0] = ATT_ALPHA * STATE.att[0] + (1 - ATT_ALPHA) * (tr - STATE.tilt0[0])
            STATE.att[1] = ATT_ALPHA * STATE.att[1] + (1 - ATT_ALPHA) * (tp - STATE.tilt0[1])
            v["roll"], v["pitch"], v["yaw"] = STATE.att
            # dpad -> xy (held = full speed): up=+x fwd, left=+y left
            dpad = rep["b0"] & 0x0F
            fwd = 1.0 if dpad in (0, 1, 7) else -1.0 if dpad in (3, 4, 5) else 0.0
            left = 1.0 if dpad in (5, 6, 7) else -1.0 if dpad in (1, 2, 3) else 0.0
            # z: □ square(0x10) -> down, △ triangle(0x80) -> up
            zdown = 1.0 if (rep["b0"] & 0x10) else 0.0
            zup = 1.0 if (rep["b0"] & 0x80) else 0.0
            v["x"] += fwd * trans * dt
            v["y"] += left * trans * dt
            v["z"] += (zup - zdown) * trans * dt
            STATE.gyro_dps = rep["gyro_dps"]
            STATE.accel_g = rep["accel_g"]
            STATE.buttons = f"{rep['b0']:#04x}/{rep['b1']:#04x}/{rep['b2']:#04x}"
            STATE.drift_deg += math.sqrt(
                sum((rep["gyro_dps"][i] - bias[i]) ** 2 for i in range(3))) * dt


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("", "/index.html"):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/state":
            with STATE.lock:
                self._json({
                    "gyro_dps": [round(v, 2) for v in STATE.gyro_dps],
                    "accel_g": [round(v, 3) for v in STATE.accel_g],
                    "virt": {k: round(v, 3) for k, v in STATE.virt.items()},
                    "drift_deg": round(STATE.drift_deg, 2),
                    "buttons": STATE.buttons,
                })
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        path = self.path.rstrip("/")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if path == "/api/calibrate":
            STATE.calib_event.set()
            self._json({"status": "calibrating 1s — hold still"})
        elif path == "/api/reset":
            STATE.reset_event.set()
            self._json({"status": "virtual pose reset"})
        elif path == "/api/params":
            try:
                p = json.loads(raw)
            except Exception:
                self._json({"error": "bad json"}, 400)
                return
            with STATE.lock:
                if "gain" in p:
                    STATE.gain = float(p["gain"])
                if "deadband" in p:
                    STATE.deadband = float(p["deadband"])
                if "trans" in p:
                    STATE.trans = float(p["trans"])
            self._json({"status": "ok"})
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    STATE.calib_event.set()  # bias capture on startup
    threading.Thread(target=reader, daemon=True).start()
    print(f"[gyro-sim] on http://0.0.0.0:{PORT}/  (hidraw={HIDRAW})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

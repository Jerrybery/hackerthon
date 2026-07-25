#!/usr/bin/env python3
"""Web-based teleop simulator for the A1Z virtual-reference-point teleop.

Lets you drive the arm's gamepad_teleop path from a browser (mouse/touch),
without the DualSense controller — for verifying directions, amplitude and
smoothness of the virtual reference point before involving real hardware.

Serves on 0.0.0.0:9992 (env A1Z_SIM_PORT to override):
  GET  /            single-page UI
  POST /api/teleop  -> MCP gamepad_teleop (deltas, same contract as the bridge)
  GET  /api/pose    -> MCP get_tcp_pose
  GET  /api/mode    -> current control mode
  POST /api/mode    -> {"mode": "ai"|"gamepad"} or empty body = toggle

Stdlib only. Run on the Orange Pi:  python3 teleop_sim.py
Then open http://<pi-ip>:9992/ in any browser.
"""

import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gamepad_bridge import McpClient  # same directory

PORT = int(os.environ.get("A1Z_SIM_PORT", "9992"))
MODE_URL = os.environ.get("A1Z_MODE_URL", "http://127.0.0.1:9991/mode")
SEND_HZ = 20.0  # must match the JS send interval for sane amplitude

PAGE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>A1Z 虚拟点遥操作模拟器</title>
<style>
  body { font-family: system-ui, sans-serif; background:#111; color:#eee;
         margin:0; padding:16px; max-width:900px; margin:auto; }
  h1 { font-size:18px; } h2 { font-size:14px; color:#9ad; margin:12px 0 6px; }
  .row { display:flex; gap:16px; flex-wrap:wrap; }
  .pad { width:220px; height:220px; border-radius:12px; background:#222;
         border:1px solid #444; position:relative; touch-action:none; }
  .knob { width:56px; height:56px; border-radius:50%; background:#4af;
          position:absolute; left:82px; top:82px; pointer-events:none; }
  .lbl { text-align:center; color:#888; font-size:12px; margin-top:4px; }
  button { font-size:16px; padding:10px 18px; border-radius:8px; border:1px solid #555;
           background:#333; color:#eee; }
  button:active { background:#4af; }
  .col { display:flex; flex-direction:column; gap:8px; align-items:center; }
  #pose { font-family:monospace; background:#000; padding:8px 12px; border-radius:8px;
          white-space:pre-wrap; font-size:13px; }
  #mode { font-weight:bold; }
  #log { font-family:monospace; font-size:12px; color:#8f8; height:120px;
         overflow-y:auto; background:#000; padding:8px; border-radius:8px; }
</style>
</head>
<body>
<h1>A1Z 虚拟参考点遥操作 · 网页模拟器</h1>
<div>模式: <span id="mode">?</span>
  <button onclick="toggleMode()">切换 AI/手柄</button>
  <span style="color:#888;font-size:12px">（teleop 仅在 gamepad 模式生效）</span>
</div>

<div class="row" style="margin-top:16px">
  <div>
    <h2>平移 XY（基座系）</h2>
    <div class="pad" id="padXY"><div class="knob" id="knobXY"></div></div>
    <div class="lbl">上=+x 前 &nbsp; 左=+y 左</div>
  </div>
  <div>
    <h2>旋转 yaw / pitch</h2>
    <div class="pad" id="padRot"><div class="knob" id="knobRot"></div></div>
    <div class="lbl">左右=yaw &nbsp; 上下=pitch</div>
  </div>
  <div class="col">
    <h2>Z / Roll / 夹爪</h2>
    <button onpointerdown="hold('dz',1)" onpointerup="hold('dz',0)" onpointerleave="hold('dz',0)">Z 升 +</button>
    <button onpointerdown="hold('dz',-1)" onpointerup="hold('dz',0)" onpointerleave="hold('dz',0)">Z 降 -</button>
    <button onpointerdown="hold('droll',1)" onpointerup="hold('droll',0)" onpointerleave="hold('droll',0)">Roll +</button>
    <button onpointerdown="hold('droll',-1)" onpointerup="hold('droll',0)" onpointerleave="hold('droll',0)">Roll -</button>
    <button onclick="grip(1.0)">夹爪 开</button>
    <button onclick="grip(0.0)">夹爪 闭</button>
  </div>
</div>

<h2>TCP 位姿（0.5s 刷新）</h2>
<div id="pose">…</div>
<h2>日志</h2>
<div id="log"></div>

<script>
const TICK_MS = 100;                // 10 Hz — 与服务端 teleop 限频 (80ms) 对齐
const TRANS_MPS = 0.10, ROT_DPS = 60;
const st = {xy:[0,0], rot:[0,0], dz:0, droll:0};

function logLine(s, ok=true){
  const el = document.getElementById('log');
  el.innerHTML += `<div style="color:${ok?'#8f8':'#f88'}">${s}</div>`;
  el.scrollTop = el.scrollHeight;
}

function bindPad(padId, knobId, key){
  const pad = document.getElementById(padId), knob = document.getElementById(knobId);
  let dragging = false;
  function setFromEvent(e){
    const r = pad.getBoundingClientRect();
    let x = (e.clientX - r.left - r.width/2) / (r.width/2 - 28);
    let y = (e.clientY - r.top - r.height/2) / (r.height/2 - 28);
    x = Math.max(-1, Math.min(1, x)); y = Math.max(-1, Math.min(1, y));
    st[key] = [x, y];
    knob.style.left = (82 + x*72) + 'px';
    knob.style.top  = (82 + y*72) + 'px';
  }
  function reset(){ st[key] = [0,0]; knob.style.left='82px'; knob.style.top='82px'; }
  pad.addEventListener('pointerdown', e => { dragging = true; pad.setPointerCapture(e.pointerId); setFromEvent(e); });
  pad.addEventListener('pointermove', e => { if (dragging) setFromEvent(e); });
  pad.addEventListener('pointerup', () => { dragging = false; reset(); });
  pad.addEventListener('pointercancel', () => { dragging = false; reset(); });
}
bindPad('padXY','knobXY','xy');
bindPad('padRot','knobRot','rot');

function hold(k, v){ st[k] = v; }
function grip(v){
  fetch('/api/teleop', {method:'POST', body: JSON.stringify({gripper: v})})
    .then(r=>r.json()).then(d=>logLine('gripper -> '+v+': '+d.result));
}

setInterval(() => {
  const dt = TICK_MS/1000;
  const payload = {
    dx:  -st.xy[1] * TRANS_MPS * dt,   // pad up = +x
    dy:  -st.xy[0] * TRANS_MPS * dt,   // pad left = +y  (屏幕右为正x,取反让左=+y)
    dz:   st.dz    * TRANS_MPS * dt,
    droll_deg:  st.droll * ROT_DPS * dt,
    dpitch_deg: -st.rot[1] * ROT_DPS * dt,
    dyaw_deg:   -st.rot[0] * ROT_DPS * dt,
  };
  const active = Object.values(payload).some(v => Math.abs(v) > 1e-9);
  if (!active) return;
  for (const k in payload) payload[k] = +payload[k].toFixed(4);
  fetch('/api/teleop', {method:'POST', body: JSON.stringify(payload)})
    .then(r=>r.json()).then(d=>{
      if (!d.result.startsWith('teleop') && !d.result.startsWith('held'))
        logLine(JSON.stringify(payload)+' -> '+d.result, false);
    }).catch(e=>logLine('net error: '+e, false));
}, TICK_MS);

function pollPose(){
  fetch('/api/pose').then(r=>r.json())
    .then(d=>{ document.getElementById('pose').textContent = d.result; })
    .catch(()=>{});
}
function pollMode(){
  fetch('/api/mode').then(r=>r.json())
    .then(d=>{
      const el = document.getElementById('mode');
      el.textContent = d.mode;
      el.style.color = d.mode === 'gamepad' ? '#4f4' : '#fa4';
    }).catch(()=>{});
}
function toggleMode(){
  fetch('/api/mode', {method:'POST', body:''})
    .then(r=>r.json()).then(d=>{ pollMode(); logLine('mode -> '+d.mode); });
}
setInterval(pollPose, 500); pollPose();
setInterval(pollMode, 2000); pollMode();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    mcp = None  # McpClient, lazily created

    @classmethod
    def client(cls) -> McpClient:
        if cls.mcp is None:
            cls.mcp = McpClient(os.environ.get(
                "A1Z_MCP_URL", "http://127.0.0.1:9990/mcp"))
            cls.mcp.initialize()
        return cls.mcp

    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _mcp_tool(self, name: str, args: dict) -> str:
        try:
            return type(self).client().tool(name, args)
        except Exception as e:
            type(self).mcp = None  # force re-init next call
            return f"ERROR: MCP unreachable: {e}"

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("", "/index.html"):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/pose":
            self._json({"result": self._mcp_tool("get_tcp_pose", {})})
        elif path == "/api/mode":
            try:
                with urllib.request.urlopen(MODE_URL, timeout=3.0) as resp:
                    self._json(json.loads(resp.read().decode()))
            except Exception as e:
                self._json({"error": str(e)}, 502)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        path = self.path.rstrip("/")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if path == "/api/teleop":
            try:
                args = json.loads(raw) if raw else {}
            except Exception:
                self._json({"error": "bad json"}, 400)
                return
            allowed = {"dx", "dy", "dz", "droll_deg", "dpitch_deg",
                       "dyaw_deg", "gripper"}
            args = {k: v for k, v in args.items() if k in allowed}
            self._json({"result": self._mcp_tool("gamepad_teleop", args)})
        elif path == "/api/mode":
            req = urllib.request.Request(MODE_URL, data=raw or b"")
            try:
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    self._json(json.loads(resp.read().decode()))
            except Exception as e:
                self._json({"error": str(e)}, 502)
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    print(f"[sim] teleop simulator on http://0.0.0.0:{PORT}/ "
          f"(MCP via {os.environ.get('A1Z_MCP_URL', 'http://127.0.0.1:9990/mcp')})",
          flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

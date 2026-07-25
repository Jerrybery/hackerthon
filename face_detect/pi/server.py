#!/usr/bin/env python3
"""YOLOv5n-face RKNN demo server: camera -> NPU -> MJPEG web stream.

Usage: python3 server.py [model.rknn] [port]
Open http://<pi-ip>:8080 in a browser.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
from rknnlite.api import RKNNLite

MODEL = 'yolov5n_face_rk3566_i8_raw.rknn'
PORT = 8080
SIZE = 640
CONF_TH = 0.4
NMS_TH = 0.45
CAM = '/dev/video0'
CAP_W, CAP_H = 1280, 720
# A face counts as "at frame center" when its center-x is within this
# fraction of the frame width around the middle (0.25 -> central half).
CENTER_BAND = 0.25

STRIDES = [8, 16, 32]
ANCHORS = [
    [4, 5, 8, 10, 13, 16],
    [23, 29, 43, 55, 73, 105],
    [146, 217, 231, 300, 335, 433],
]

PAGE = """<!doctype html><html><head><meta charset=utf-8>
<title>YOLOv5n-face @ RK3566</title>
<style>
 body{background:#111;color:#eee;font-family:monospace;text-align:center}
 img{max-width:96vw;border:1px solid #444}
 #s{margin:8px;font-size:14px;color:#7f7}
</style></head><body>
<h3>YOLOv5n-face INT8 &middot; Orange Pi 3B (RK3566 NPU)</h3>
<div id=s>loading...</div>
<img src="/stream.mjpeg">
<script>
setInterval(async()=>{
  try{const s=await(await fetch('/stats')).json();
  document.getElementById('s').textContent=
   `inference ${s.infer_ms} ms · ${s.fps} FPS · faces ${s.faces}`;
  }catch(e){}
},1000);
</script></body></html>"""


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def decode(outs):
    all_boxes, all_conf = [], []
    for out, st, anch in zip(outs, STRIDES, ANCHORS):
        out = out[0]
        if out.shape[0] != 48:
            out = out.transpose(2, 0, 1)
        _, gh, gw = out.shape
        out = out.reshape(3, 16, gh, gw)
        gy, gx = np.meshgrid(np.arange(gh), np.arange(gw), indexing='ij')
        bx = (sigmoid(out[:, 0]) * 2 - 0.5 + gx) * st
        by = (sigmoid(out[:, 1]) * 2 - 0.5 + gy) * st
        aw = np.array(anch[0::2])[:, None, None]
        ah = np.array(anch[1::2])[:, None, None]
        bw = (sigmoid(out[:, 2]) * 2) ** 2 * aw
        bh = (sigmoid(out[:, 3]) * 2) ** 2 * ah
        conf = sigmoid(out[:, 4]) * sigmoid(out[:, 15])
        all_boxes.append(np.stack([bx, by, bw, bh], axis=-1).reshape(-1, 4))
        all_conf.append(conf.reshape(-1))
    return np.concatenate(all_boxes), np.concatenate(all_conf)


class Detector:
    """Owns camera capture + RKNN inference; produces annotated JPEG frames."""

    def __init__(self, model):
        self.lite = RKNNLite()
        assert self.lite.load_rknn(model) == 0
        assert self.lite.init_runtime() == 0
        self.cap = cv2.VideoCapture(CAM, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAP_W)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAP_H)
        assert self.cap.isOpened(), f'cannot open {CAM}'
        self.lock = threading.Lock()
        self.frame = None          # latest raw frame
        self.jpg = None            # latest annotated jpeg
        self.stats = {'infer_ms': 0, 'fps': 0, 'faces': 0}
        self.face_info = {'ts': 0, 'width': CAP_W, 'height': CAP_H, 'faces': []}
        self.stop = False

    def grab_loop(self):
        while not self.stop:
            ok, f = self.cap.read()
            if ok:
                with self.lock:
                    self.frame = f

    def infer_loop(self):
        fps_ema = 0.0
        while not self.stop:
            with self.lock:
                f = None if self.frame is None else self.frame.copy()
            if f is None:
                time.sleep(0.05)
                continue
            h0, w0 = f.shape[:2]
            r = min(SIZE / h0, SIZE / w0)
            nw, nh = int(round(w0 * r)), int(round(h0 * r))
            dw, dh = (SIZE - nw) // 2, (SIZE - nh) // 2
            canvas = np.full((SIZE, SIZE, 3), 114, np.uint8)
            canvas[dh:dh + nh, dw:dw + nw] = cv2.resize(f, (nw, nh))
            x = canvas[:, :, ::-1][None]

            t0 = time.perf_counter()
            outs = self.lite.inference(inputs=[x])
            infer_ms = (time.perf_counter() - t0) * 1000

            boxes, conf = decode(outs)
            m = conf > CONF_TH
            tlbr = [[b[0] - b[2] / 2, b[1] - b[3] / 2, b[2], b[3]] for b in boxes[m]]
            idx = cv2.dnn.NMSBoxes(tlbr, conf[m].tolist(), CONF_TH, NMS_TH)
            dets = np.array(idx).ravel() if len(idx) else []
            faces = []
            for i in dets:
                x0, y0, w, h = tlbr[i]
                p0 = (int((x0 - dw) / r), int((y0 - dh) / r))
                p1 = (int((x0 + w - dw) / r), int((y0 + h - dh) / r))
                cx = (p0[0] + p1[0]) / 2
                faces.append({'x0': p0[0], 'y0': p0[1], 'x1': p1[0], 'y1': p1[1],
                              'conf': round(float(conf[m][i]), 3),
                              'cx': round(cx, 1),
                              'centered': abs(cx - w0 / 2) <= w0 * CENTER_BAND})
                cv2.rectangle(f, p0, p1, (0, 255, 0), 2)
                cv2.putText(f, f'{conf[m][i]:.2f}', (p0[0], max(p0[1] - 4, 14)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            fps = 1000 / max(infer_ms, 1e-3)
            fps_ema = fps if fps_ema == 0 else fps_ema * 0.8 + fps * 0.2
            cv2.putText(f, f'{infer_ms:.0f}ms {fps_ema:.1f}FPS faces:{len(dets)}',
                        (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            ok, jpg = cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                with self.lock:
                    self.jpg = jpg.tobytes()
                    self.stats = {'infer_ms': round(infer_ms, 1),
                                  'fps': round(fps_ema, 1), 'faces': len(dets)}
                    self.face_info = {'ts': time.time(), 'width': w0, 'height': h0,
                                      'faces': faces}


class Handler(BaseHTTPRequestHandler):
    det: Detector = None

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == '/':
            body = PAGE.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/stats':
            body = json.dumps(self.det.stats).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/faces':
            with self.det.lock:
                body = json.dumps(self.det.face_info).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/stream.mjpeg':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=jpg')
            self.end_headers()
            try:
                while True:
                    with self.det.lock:
                        jpg = self.det.jpg
                    if jpg is None:
                        time.sleep(0.05)
                        continue
                    self.wfile.write(b'--jpg\r\nContent-Type: image/jpeg\r\n\r\n' + jpg + b'\r\n')
                    time.sleep(0.03)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_error(404)


if __name__ == '__main__':
    import sys
    model = sys.argv[1] if len(sys.argv) > 1 else MODEL
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT
    det = Detector(model)
    Handler.det = det
    threading.Thread(target=det.grab_loop, daemon=True).start()
    threading.Thread(target=det.infer_loop, daemon=True).start()
    print(f'serving on http://0.0.0.0:{port}')
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()

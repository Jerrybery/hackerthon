#!/usr/bin/env python3
"""Run yolov5n-face RKNN (raw head outputs) on RK3566: decode + NMS + benchmark."""
import sys
import time

import cv2
import numpy as np
from rknnlite.api import RKNNLite

RKNN_MODEL = sys.argv[1] if len(sys.argv) > 1 else 'yolov5n_face_rk3566_i8.rknn'
IMG = sys.argv[2] if len(sys.argv) > 2 else 'face_test.jpg'
OUT = sys.argv[3] if len(sys.argv) > 3 else 'face_test_rknn.jpg'
SIZE = 640
CONF_TH = 0.4
NMS_TH = 0.45

STRIDES = [8, 16, 32]
ANCHORS = [
    [4, 5, 8, 10, 13, 16],
    [23, 29, 43, 55, 73, 105],
    [146, 217, 231, 300, 335, 433],
]


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def decode(outs):
    """outs: 3 tensors (1,48,H,W) or (1,H,W,48), raw logits. Returns boxes(N,4 xywh), conf(N)."""
    all_boxes, all_conf = [], []
    for out, st, anch in zip(outs, STRIDES, ANCHORS):
        out = out[0]
        if out.shape[0] != 48:          # NHWC -> NCHW
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
        conf = sigmoid(out[:, 4]) * sigmoid(out[:, 15])  # obj * cls (cls 在 ch15，5-14 是关键点)
        all_boxes.append(np.stack([bx, by, bw, bh], axis=-1).reshape(-1, 4))
        all_conf.append(conf.reshape(-1))
    return np.concatenate(all_boxes), np.concatenate(all_conf)


img = cv2.imread(IMG)
h0, w0 = img.shape[:2]
r = min(SIZE / h0, SIZE / w0)
nw, nh = int(round(w0 * r)), int(round(h0 * r))
dw, dh = (SIZE - nw) // 2, (SIZE - nh) // 2
canvas = np.full((SIZE, SIZE, 3), 114, np.uint8)
canvas[dh:dh + nh, dw:dw + nw] = cv2.resize(img, (nw, nh))
x = canvas[:, :, ::-1][None]  # RGB uint8 NHWC

lite = RKNNLite()
assert lite.load_rknn(RKNN_MODEL) == 0, 'load_rknn failed'
assert lite.init_runtime() == 0, 'init_runtime failed'

for _ in range(10):
    lite.inference(inputs=[x])
ts = []
for _ in range(50):
    t0 = time.perf_counter()
    outs = lite.inference(inputs=[x])
    ts.append((time.perf_counter() - t0) * 1000)
ts = np.array(ts)
print(f'inference: avg {ts.mean():.1f} ms  min {ts.min():.1f}  max {ts.max():.1f}  -> {1000/ts.mean():.1f} FPS')

boxes, conf = decode(outs)
m = conf > CONF_TH
tlbr = [[b[0] - b[2] / 2, b[1] - b[3] / 2, b[2], b[3]] for b in boxes[m]]
idx = cv2.dnn.NMSBoxes(tlbr, conf[m].tolist(), CONF_TH, NMS_TH)
print('detections:', len(idx))

vis = img.copy()
for i in np.array(idx).ravel():
    x0, y0, w, h = tlbr[i]
    p0 = (int((x0 - dw) / r), int((y0 - dh) / r))
    p1 = (int((x0 + w - dw) / r), int((y0 + h - dh) / r))
    cv2.rectangle(vis, p0, p1, (0, 255, 0), 2)
    cv2.putText(vis, f'{conf[m][i]:.2f}', (p0[0], p0[1] - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
cv2.imwrite(OUT, vis)
print('saved', OUT)
lite.release()

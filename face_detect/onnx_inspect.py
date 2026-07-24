#!/usr/bin/env python3
"""Inspect yolov5n_face.onnx output format + baseline detections (onnxruntime)."""
import cv2
import numpy as np
import onnxruntime as ort

IMG = 'face_detect/face_test.jpg'
ONNX = 'face_detect/yolov5n_face.onnx'
SIZE = 640

img = cv2.imread(IMG)
h0, w0 = img.shape[:2]
r = min(SIZE / h0, SIZE / w0)
nw, nh = int(round(w0 * r)), int(round(h0 * r))
resized = cv2.resize(img, (nw, nh))
canvas = np.full((SIZE, SIZE, 3), 114, np.uint8)
dw, dh = (SIZE - nw) // 2, (SIZE - nh) // 2
canvas[dh:dh + nh, dw:dw + nw] = resized
blob = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0

sess = ort.InferenceSession(ONNX, providers=['CPUExecutionProvider'])
out = sess.run(None, {sess.get_inputs()[0].name: blob})[0][0]  # (25200, 16)
print('shape:', out.shape)
print('x range:', out[:, 0].min(), out[:, 0].max())
print('obj range:', out[:, 4].min(), out[:, 4].max())
print('cls range:', out[:, 5].min(), out[:, 5].max())

# Heuristic: if obj values fall in [0,1], decode is baked in; else raw logits.
obj = out[:, 4]
baked = obj.min() >= 0 and obj.max() <= 1
print('decode baked in:', baked)
conf = obj * out[:, 5] if baked else 1 / (1 + np.exp(-obj)) * 1 / (1 + np.exp(-out[:, 5]))
mask = conf > 0.4
det = out[mask]
print('detections >0.4:', len(det))
for d in det[:10]:
    print(np.round(d[:6], 2))

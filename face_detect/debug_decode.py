#!/usr/bin/env python3
"""Compare decoded-graph ONNX output vs my raw decode on the same image."""
import cv2
import numpy as np
import onnxruntime as ort

SIZE = 640
img = cv2.imread('face_detect/face_test.jpg')
h0, w0 = img.shape[:2]
r = min(SIZE / h0, SIZE / w0)
nw, nh = int(round(w0 * r)), int(round(h0 * r))
dw, dh = (SIZE - nw) // 2, (SIZE - nh) // 2
canvas = np.full((SIZE, SIZE, 3), 114, np.uint8)
canvas[dh:dh + nh, dw:dw + nw] = cv2.resize(img, (nw, nh))
blob = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0


def sig(x):
    return 1 / (1 + np.exp(-x))


# Reference: decoded graph (known good)
ref = ort.InferenceSession('face_detect/yolov5n_face.onnx',
                           providers=['CPUExecutionProvider']).run(None, {'input': blob})[0][0]
ref_conf = ref[:, 4] * ref[:, 15]
top = np.argsort(ref_conf)[-3:][::-1]
print('ref top boxes (xywh, conf):')
for i in top:
    print('  ', np.round(ref[i, :4], 1), round(float(ref_conf[i]), 3))

# Raw outputs
raw = ort.InferenceSession('face_detect/yolov5n_face_raw.onnx',
                           providers=['CPUExecutionProvider']).run(None, {'input': blob})

# channel stats per scale
for s, out in enumerate(raw):
    o = out[0].reshape(3, 16, *out.shape[-2:])
    print(f'scale{s} shape{out.shape}: per-channel max sigmoid:',
          np.round(sig(o).max(axis=(0, 2, 3)), 2))
    print(f'          per-channel mean abs:', np.round(np.abs(o).mean(axis=(0, 2, 3)), 2))

# anchor order in ref: ref row index -> (scale, anchor, gy, gx)
# ref rows are ordered: for each scale, na*gh*gw rows. Check which raw (a,gy,gx)
# the ref top row corresponds to and compare channel values.
idx = top[0]
sizes = [3 * 80 * 80, 3 * 40 * 40, 3 * 20 * 20]
s = 0
while idx >= sizes[s]:
    idx -= sizes[s]
    s += 1
gh = [80, 40, 20][s]
a, rem = divmod(idx, gh * gh)
gy, gx = divmod(rem, gh)
o = raw[s][0].reshape(3, 16, gh, gh) if raw[s].shape[-1] == gh else None
print(f'ref top row maps to scale{s} anchor{a} gy{gy} gx{gx}')
print('ref row[:8]   :', np.round(ref[top[0], :8], 3))
print('raw (a,:)     :', np.round(o[a, :, gy, gx], 3))
print('sig raw (a,:) :', np.round(sig(o[a, :, gy, gx]), 3))

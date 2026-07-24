#!/usr/bin/env python3
"""Convert yolov5n_face.onnx -> RKNN for RK3566 (Orange Pi 3B).
Usage: convert_rknn.py [onnx] [out.rknn] [i8|fp16]
"""
import sys
from rknn.api import RKNN

ONNX = sys.argv[1] if len(sys.argv) > 1 else 'yolov5n_face.onnx'
MODE = sys.argv[3] if len(sys.argv) > 3 else 'i8'
OUT = sys.argv[2] if len(sys.argv) > 2 else f'yolov5n_face_rk3566_{MODE}.rknn'

rknn = RKNN(verbose=False)

# Feed uint8 RGB [0,255]; bake /255 normalization into the model.
rknn.config(
    target_platform='rk3566',
    mean_values=[[0, 0, 0]],
    std_values=[[255, 255, 255]],
    quantized_dtype='asymmetric_quantized-8',
)

HEAD_OUTPUTS = [
    '/model.21/m.0/Conv_output_0',  # P3/8  80x80
    '/model.21/m.1/Conv_output_0',  # P4/16 40x40
    '/model.21/m.2/Conv_output_0',  # P5/32 20x20
]
ret = rknn.load_onnx(model=ONNX, inputs=['input'], input_size_list=[[1, 3, 640, 640]],
                     outputs=HEAD_OUTPUTS)
if ret != 0:
    sys.exit('load_onnx failed')

if MODE == 'i8':
    ret = rknn.build(do_quantization=True, dataset='dataset.txt', rknn_batch_size=1)
else:
    ret = rknn.build(do_quantization=False, rknn_batch_size=1)
if ret != 0:
    sys.exit('build failed')

ret = rknn.export_rknn(OUT)
if ret != 0:
    sys.exit('export failed')

rknn.release()
print('OK ->', OUT)

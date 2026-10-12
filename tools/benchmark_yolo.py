"""Compare full-frame OCR against YOLO-crop-then-OCR on the labelled test images.

Needs models/yolov8n.onnx (see tools/export_yolo_onnx.py).
    python tools/benchmark_yolo.py
"""
import csv
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ocr_engine as O  # noqa: E402
from yolo_detector import YoloV8Detector  # noqa: E402

det = YoloV8Detector()
if det.net is None:
    sys.exit("models/yolov8n.onnx not found - run tools/export_yolo_onnx.py first")
gt = {r["filename"]: r["route"] for r in csv.DictReader(open("test_images/ground_truth.csv"))}
ok_base = ok_yolo = 0
for fn, exp in gt.items():
    f = cv2.imread(f"test_images/{fn}")
    t = time.time(); base = O.extract_route(f, raw_frame=f); tb = time.time() - t
    t = time.time(); crop, box, ys = det.detect_bus_placard(f)
    y = O.extract_route(crop, raw_frame=crop) if box is not None else base
    if box is not None and y.route is None:
        y = O.extract_route(f, raw_frame=f)
    ty = time.time() - t
    ok_base += (base.route or "") == exp
    ok_yolo += (y.route or "") == exp
    print(f"{fn[:30]:30} exp={exp or '-':5} full={base.route or '-':5}({tb:.2f}s) yolo={y.route or '-':5}({ty:.2f}s) bus_found={box is not None}")
print(f"full-frame {ok_base}/{len(gt)}   yolo-crop {ok_yolo}/{len(gt)}")

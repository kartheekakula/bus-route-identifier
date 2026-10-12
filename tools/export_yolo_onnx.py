"""Export YOLOv8n to models/yolov8n.onnx (one-off, needs `pip install ultralytics onnx` on a laptop).

    python tools/export_yolo_onnx.py
"""
from pathlib import Path
from ultralytics import YOLO

Path("models").mkdir(exist_ok=True)
out = YOLO("yolov8n.pt").export(format="onnx", imgsz=640, opset=12, simplify=False)
Path(out).replace("models/yolov8n.onnx")
print("wrote models/yolov8n.onnx")

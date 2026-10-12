"""
tools/benchmark.py
====================
Offline benchmark harness: feed it a folder of test photos of route
boards and it reports per-stage timings and OCR accuracy against a
ground-truth CSV, without needing a live button press or a bus.

Usage:
    python tools/benchmark.py --images test_images/ --ground-truth truth.csv

truth.csv format: filename,expected_route
    board_01.jpg,21C
    board_02.jpg,45
"""
import argparse
import csv
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from preprocessing import preprocess  # noqa: E402
from ocr_engine import extract_route  # noqa: E402


def load_ground_truth(path):
    truth = {}
    with open(path) as f:
        for row in csv.reader(f):
            if len(row) == 2:
                truth[row[0]] = row[1]
    return truth


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", required=True)
    parser.add_argument("--ground-truth", required=True)
    args = parser.parse_args()

    truth = load_ground_truth(args.ground_truth)
    image_dir = Path(args.images)

    correct, total = 0, 0
    total_time = 0.0

    for filename, expected in truth.items():
        img_path = image_dir / filename
        frame = cv2.imread(str(img_path))
        if frame is None:
            print(f"SKIP  {filename}: could not read image")
            continue

        t0 = time.monotonic()
        binary = preprocess(frame)
        result = extract_route(binary)
        elapsed = time.monotonic() - t0
        total_time += elapsed
        total += 1

        is_correct = result.route == expected
        correct += int(is_correct)
        status = "OK  " if is_correct else "MISS"
        print(f"{status}  {filename}: expected={expected} got={result.route} "
              f"conf={result.confidence:.1f} ({elapsed:.3f}s)")

    if total:
        print(f"\nAccuracy: {correct}/{total} ({100*correct/total:.1f}%)")
        print(f"Avg preprocess+OCR time: {total_time/total:.3f}s "
              f"(budget for these two stages combined: "
              f"{__import__('config').BUDGET_PREPROCESS + __import__('config').BUDGET_OCR:.3f}s)")


if __name__ == "__main__":
    main()

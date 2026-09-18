"""Measure route-recognition accuracy and latency against a ground-truth CSV.

Usage:
    python tools/benchmark_ocr.py
    python tools/benchmark_ocr.py --images test_images --ground-truth test_images/ground_truth.csv
"""
import argparse
import csv
import logging
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from ocr_engine import extract_route  # noqa: E402
from preprocessing import preprocess  # noqa: E402
from routes import RouteLookup  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", default="test_images")
    parser.add_argument("--ground-truth", default="test_images/ground_truth.csv")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--engine", help="Override config.OCR_ENGINE for this run")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    if args.engine:
        config.OCR_ENGINE = args.engine

    truth = {}
    with open(args.ground_truth, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            truth[row["filename"]] = (row["route"] or "").strip().upper()

    lookup = RouteLookup(config.ROUTES_DATA_DIR, config.CITY)

    correct = 0
    latencies = []
    rows = []

    for filename, expected in truth.items():
        path = Path(args.images) / filename
        frame = cv2.imread(str(path))
        if frame is None:
            print(f"  SKIP (unreadable): {filename}")
            continue

        t0 = time.monotonic()
        binary = preprocess(frame)
        result = extract_route(binary, raw_frame=frame)
        got = (result.route or "").upper()
        if got:
            got = lookup.correct_route(got)
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        latencies.append(elapsed_ms)

        ok = got == expected
        correct += ok
        rows.append((ok, filename, expected, got, result.confidence, elapsed_ms, result.raw_text))

    print(f"\n{'':2} {'FILE':<34} {'EXPECT':<8} {'GOT':<8} {'CONF':>6} {'MS':>8}")
    print("-" * 74)
    for ok, filename, expected, got, conf, ms, raw in rows:
        mark = "OK" if ok else "XX"
        print(f"{mark:2} {filename[:34]:<34} {expected or '-':<8} {got or '-':<8} {conf:6.1f} {ms:8.1f}")
        if args.verbose and not ok:
            print(f"   raw: {raw[:120]!r}")

    total = len(rows)
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0.0
    p95 = latencies[int(len(latencies) * 0.95) - 1] if latencies else 0.0
    over = sum(ms > config.BUDGET_TOTAL * 1000 for *_, ms, _ in rows)

    print("-" * 74)
    print(f"accuracy      : {correct}/{total} ({100.0 * correct / total:.1f}%)")
    print(f"latency p50   : {p50:.0f} ms")
    print(f"latency p95   : {p95:.0f} ms")
    print(f"over budget   : {over}/{total} (budget {config.BUDGET_TOTAL * 1000:.0f} ms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

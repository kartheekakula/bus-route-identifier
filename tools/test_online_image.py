"""
tools/test_online_image.py
==========================
Test the bus route identification pipeline on online or local images.

Usage:
    python tools/test_online_image.py --url https://example.com/bus.jpg
    python tools/test_online_image.py --file path/to/local/bus.jpg
"""
import argparse
import sys
import time
import urllib.request
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import cv2
import numpy as np

import config
from feedback import HapticMotor, announce_route, announce_low_confidence, announce_no_text
from ocr_engine import extract_route
from preprocessing import preprocess
from routes import RouteLookup


def download_image_from_url(url: str) -> np.ndarray:
    """Download an image from an HTTP/HTTPS URL into an in-memory NumPy array."""
    print(f"[*] Downloading image from URL: {url} ...")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "BusRouteIdentifier/1.0 (assistive-tech-research)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        image_bytes = resp.read()

    img_array = np.asarray(bytearray(image_bytes), dtype=np.uint8)
    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Could not decode downloaded image into a valid OpenCV frame.")
    return frame


def run_pipeline_on_frame(frame: np.ndarray, source_label: str):
    """Execute the full end-to-end pipeline on an input frame."""
    t_start = time.monotonic()
    h, w = frame.shape[:2]

    print("\n" + "=" * 70)
    print(f" PIPELINE EXECUTION: {source_label}")
    print("=" * 70)
    print(f"[*] Input frame resolution: {w}x{h} px")

    # 1. Preprocessing stage
    t0 = time.monotonic()
    binary = preprocess(frame)
    preprocess_s = time.monotonic() - t0
    print(f"[Stage 1 - Preprocess] Grayscale + CLAHE + Adaptive Threshold in {preprocess_s*1000:.1f}ms")

    # 2. OCR Extraction stage
    t0 = time.monotonic()
    ocr_result = extract_route(binary)
    ocr_s = time.monotonic() - t0
    print(f"[Stage 2 - OCR Engine] Engine='{ocr_result.engine}', Extracted text='{ocr_result.raw_text}'")
    print(f"                      Detected route='{ocr_result.route}', Confidence={ocr_result.confidence:.1f}%")
    print(f"                      OCR latency={ocr_s*1000:.1f}ms")

    # 3. Route Lookup & Fuzzy Correction
    t0 = time.monotonic()
    lookup = RouteLookup(routes_dir=config.ROUTES_DATA_DIR, city=config.CITY)
    original_route = ocr_result.route
    corrected_route = lookup.correct_route(original_route) if original_route else None
    destination = lookup.lookup(corrected_route) if corrected_route else None
    lookup_s = time.monotonic() - t0

    if original_route and corrected_route != original_route:
        print(f"[Stage 3 - Fuzzy Match] Corrected '{original_route}' -> '{corrected_route}'")
    else:
        print(f"[Stage 3 - Fuzzy Match] No correction needed (canonical route: '{corrected_route}')")

    if destination:
        print(f"[Stage 3 - Dest Lookup] City='{config.CITY}', Destination='{destination}'")
    else:
        print(f"[Stage 3 - Dest Lookup] City='{config.CITY}', No destination mapped (plain fallback)")
    print(f"                       Lookup latency={lookup_s*1000:.2f}ms")

    # 4. Feedback & Audio Announcement
    t0 = time.monotonic()
    haptic = HapticMotor()
    if corrected_route is None:
        announced_phrase = config.PHRASE_NO_TEXT
        announce_no_text(haptic)
    elif ocr_result.confidence < config.OCR_MIN_CONFIDENCE:
        announced_phrase = config.PHRASE_LOW_CONFIDENCE
        announce_low_confidence(haptic)
    else:
        if destination:
            announced_phrase = config.PHRASE_ROUTE_WITH_DESTINATION_TEMPLATE.format(
                route=corrected_route, destination=destination
            )
        else:
            announced_phrase = config.PHRASE_ROUTE_TEMPLATE.format(route=corrected_route)
        announce_route(corrected_route, haptic, destination)
    feedback_s = time.monotonic() - t0

    print(f"[Stage 4 - Feedback] Spoken Phrase: \"{announced_phrase}\"")
    print(f"                    Feedback latency={feedback_s*1000:.1f}ms")

    total_s = time.monotonic() - t_start
    print("-" * 70)
    print(f"[*] Total Latency: {total_s*1000:.1f}ms / Budget: {config.BUDGET_TOTAL*1000:.0f}ms")
    if total_s <= config.BUDGET_TOTAL:
        print(f"[+] Status: SUCCESS - Meets real-time commuter budget! ({total_s:.3f}s <= 1.500s)")
    else:
        print(f"[-] Status: OVER BUDGET ({total_s:.3f}s > 1.500s)")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Test route identifier on online or local images.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", type=str, help="HTTP/HTTPS URL of bus route image")
    group.add_argument("--file", type=str, help="Local file path to bus image")
    args = parser.parse_args()

    try:
        if args.url:
            frame = download_image_from_url(args.url)
            source_label = args.url
        else:
            path = Path(args.file)
            if not path.exists():
                print(f"Error: File '{path}' does not exist.")
                sys.exit(1)
            frame = cv2.imread(str(path))
            if frame is None:
                print(f"Error: Could not read image from '{path}'.")
                sys.exit(1)
            source_label = str(path)

        run_pipeline_on_frame(frame, source_label)

    except Exception as e:
        print(f"\n[ERROR] Pipeline run failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

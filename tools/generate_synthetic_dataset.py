"""
tools/generate_synthetic_dataset.py
====================================
Generates synthetic bus route board photos with KNOWN correct answers, so you
have a large, labeled test set beyond the handful of real photos in
test_images/. Real photos are still the ones that matter most for proving
real-world accuracy — this is a supplement for volume and edge-case coverage
(distance/blur/angle variety), not a replacement.

Each image simulates a route board mounted on a windshield: an LED-style
amber-on-black board OR a painted white-on-black placard, with route number +
destination text, rendered onto a photo-like background, then perturbed with
blur, rotation, perspective skew, and JPEG compression to resemble a real
phone photo taken from a few metres away.

Usage:
    python tools/generate_synthetic_dataset.py --count 40
    python tools/benchmark_ocr.py --images test_images/synthetic \
        --ground-truth test_images/synthetic/ground_truth.csv
"""
import argparse
import csv
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
]

BOARD_STYLES = ["led_amber", "led_white", "painted_black"]


def _load_routes() -> list:
    """Pull real (route, destination) pairs from the project's own CSVs —
    keeps synthetic labels consistent with what the lookup table actually
    knows, so a correct OCR read also produces a correct destination match."""
    pairs = []
    routes_dir = ROOT_DIR / "data" / "routes"
    for csv_path in sorted(routes_dir.glob("*.csv")):
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                route = (row.get("route") or "").strip().upper()
                dest = (row.get("destination") or "").strip()
                if route:
                    pairs.append((route, dest))
    return pairs


def _render_board(route: str, destination: str, style: str) -> Image.Image:
    """Render one route board as a PIL image (before photo-style perturbation)."""
    w, h = 640, 220
    if style == "led_amber":
        bg, fg = (10, 10, 10), (255, 176, 30)
    elif style == "led_white":
        bg, fg = (8, 8, 8), (235, 235, 235)
    else:  # painted_black placard, white text, common on rear windows
        bg, fg = (15, 15, 15), (255, 255, 255)

    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)

    route_font = ImageFont.truetype(random.choice(FONT_PATHS), 96)
    dest_font = ImageFont.truetype(FONT_PATHS[0], 34)

    draw.text((30, 20), route, font=route_font, fill=fg)
    if destination:
        # Wrap long destination strings across two lines so they don't run
        # off the board — real boards do this too.
        words = destination.split()
        line1, line2 = "", ""
        for word in words:
            if len(line1) + len(word) < 26:
                line1 = (line1 + " " + word).strip()
            else:
                line2 = (line2 + " " + word).strip()
        draw.text((260, 40), line1, font=dest_font, fill=fg)
        if line2:
            draw.text((260, 90), line2, font=dest_font, fill=fg)

    return img


def _photo_background(w: int, h: int, rng: random.Random) -> np.ndarray:
    """A loose, textured background standing in for sky/trees/bus-body context
    around the board, so the board isn't sitting in a clean void."""
    base = rng.choice([
        (150, 170, 190),  # overcast sky
        (90, 130, 170),   # clear sky
        (60, 60, 65),     # bus body grey
        (200, 60, 50),    # bus body red
    ])
    bg = np.full((h, w, 3), base, dtype=np.uint8)
    noise = np.random.randint(-15, 15, (h, w, 3))
    bg = np.clip(bg.astype(int) + noise, 0, 255).astype(np.uint8)
    return cv2.GaussianBlur(bg, (25, 25), 0)


def _apply_photo_realism(board_bgr: np.ndarray, rng: random.Random, difficulty: str) -> np.ndarray:
    """Composite the board onto a background frame and degrade it to resemble
    a real phone photo taken at a distance/angle, at a chosen difficulty."""
    bh, bw = board_bgr.shape[:2]

    if difficulty == "easy":
        canvas_scale = rng.uniform(1.3, 1.6)
        max_angle, max_blur = 2, 1
    elif difficulty == "medium":
        canvas_scale = rng.uniform(1.8, 2.6)
        max_angle, max_blur = 6, 3
    else:  # hard — small/distant board, more distortion
        canvas_scale = rng.uniform(3.0, 4.5)
        max_angle, max_blur = 12, 5

    canvas_w, canvas_h = int(bw * canvas_scale), int(bh * canvas_scale)
    canvas = _photo_background(canvas_w, canvas_h, rng)

    # Slight perspective warp on the board itself (viewing angle).
    src = np.float32([[0, 0], [bw, 0], [bw, bh], [0, bh]])
    jitter = bw * 0.04 * (1 if difficulty != "easy" else 0.3)
    dst = np.float32([
        [rng.uniform(0, jitter), rng.uniform(0, jitter)],
        [bw - rng.uniform(0, jitter), rng.uniform(0, jitter * 0.5)],
        [bw - rng.uniform(0, jitter * 0.5), bh - rng.uniform(0, jitter)],
        [rng.uniform(0, jitter), bh - rng.uniform(0, jitter * 0.5)],
    ])
    M = cv2.getPerspectiveTransform(src, dst)
    board_warped = cv2.warpPerspective(board_bgr, M, (bw, bh), borderValue=(20, 20, 20))

    # Paste roughly centered, with a random offset.
    off_x = rng.randint(0, max(1, canvas_w - bw))
    off_y = rng.randint(0, max(1, canvas_h - bh))
    canvas[off_y:off_y + bh, off_x:off_x + bw] = board_warped

    # Slight rotation of the whole frame (camera tilt).
    angle = rng.uniform(-max_angle, max_angle)
    Mrot = cv2.getRotationMatrix2D((canvas_w / 2, canvas_h / 2), angle, 1.0)
    canvas = cv2.warpAffine(canvas, Mrot, (canvas_w, canvas_h), borderValue=(120, 120, 120))

    # Blur (focus/motion/distance) and brightness jitter.
    k = rng.choice([1, 1, 3, max_blur if max_blur % 2 else max_blur + 1])
    if k > 1:
        canvas = cv2.GaussianBlur(canvas, (k, k), 0)
    brightness = rng.uniform(0.75, 1.2)
    canvas = np.clip(canvas.astype(float) * brightness, 0, 255).astype(np.uint8)

    return canvas


def generate(count: int, out_dir: Path, seed: int = 42):
    rng = random.Random(seed)
    pairs = _load_routes()
    if not pairs:
        print("No route CSVs found under data/routes/ — nothing to generate labels from.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []

    for i in range(count):
        route, destination = rng.choice(pairs)
        style = rng.choice(BOARD_STYLES)
        difficulty = rng.choices(["easy", "medium", "hard"], weights=[0.4, 0.4, 0.2])[0]

        board_pil = _render_board(route, destination, style)
        board_bgr = cv2.cvtColor(np.array(board_pil), cv2.COLOR_RGB2BGR)
        final = _apply_photo_realism(board_bgr, rng, difficulty)

        safe_route = route.replace("/", "-")
        filename = f"synth_{i:03d}_{safe_route}_{difficulty}.jpg"
        quality = rng.randint(55, 90)  # JPEG artifacts, like a real phone photo
        cv2.imwrite(str(out_dir / filename), final, [cv2.IMWRITE_JPEG_QUALITY, quality])
        manifest.append((filename, route))

    gt_path = out_dir / "ground_truth.csv"
    with open(gt_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "route"])
        writer.writerows(manifest)

    print(f"Generated {count} synthetic images -> {out_dir}")
    print(f"Ground truth  -> {gt_path}")
    print(f"\nRun:\n  python tools/benchmark_ocr.py --images {out_dir} --ground-truth {gt_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--out", default="test_images/synthetic")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    generate(args.count, ROOT_DIR / args.out, seed=args.seed)

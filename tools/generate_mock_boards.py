"""
tools/generate_mock_boards.py
=============================
Generates realistic bus route display board test images in test_images/
to benchmark OCR, fuzzy-matching correction, and destination lookup.
"""
from pathlib import Path
import cv2
import numpy as np

output_dir = Path("test_images")
output_dir.mkdir(exist_ok=True)

test_boards = [
    {
        "filename": "board_23A_ganguru.jpg",
        "route_text": "23A",
        "dest_text": "GANGURU",
        "bg_color": (30, 30, 30),      # Dark LED matrix background
        "text_color": (0, 215, 255),   # Bright Amber / Yellow LED
    },
    {
        "filename": "board_305_railway.jpg",
        "route_text": "305",
        "dest_text": "RLY STATION",
        "bg_color": (240, 240, 240),   # White acrylic board
        "text_color": (20, 20, 180),   # Dark Navy / Red lettering
    },
    {
        "filename": "board_3O5_noisy_glare.jpg",
        "route_text": "3O5",            # Simulating letter 'O' instead of zero
        "dest_text": "P.N.B.S.",
        "bg_color": (20, 50, 20),      # Dark green bus board
        "text_color": (250, 250, 250), # White paint with glare
        "add_glare": True,
    },
    {
        "filename": "board_1G_kankipadu.jpg",
        "route_text": "1G",
        "dest_text": "KANKIPADU",
        "bg_color": (15, 15, 15),
        "text_color": (50, 255, 50),   # Green LED display
    },
    {
        "filename": "board_unknown_404.jpg",
        "route_text": "404",
        "dest_text": "AIRPORT SHUTTLE",
        "bg_color": (40, 40, 40),
        "text_color": (255, 255, 255),
    }
]

for item in test_boards:
    # 640x480 standard camera frame resolution
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:] = item["bg_color"]

    # Draw simulated route board bezel
    cv2.rectangle(img, (40, 100), (600, 380), (80, 80, 80), 6)

    # Route number text (large, high contrast)
    cv2.putText(
        img,
        item["route_text"],
        (70, 280),
        cv2.FONT_HERSHEY_DUPLEX,
        4.0,
        item["text_color"],
        8,
        cv2.LINE_AA,
    )

    # Destination subtitle text
    cv2.putText(
        img,
        item["dest_text"],
        (70, 350),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        item["text_color"],
        3,
        cv2.LINE_AA,
    )

    # Simulate non-uniform outdoor sunlight glare if requested
    if item.get("add_glare"):
        overlay = img.copy()
        cv2.circle(overlay, (200, 240), 180, (255, 255, 255), -1)
        img = cv2.addWeighted(overlay, 0.25, img, 0.75, 0)

    out_path = output_dir / item["filename"]
    cv2.imwrite(str(out_path), img)
    print(f"[+] Generated: {out_path}")

print(f"\nGenerated {len(test_boards)} test bus route images in {output_dir.resolve()}")

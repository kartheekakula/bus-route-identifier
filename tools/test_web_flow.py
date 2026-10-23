"""
tools/test_web_flow.py
======================
Simulates client uploading each image in test_images/ to the web app
and prints the route, engine, and latency for each.
"""
import io
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from web_app import app


def test_web_uploads(mode="auto"):
    config.OCR_MODE = mode
    client = app.test_client()

    print("=" * 75)
    print(f"TESTING WEB APP END-TO-END UPLOADS (OCR_MODE={mode})")
    print("=" * 75)
    print(f"{'FILE':<38} {'ROUTE':<10} {'ENGINE':<10} {'LATENCY':>10}")
    print("-" * 75)

    test_dir = Path("test_images")
    valid_exts = {".jpg", ".jpeg", ".png"}

    for p in sorted(test_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() not in valid_exts or p.name.startswith("debug_"):
            continue

        with open(p, "rb") as fh:
            img_bytes = fh.read()

        data = {
            "file": (io.BytesIO(img_bytes), p.name),
        }

        resp = client.post("/api/identify", data=data, content_type="multipart/form-data")
        if resp.status_code != 200:
            print(f"{p.name[:36]:<38} ERROR {resp.status_code}: {resp.get_json()}")
            continue

        res_json = resp.get_json()
        route = res_json.get("route") or "none"
        engine = res_json.get("engine") or res_json["stages"]["ocr"]["engine"]
        time_ms = res_json["stages"]["ocr"]["time_ms"]

        print(f"{p.name[:36]:<38} {route:<10} {engine:<10} {time_ms:>8.1f}ms")

    print("-" * 75)


if __name__ == "__main__":
    mode_arg = sys.argv[1] if len(sys.argv) > 1 else "auto"
    test_web_uploads(mode_arg)

"""
tools/pregenerate_cache.py
===========================
Run this ONCE (offline, not on the hot path) to pre-render audio clips
for config.COMMON_ROUTES. This is the single biggest latency win
available for routes you announce often — it turns the feedback stage
from "run a synthesizer" into "play a file", cutting ~30-150ms down to
~10-20ms per announcement.

Usage:
    python tools/pregenerate_cache.py
    python tools/pregenerate_cache.py --routes 12 21C 45 500A
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from routes import RouteLookup  # noqa: E402
from feedback import _synthesize_espeak, _synthesize_piper  # noqa: E402



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--routes", nargs="*", default=config.COMMON_ROUTES)
    args = parser.parse_args()

    config.AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    route_lookup = RouteLookup(routes_dir=config.ROUTES_DATA_DIR, city=config.CITY)

    for route in args.routes:
        dest = route_lookup.lookup(route)
        if dest:
            text = config.PHRASE_ROUTE_WITH_DESTINATION_TEMPLATE.format(route=route, destination=dest)
        else:
            text = config.PHRASE_ROUTE_TEMPLATE.format(route=route)
        out_path = config.AUDIO_CACHE_DIR / f"{route.replace('/', '-')}.wav"
        print(f"Rendering '{text}' -> {out_path}")
        if config.TTS_ENGINE == "piper":
            _synthesize_piper(text, out_path)
        else:
            _synthesize_espeak(text, out_path)


    print(f"Done. {len(args.routes)} clips cached in {config.AUDIO_CACHE_DIR}")


if __name__ == "__main__":
    main()

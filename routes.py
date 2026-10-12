"""
routes.py
=========
Offline route-to-destination lookup and fuzzy correction.

This module loads a per-city CSV file at startup containing known route numbers
and their destination names. It is used to correct noisy OCR reads and enrich
voice feedback with destination information without adding runtime file-system
access latency.
"""
import csv
import difflib
import logging
import time
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger("bus_route.routes")


class RouteLookup:
    """Loads and matches route numbers against a city-specific offline dataset.

    Should be instantiated ONCE at startup to avoid runtime file-system access.
    """

    def __init__(self, routes_dir: Path, city: str):
        self.routes_dir = Path(routes_dir)
        self.city = city
        self.routes: Dict[str, str] = {}
        self.startup_complete = False
        self.load_data()

    def load_data(self):
        """Loads route mappings from the city CSV file.

        Logs a warning if called after startup has completed.
        """
        if self.startup_complete:
            logger.warning(
                "CRITICAL WARNING: Route data loaded outside of startup path! "
                "This violates latency budget constraints."
            )

        t0 = time.monotonic()
        csv_path = self.routes_dir / f"{self.city}.csv"
        if not csv_path.exists():
            logger.warning(
                "Route data file '%s' does not exist. Operating in no-destination/no-lookup mode.",
                csv_path,
            )
            return

        try:
            with open(csv_path, mode="r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)

                # Skip header if it is standard route/destination format
                if header and len(header) >= 2:
                    if header[0].strip().lower() != "route" or header[1].strip().lower() != "destination":
                        # Not a header, process it
                        r, d = header[0].strip(), header[1].strip()
                        self.routes[r.upper()] = d

                rows_loaded = len(self.routes)
                for row in reader:
                    if len(row) >= 2:
                        route_num, dest = row[0].strip(), row[1].strip()
                        self.routes[route_num.upper()] = dest
                        rows_loaded += 1

            elapsed = time.monotonic() - t0
            logger.info(
                "Loaded %d routes for city '%s' from %s in %.3fs.",
                rows_loaded,
                self.city,
                csv_path.name,
                elapsed,
            )
        except Exception as e:
            logger.exception("Failed to load route data from %s: %s", csv_path, e)

        # Also load all other available city datasets at startup (offline multi-city support)
        self.all_cities_routes: Dict[str, str] = dict(self.routes)
        try:
            for other_csv in self.routes_dir.glob("*.csv"):
                if other_csv.name.lower() == f"{self.city}.csv".lower():
                    continue
                with open(other_csv, mode="r", encoding="utf-8") as f:
                    rdr = csv.reader(f)
                    next(rdr, None)
                    for row in rdr:
                        if len(row) >= 2:
                            r_num, dest = row[0].strip().upper(), row[1].strip()
                            if r_num not in self.all_cities_routes:
                                self.all_cities_routes[r_num] = dest
        except Exception as e:
            logger.warning("Could not load other city CSVs: %s", e)

    def lookup(self, route: str) -> Optional[str]:
        """Look up the destination name for a given route number.

        Case-insensitive. Checks primary city first, then other loaded city datasets.
        """
        if not route:
            return None
        r_upper = route.upper()
        if r_upper in self.routes:
            return self.routes[r_upper]
        return getattr(self, "all_cities_routes", {}).get(r_upper)

    def correct_route(self, route: str) -> str:
        """Fuzzy match a noisy OCR route string against known valid routes.

        Checks against active city routes first, then all known routes.
        """
        if not route:
            return route

        route_upper = route.upper()
        all_known = getattr(self, "all_cities_routes", self.routes)
        if route_upper in all_known:
            return route_upper

        # Try to find a close match in primary city first
        known_primary = list(self.routes.keys())
        close_primary = difflib.get_close_matches(route_upper, known_primary, n=1, cutoff=0.6)
        if close_primary:
            return close_primary[0]

        # Try all known routes
        close_all = difflib.get_close_matches(route_upper, list(all_known.keys()), n=1, cutoff=0.6)
        if close_all:
            return close_all[0]

        return route

    def resolve_route_from_text(self, raw_text: str) -> Optional[str]:
        """Infers the route number if prominent destination names appear in the OCR text."""
        if not raw_text:
            return None
        import re
        text_upper = raw_text.upper()
        all_routes = getattr(self, "all_cities_routes", self.routes)
        best_match = None
        best_score = 0
        stop_words = {"ROAD", "GATE", "STOP", "STAND", "CITY", "TOWN", "MAIN", "NEAR", "STATION"}
        for r_num, dest in all_routes.items():
            dest_words = [w.strip() for w in re.split(r'[\s,\-/()]+', dest.upper()) if len(w.strip()) >= 4]
            dest_words = [w for w in dest_words if w not in stop_words]
            if not dest_words:
                continue
            matches = sum(1 for w in dest_words if w in text_upper)
            has_strong_word = any(w in text_upper for w in dest_words if len(w) >= 6)
            if (matches >= 2 or (matches >= 1 and has_strong_word)) and matches > best_score:
                best_score = matches
                best_match = r_num
        return best_match

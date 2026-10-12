"""
tools/analyze_logs.py
=======================
Summarizes logs/run_timings.csv into the kind of numbers a research
paper's evaluation section actually wants: mean/median/p95 latency per
stage, budget-overrun rate, and route-detection rate — computed from
REAL field usage, not a bench test.

Usage:
    python tools/analyze_logs.py
    python tools/analyze_logs.py --log-path logs/run_timings.csv --csv-out summary.csv
"""
import argparse
import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

STAGE_COLUMNS = ["capture_s", "preprocess_s", "ocr_s", "feedback_s", "total_s"]


def load_rows(log_path: Path):
    with open(log_path, newline="") as f:
        return list(csv.DictReader(f))


def percentile(values, pct):
    values = sorted(values)
    if not values:
        return float("nan")
    k = (len(values) - 1) * (pct / 100)
    f, c = int(k), min(int(k) + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-path", default=str(config.LOG_PATH))
    parser.add_argument("--csv-out", default=None, help="Optional path to write the summary as CSV")
    args = parser.parse_args()

    log_path = Path(args.log_path)
    if not log_path.exists():
        print(f"No log found at {log_path} — run the device a few times first.")
        return

    rows = load_rows(log_path)
    if not rows:
        print("Log file is empty.")
        return

    print(f"Analyzed {len(rows)} runs from {log_path}\n")
    summary_rows = [("stage", "mean_s", "median_s", "p95_s", "max_s")]

    for col in STAGE_COLUMNS:
        values = [float(r[col]) for r in rows if r[col]]
        mean_v = statistics.mean(values)
        median_v = statistics.median(values)
        p95_v = percentile(values, 95)
        max_v = max(values)
        print(f"{col:15s} mean={mean_v:.3f}s  median={median_v:.3f}s  p95={p95_v:.3f}s  max={max_v:.3f}s")
        summary_rows.append((col, f"{mean_v:.3f}", f"{median_v:.3f}", f"{p95_v:.3f}", f"{max_v:.3f}"))

    total_values = [float(r["total_s"]) for r in rows]
    over_budget = sum(1 for v in total_values if v > config.BUDGET_TOTAL)
    detected = sum(1 for r in rows if r["route"] and r["route"] != "None")

    print(f"\nBudget ({config.BUDGET_TOTAL}s) exceeded on {over_budget}/{len(rows)} runs "
          f"({100*over_budget/len(rows):.1f}%)")
    print(f"Route successfully detected on {detected}/{len(rows)} runs "
          f"({100*detected/len(rows):.1f}%)")

    if args.csv_out:
        with open(args.csv_out, "w", newline="") as f:
            csv.writer(f).writerows(summary_rows)
        print(f"\nSummary written to {args.csv_out}")


if __name__ == "__main__":
    main()

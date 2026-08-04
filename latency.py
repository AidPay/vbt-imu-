"""
latency.py -- instrument each stage (don't optimize by guessing)

Times parse / filter / fusion / detection per sample with a high-resolution
clock, then reports mean / median / p95 / max in milliseconds for each stage
and for total parse-to-output.

Two bounds to keep in mind:
  - end-to-end target: total < 100 ms per sample (from the plan)
  - real-time budget:  to keep up with a 100 Hz feed, total must stay under
                       10 ms per sample, or the pipeline falls behind the
                       stream. This is the tighter, more useful bound.

Note: these stages take microseconds each, which is close to the cost of the
timing calls themselves -- so read the RELATIVE breakdown and the headroom vs
the budgets, not the absolute numbers to three decimals. The instrumentation
earns its keep when Aiden's heavier fusion goes in and one stage starts to
dominate.

Run:
    python latency.py data/raw/sim/session_lift_sim.csv
"""

import sys
import time

import numpy as np

from pipeline import Pipeline, DATA_COLUMNS, _split_line
from fusion import ComplementaryFilter, RepDetector


def instrument(source, cutoff_hz=5.0, sample_rate=100.0):
    pipe = Pipeline(kind="lowpass", cutoff_hz=cutoff_hz, sample_rate=sample_rate)
    fuse = ComplementaryFilter(alpha=0.98, nominal_dt=1.0 / sample_rate)
    det = RepDetector(baseline_cutoff_hz=0.3, sample_rate=sample_rate, hysteresis=1.0)

    times = {k: [] for k in ("parse", "filter", "fusion", "detect", "total")}
    n = 0
    for line in source:
        t0 = time.perf_counter()
        parsed = _split_line(line)
        t1 = time.perf_counter()
        if parsed is None:
            continue
        ts, vals = parsed

        clean = dict(ts)
        for c, v in zip(DATA_COLUMNS, vals):
            clean[c] = pipe.filters[c].update(v)
        t2 = time.perf_counter()

        clean["pitch_fused"] = fuse.update(clean)
        t3 = time.perf_counter()

        det.update(clean["pitch_fused"], index=n)
        t4 = time.perf_counter()

        times["parse"].append(t1 - t0)
        times["filter"].append(t2 - t1)
        times["fusion"].append(t3 - t2)
        times["detect"].append(t4 - t3)
        times["total"].append(t4 - t0)
        n += 1
    return times, n


def _stats_ms(seconds):
    a = np.array(seconds) * 1000.0
    return a.mean(), np.median(a), np.percentile(a, 95), a.max()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/sim/session_lift_sim.csv"
    with open(path) as f:
        times, n = instrument(f)

    print("Per-stage latency over %d samples (milliseconds):\n" % n)
    print("  %-8s %8s %8s %8s %8s" % ("stage", "mean", "median", "p95", "max"))
    for stage in ("parse", "filter", "fusion", "detect", "total"):
        m, med, p95, mx = _stats_ms(times[stage])
        print("  %-8s %8.4f %8.4f %8.4f %8.4f" % (stage, m, med, p95, mx))

    total = np.array(times["total"]) * 1000.0
    p95_total = np.percentile(total, 95)
    print("\nTarget  : total < 100 ms/sample  -> %s (p95 = %.4f ms)"
          % ("PASS" if p95_total < 100 else "FAIL", p95_total))
    print("Realtime: total <  10 ms/sample  -> %s (keeps up with 100 Hz)"
          % ("PASS" if p95_total < 10 else "FAIL"))

    busy_s = np.sum(times["total"])
    if busy_s > 0:
        print("Throughput: ~%.0f samples/sec of processing capacity" % (n / busy_s))

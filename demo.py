"""
demo.py -- end-to-end demo runner + stream health check

One command takes a source (live board or replay) all the way through:
  source -> robust pipeline -> rep detection -> save session -> summary

    python demo.py --replay data/raw/sim/session_lift_sim.csv
    python demo.py --port COM3 --baud 9600          # Ctrl+C to stop

Stream health check for the "10+ minutes, no intervention" requirement --
monitors effective sample rate and stalls over a duration:

    python demo.py --port COM3 --health --duration 600            # real 10-min soak
    python demo.py --replay data/raw/sim/session_lift_sim.csv --health --duration 30
"""

import argparse
import time

from pipeline import _split_line
from robust import robust_process, reconnecting_serial
from persistence import save_session
from query import Session


def realtime_replay(path, rate_hz=100.0, duration_s=None):
    """Loop a file at ~rate_hz to imitate a continuous live feed. Stops after
    duration_s if given, otherwise after a single pass."""
    period = 1.0 / rate_hz if rate_hz > 0 else 0.0
    start = time.perf_counter()
    while True:
        with open(path) as f:
            for line in f:
                yield line
                if period:
                    time.sleep(period)
        if duration_s is None or time.perf_counter() - start >= duration_s:
            return


def run_demo(source, source_name, cutoff_hz=5.0, sample_rate=100.0, out_dir="sessions"):
    reps, q, n = robust_process(source, cutoff_hz=cutoff_hz, sample_rate=sample_rate)
    meta = {"source_file": source_name, "n_samples": n,
            "processing": {"filter": "lowpass",
                           "cutoff_hz": cutoff_hz, "sample_rate": sample_rate}}
    path = save_session(reps, meta, out_dir)
    s = Session.load(path)

    print("=" * 50)
    print("DEMO: %s" % source_name)
    print("=" * 50)
    print("samples processed : %d" % n)
    print("stream quality    : junk=%d  spikes=%d  dropouts=%d"
          % (q["junk_lines"], q["spike_samples"], q["dropouts"]))
    print("reps detected     : %d" % len(s))
    print("session stats     : %s" % s.stats())
    print("\nper rep:")
    for r in s:
        asy = r["asymmetry_score"]
        asy_s = ("%.2f deg" % asy) if asy is not None else "n/a"
        flag = "" if r.get("complete", True) else "   [INCOMPLETE %s]" % r.get("flags")
        print("  rep %-2d  asymmetry=%-10s%s" % (r["rep_id"], asy_s, flag))
    print("\nsaved -> %s" % path)
    return path


def stream_health(source, duration_s, expected_hz=100.0, stall_ms=200.0):
    """Watch a live/looped source for the full duration, tracking effective
    sample rate and any stalls (gaps longer than stall_ms)."""
    start = last = time.perf_counter()
    n = stalls = 0
    longest = 0.0
    for line in source:
        now = time.perf_counter()
        gap = now - last
        last = now
        if gap * 1000 > stall_ms:
            stalls += 1
            longest = max(longest, gap)
        if _split_line(line) is not None:
            n += 1
        if now - start >= duration_s:
            break

    elapsed = time.perf_counter() - start
    eff = n / elapsed if elapsed > 0 else 0.0
    print("=" * 50)
    print("STREAM HEALTH (%.0f s)" % elapsed)
    print("=" * 50)
    print("samples         : %d" % n)
    print("effective rate  : %.1f Hz (expected ~%.0f)" % (eff, expected_hz))
    print("stalls (>%.0f ms) : %d" % (stall_ms, stalls))
    print("longest stall   : %.0f ms" % (longest * 1000))
    ok = (elapsed >= duration_s * 0.99 and stalls == 0 and eff > expected_hz * 0.8)
    print("\nRESULT: %s" % ("PASS -- streamed cleanly with no intervention"
                            if ok else "CHECK -- see stalls / rate above"))
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="VBT-IMU demo runner and stream health check.")
    ap.add_argument("--replay", help="replay a CSV file")
    ap.add_argument("--port", help="live serial port, e.g. COM3")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--health", action="store_true", help="run the stream health check")
    ap.add_argument("--duration", type=float, default=600.0, help="health check seconds")
    ap.add_argument("--rate", type=float, default=100.0, help="expected/replay Hz")
    args = ap.parse_args()

    if args.health:
        if args.port:
            src = reconnecting_serial(args.port, args.baud)
        elif args.replay:
            src = realtime_replay(args.replay, args.rate, duration_s=args.duration)
        else:
            ap.error("health check needs --port or --replay")
        stream_health(src, args.duration, expected_hz=args.rate)
    else:
        if args.port:
            src = reconnecting_serial(args.port, args.baud)
            name = args.port
        elif args.replay:
            from logger import replay_source
            src = replay_source(args.replay, args.rate)
            name = args.replay
        else:
            ap.error("give --replay <file> or --port <COMx>")
        run_demo(src, name, sample_rate=args.rate)

"""
logger.py -- VBT-IMU session logger

Captures a session and writes a timestamped CSV, one row per sample, flushed
as data arrives so a crash or unplug never loses what was already recorded.

Two sources, one logging path:
  live serial  -- real board over a COM port (needs: pip install pyserial)
  replay       -- an existing CSV, replayed like a live feed, so you can test
                  the whole logging path with NO hardware connected.

The raw feed has no timestamp. This logger adds two columns as samples arrive:
  t_iso     wall-clock time (ISO 8601), for humans
  t_mono_s  seconds since the first sample, from a steady monotonic clock --
            this is the one fusion should use for dt between samples.

Usage:
  # test with no hardware, replaying a sim file into a test folder:
  python logger.py --replay data/raw/sim/session_lift_sim.csv --out data/raw/test

  # real capture from the board on COM3:
  python logger.py --port COM3 --baud 9600
"""

import argparse
import csv
import os
import time
from datetime import datetime

# Same 7-column contract the parser enforces.
DATA_COLUMNS = [
    "accel_x", "accel_y", "accel_z",
    "gyro_x", "gyro_y", "gyro_z",
    "pitch_accel",
]
OUTPUT_COLUMNS = ["t_iso", "t_mono_s"] + DATA_COLUMNS


def parse_line(line):
    """Turn one raw line into 7 floats, or return None if it isn't a valid
    data line (header row, partial fragment, blank, or junk)."""
    line = line.strip()
    if not line:
        return None
    parts = line.split(",")
    if len(parts) != len(DATA_COLUMNS):
        return None
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None            # header row or garbled fragment -> skip


def serial_source(port, baud):
    """Yield raw lines from the board. pyserial is imported lazily so replay
    mode works even without it installed."""
    import serial             # pip install pyserial
    ser = serial.Serial(port, baud, timeout=1)
    print("Listening on %s @ %d baud. Ctrl+C to stop." % (port, baud))
    try:
        while True:
            raw = ser.readline().decode("utf-8", errors="ignore")
            if raw:
                yield raw
    finally:
        ser.close()


def replay_source(csv_path, rate_hz=100.0):
    """Yield lines from an existing CSV at ~rate_hz, imitating the live board
    so the logging path can be tested with no hardware."""
    period = 1.0 / rate_hz if rate_hz > 0 else 0.0
    print("Replaying %s at ~%.0f Hz." % (csv_path, rate_hz))
    with open(csv_path) as f:
        for raw in f:
            yield raw
            if period:
                time.sleep(period)


def log_session(source, out_dir="data/raw/real"):
    """Consume a source of raw lines, stamp each sample, and write a
    timestamped CSV, flushing every row so nothing is lost on a crash."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_path = os.path.join(out_dir, "session_%s.csv" % stamp)

    n = 0
    t0 = None
    with open(out_path, "w", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(OUTPUT_COLUMNS)
        try:
            for raw in source:
                sample = parse_line(raw)
                if sample is None:
                    continue                     # skip header / partial / junk
                now = time.monotonic()
                if t0 is None:
                    t0 = now
                t_iso = datetime.now().isoformat(timespec="milliseconds")
                t_mono = now - t0
                writer.writerow([t_iso, "%.4f" % t_mono] + sample)
                out.flush()                      # persist immediately
                n += 1
                if n % 100 == 0:
                    print("  logged %d samples..." % n)
        except KeyboardInterrupt:
            print("\nStopped by user.")

    print("Wrote %d samples to %s" % (n, out_path))
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Log a VBT-IMU session to a timestamped CSV.")
    ap.add_argument("--port", help="serial port for live capture, e.g. COM3")
    ap.add_argument("--baud", type=int, default=9600, help="baud rate (default 9600)")
    ap.add_argument("--replay", help="replay an existing CSV instead of live capture")
    ap.add_argument("--rate", type=float, default=100.0, help="replay rate in Hz")
    ap.add_argument("--out", default="data/raw/real", help="output directory")
    args = ap.parse_args()

    if args.replay:
        src = replay_source(args.replay, args.rate)
    elif args.port:
        src = serial_source(args.port, args.baud)
    else:
        ap.error("give either --replay <csv> or --port <COMx>")

    log_session(src, args.out)

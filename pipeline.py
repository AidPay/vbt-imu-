"""
pipeline.py -- one entry point, one output stream

Ties the stages together: raw line in -> parse -> filter -> clean sample out.
The pipeline processes ONE sample at a time and holds filter state between
samples, so the exact same object works on a live serial feed or a replayed
log file. Same code path either way -- that is what makes offline testing
trustworthy.

Usage as a stream (real use):
    from pipeline import Pipeline
    from logger import replay_source, serial_source

    pipe = Pipeline(cutoff_hz=5.0, sample_rate=100.0)
    for clean in pipe.run(replay_source("data/raw/sim/session_lift_sim.csv")):
        ...   # clean is a dict of filtered values, ready for fusion

Run this file directly to prove the live and replayed paths are identical:
    python pipeline.py data/raw/sim/session_lift_sim.csv
"""

import numpy as np

from filters import make_filter

DATA_COLUMNS = [
    "accel_x", "accel_y", "accel_z",
    "gyro_x", "gyro_y", "gyro_z",
    "pitch_accel",
]


def _split_line(line):
    """Parse one raw line into (timestamps_dict, [7 floats]) or None.

    Accepts 7-field lines (raw feed) and 9-field lines (logged: t_iso,
    t_mono_s, + 7). Header rows and junk return None.
    """
    line = line.strip()
    if not line:
        return None
    parts = line.split(",")
    if len(parts) == 7:
        ts, vals = {}, parts
    elif len(parts) == 9:
        ts, vals = {"t_iso": parts[0], "t_mono_s": parts[1]}, parts[2:]
    else:
        return None
    try:
        floats = [float(v) for v in vals]
    except ValueError:
        return None            # header row or garbled fragment
    return ts, floats


class Pipeline:
    """Stateful streaming pipeline. One filter per channel, fed one sample
    at a time so it behaves identically live and on replay."""

    def __init__(self, kind="lowpass", cutoff_hz=5.0, sample_rate=100.0, window=5):
        self.filters = {
            c: make_filter(kind, cutoff_hz, sample_rate, window)
            for c in DATA_COLUMNS
        }

    def process(self, raw_line):
        """Parse + filter one line. Returns a clean sample dict, or None if
        the line was a header / partial / junk."""
        parsed = _split_line(raw_line)
        if parsed is None:
            return None
        ts, vals = parsed
        out = dict(ts)                      # carry timestamps through untouched
        for c, v in zip(DATA_COLUMNS, vals):
            out[c] = self.filters[c].update(v)
        return out

    def run(self, source):
        """Consume a source of raw lines, yield clean filtered samples."""
        for raw in source:
            clean = self.process(raw)
            if clean is not None:
                yield clean


if __name__ == "__main__":
    import sys
    from parser import parse_session
    from filters import filter_session

    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/sim/session_lift_sim.csv"
    CUTOFF, FS = 5.0, 100.0

    # OFFLINE path: filter the whole array at once.
    batch = filter_session(parse_session(path),
                           kind="lowpass", cutoff_hz=CUTOFF, sample_rate=FS)

    # LIVE path: same file, one line at a time through the streaming pipeline.
    pipe = Pipeline(kind="lowpass", cutoff_hz=CUTOFF, sample_rate=FS)
    streamed = {c: [] for c in DATA_COLUMNS}
    with open(path) as f:
        for line in f:
            clean = pipe.process(line)
            if clean is not None:
                for c in DATA_COLUMNS:
                    streamed[c].append(clean[c])
    streamed = {c: np.array(v) for c, v in streamed.items()}

    print("Live (streaming) vs replayed (batch) equivalence on %s\n" % path)
    all_match = True
    for c in DATA_COLUMNS:
        ok = np.array_equal(batch[c], streamed[c])
        maxdiff = (np.max(np.abs(batch[c] - streamed[c]))
                   if len(streamed[c]) else float("nan"))
        all_match = all_match and ok
        print("  %-12s identical=%s  max_diff=%.2e" % (c, ok, maxdiff))

    print("\n%s" % ("PASS: live and replayed paths produce identical output."
                    if all_match else
                    "FAIL: paths diverge -- do not trust offline tests yet."))

"""
parser.py -- VBT-IMU session parser

Reads a session CSV (see data/raw/sim/*.csv) into labeled float arrays and
validates each column against the data dictionary in data_format.md.

IMPORTANT: the current firmware (Seeed XIAO nRF52840 Sense, LSM6DS3TR-C)
streams data ALREADY SCALED into g and deg/s as CSV text lines. So this
parser does NOT convert raw counts -- it reads floats directly and checks
they are in range. If the firmware ever changes to stream raw int16 counts
or a binary frame, a decode+scaling step gets added here and the format
spec has to be updated to match.

Usage (from the repo root):
    python parser.py data/raw/sim/session_flat.csv
"""

import csv
import sys
import numpy as np

# Frozen column contract -- must match data_format.md exactly.
EXPECTED_COLUMNS = [
    "accel_x", "accel_y", "accel_z",
    "gyro_x", "gyro_y", "gyro_z",
    "pitch_accel",
]

# (min, max) valid ranges from data_format.md, with a little margin so real
# noise near the rails does not trip false alarms.
VALID_RANGES = {
    "accel_x": (-2.5, 2.5),
    "accel_y": (-2.5, 2.5),
    "accel_z": (-2.5, 2.5),
    "gyro_x": (-250.0, 250.0),
    "gyro_y": (-250.0, 250.0),
    "gyro_z": (-250.0, 250.0),
    "pitch_accel": (-90.0, 90.0),
}


def parse_session(path):
    """Read a session CSV into a dict of labeled float arrays.

    Returns a dict mapping column name -> np.ndarray(float). Every array has
    the same length (number of samples).
    Raises ValueError if the header does not match EXPECTED_COLUMNS.
    """
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        if header != EXPECTED_COLUMNS:
            raise ValueError(
                "Header mismatch in %s\n  expected: %s\n  got:      %s"
                % (path, EXPECTED_COLUMNS, header)
            )
        rows = [[float(v) for v in row] for row in reader if row]

    data = np.array(rows, dtype=float)                 # shape (n_samples, n_cols)
    return {col: data[:, i] for i, col in enumerate(EXPECTED_COLUMNS)}


def validate_ranges(session):
    """Return a list of (column, row_index, value) for out-of-range samples."""
    problems = []
    for col, (lo, hi) in VALID_RANGES.items():
        arr = session[col]
        bad = np.where((arr < lo) | (arr > hi))[0]
        for i in bad:
            problems.append((col, int(i), float(arr[i])))
    return problems


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/sim/session_flat.csv"

    session = parse_session(path)
    n = len(session["accel_x"])
    print("Parsed %d samples from %s\n" % (n, path))

    # Field-by-field verification: print the first few rows exactly as parsed
    # so you can eyeball them against the raw CSV before trusting anything.
    print("First 3 samples (verify against the raw file):")
    for i in range(min(3, n)):
        vals = ", ".join("%s=%+.4f" % (c, session[c][i]) for c in EXPECTED_COLUMNS)
        print("  [%d] %s" % (i, vals))

    # Sanity check from data_format.md: board flat -> az ~ 1.0, ax/ay ~ 0.0.
    print("\nColumn means over the session:")
    for c in EXPECTED_COLUMNS:
        print("  %-12s mean=%+.4f" % (c, session[c].mean()))

    problems = validate_ranges(session)
    if problems:
        print("\nWARNING: %d out-of-range samples:" % len(problems))
        for col, i, v in problems[:10]:
            print("    %s @ row %d: %s" % (col, i, v))
    else:
        print("\nOK: all samples within data_format.md ranges.")

"""
filters.py -- configurable noise filters for the VBT-IMU pipeline

Two filter types, both driven by parameters (not hardcoded constants) so the
cutoff can be swept independently:

  LowPass(cutoff_hz, sample_rate)   one-pole low-pass. Cutoff is given in Hz;
                                    alpha is derived from it. (Aiden's hand-
                                    tuned alpha maps to a cutoff -- see note
                                    below -- so both people describe the same
                                    filter in the units they think in.)
  MovingAverage(window)             simple N-sample rolling average.

Both work TWO ways from the same object:
  .update(x)   feed one sample, get one filtered sample back (holds state).
               This is what the LIVE pipeline uses -- one sample at a time.
  .apply(arr)  filter a whole array at once (resets state first).
               Handy for offline work on a recorded session.

alpha <-> cutoff (one-pole):
    alpha = dt / (RC + dt),  RC = 1 / (2*pi*cutoff_hz),  dt = 1 / sample_rate
So if Aiden tuned alpha = A at sample_rate fs:
    cutoff_hz = (A * fs) / (2*pi*(1 - A))
"""

import math
from collections import deque

import numpy as np

# columns that are timestamps, not signal -- never filtered
NON_SIGNAL = ("t_iso", "t_mono_s", "sample_counter")


class LowPass:
    """One-pole (exponential) low-pass filter, cutoff specified in Hz."""

    def __init__(self, cutoff_hz, sample_rate):
        self.cutoff_hz = cutoff_hz
        self.sample_rate = sample_rate
        self.alpha = self._alpha(cutoff_hz, sample_rate)
        self.y = None

    @staticmethod
    def _alpha(cutoff_hz, sample_rate):
        dt = 1.0 / sample_rate
        rc = 1.0 / (2.0 * math.pi * cutoff_hz)
        return dt / (rc + dt)

    def update(self, x):
        """Feed one sample, return the filtered value. Holds state."""
        if self.y is None:
            self.y = x
        else:
            self.y += self.alpha * (x - self.y)
        return self.y

    def reset(self):
        self.y = None

    def apply(self, arr):
        """Filter a whole array (resets state first)."""
        self.reset()
        return np.array([self.update(float(v)) for v in arr])


class MovingAverage:
    """Simple rolling average over the last `window` samples."""

    def __init__(self, window):
        self.window = int(window)
        self.buf = deque(maxlen=self.window)

    def update(self, x):
        self.buf.append(x)
        return sum(self.buf) / len(self.buf)

    def reset(self):
        self.buf.clear()

    def apply(self, arr):
        self.reset()
        return np.array([self.update(float(v)) for v in arr])


def make_filter(kind="lowpass", cutoff_hz=5.0, sample_rate=100.0, window=5):
    """Factory: return a fresh filter object of the requested kind.

    A factory is used (rather than one shared object) because each signal
    channel needs its OWN state -- sharing one filter across channels would
    bleed accel values into gyro values.
    """
    if kind == "lowpass":
        return LowPass(cutoff_hz, sample_rate)
    if kind == "moving_average":
        return MovingAverage(window)
    raise ValueError("unknown filter kind: %r" % kind)


def filter_session(session, kind="lowpass", cutoff_hz=5.0,
                   sample_rate=100.0, window=5, columns=None):
    """Filter every signal channel of a parsed session with its own filter.

    Timestamp columns are copied through untouched. Returns a new dict.
    """
    if columns is None:
        columns = [c for c in session if c not in NON_SIGNAL]

    out = dict(session)  # keep timestamps / non-signal columns as-is
    for c in columns:
        f = make_filter(kind, cutoff_hz, sample_rate, window)
        out[c] = f.apply(session[c])
    return out


if __name__ == "__main__":
    import sys
    from parser import parse_session

    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/sim/session_motion.csv"
    session = parse_session(path)

    filtered = filter_session(session, kind="lowpass",
                              cutoff_hz=5.0, sample_rate=100.0)

    fc = 5.0
    fs = 100.0
    print("Low-pass @ %.1f Hz cutoff (sample_rate %.0f Hz)" % (fc, fs))
    print("alpha = %.4f\n" % LowPass._alpha(fc, fs))
    print("Noise drop = standard deviation before vs after filtering:")
    for c in ["accel_x", "gyro_y", "pitch_accel"]:
        raw = session[c].std()
        filt = filtered[c].std()
        print("  %-12s std raw=%.4f  filtered=%.4f" % (c, raw, filt))

"""
fusion.py -- streaming sensor fusion + rep detection (REFERENCE IMPLEMENTATION)

This is a correct-by-construction placeholder, NOT Aiden's algorithm. It exists
so the pipeline runs end-to-end today and so Aiden's real code has a precise
interface to drop into. When his fusion / rep detection is ready, replace the
INSIDES of these two classes -- the .update(...) contract stays the same.

Both classes follow the streaming rules the live pipeline needs:
  - hold state between samples (no reprocessing a whole buffer)
  - integrate using the ACTUAL elapsed time between samples (t_mono_s),
    never an assumed fixed dt

Run directly to exercise the full chain on a sim file:
    python fusion.py data/raw/sim/session_lift_sim.csv
"""

import math
import sys

from filters import LowPass
from pipeline import Pipeline, DATA_COLUMNS


class ComplementaryFilter:
    """Estimate pitch by blending integrated gyro rate with accel-based pitch.

    pitch = alpha * (pitch_prev + gyro_rate * dt) + (1 - alpha) * pitch_accel

    alpha near 1.0 trusts the gyro short-term and leans on the accelerometer
    only to cancel long-term drift.
    """

    def __init__(self, alpha=0.98, nominal_dt=0.01, gyro_key="gyro_y",
                 accel_pitch_key="pitch_accel"):
        self.alpha = alpha
        self.nominal_dt = nominal_dt          # used only when no timestamp
        self.gyro_key = gyro_key              # data_format.md: gyro_y = pitch rate
        self.accel_pitch_key = accel_pitch_key
        self.pitch = None
        self.last_t = None
        self.used_real_dt = False             # for reporting

    def _dt(self, sample):
        """Actual elapsed time since the last sample, from t_mono_s if the
        sample carries it; otherwise fall back to nominal_dt."""
        t = sample.get("t_mono_s")
        if t is None:
            return self.nominal_dt
        t = float(t)
        if self.last_t is None:
            self.last_t = t
            return self.nominal_dt
        dt = t - self.last_t
        self.last_t = t
        self.used_real_dt = True
        return dt if dt > 0 else self.nominal_dt

    def update(self, sample):
        """Feed one clean sample dict, return the fused pitch (degrees)."""
        dt = self._dt(sample)
        accel_pitch = sample[self.accel_pitch_key]
        gyro_rate = sample[self.gyro_key]

        if self.pitch is None:
            self.pitch = accel_pitch          # seed from accelerometer
        else:
            gyro_pitch = self.pitch + gyro_rate * dt
            self.pitch = self.alpha * gyro_pitch + (1 - self.alpha) * accel_pitch
        return self.pitch


class RepDetector:
    """Baseline rep counter: counts full oscillations of a signal around an
    adaptive midline (a slow low-pass), using two thresholds (a Schmitt
    trigger) so noise near the midline doesn't double-count.

    Emits a dict {rep_id, start_idx, end_idx} the moment a rep completes,
    else None. Swap this whole body for Aiden's detector when ready.
    """

    def __init__(self, baseline_cutoff_hz=0.3, sample_rate=100.0, hysteresis=1.0):
        self.midline = LowPass(baseline_cutoff_hz, sample_rate)
        self.hyst = hysteresis
        self.armed = False       # signal has dipped below the low band
        self.count = 0
        self.rep_start = None

    def update(self, value, index):
        mid = self.midline.update(value)
        low, high = mid - self.hyst, mid + self.hyst

        if value < low:
            if not self.armed:
                self.armed = True
                self.rep_start = index
            return None
        if value > high and self.armed:
            self.count += 1
            self.armed = False
            return {"rep_id": self.count,
                    "start_idx": self.rep_start,
                    "end_idx": index}
        return None


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/sim/session_lift_sim.csv"

    pipe = Pipeline(kind="lowpass", cutoff_hz=5.0, sample_rate=100.0)
    fuse = ComplementaryFilter(alpha=0.98, nominal_dt=0.01)
    reps = RepDetector(baseline_cutoff_hz=0.3, sample_rate=100.0, hysteresis=1.0)

    events, n = [], 0
    with open(path) as f:
        for line in f:
            clean = pipe.process(line)
            if clean is None:
                continue
            clean["pitch_fused"] = fuse.update(clean)
            ev = reps.update(clean["pitch_fused"], index=n)
            if ev:
                events.append(ev)
            n += 1

    print("Processed %d samples from %s" % (n, path))
    print("dt source: %s" % ("real t_mono_s" if fuse.used_real_dt
                              else "nominal (file has no timestamp)"))
    print("Reps detected: %d" % len(events))
    for ev in events[:10]:
        span = ev["end_idx"] - ev["start_idx"]
        print("  rep %d: samples %d..%d (%d long)"
              % (ev["rep_id"], ev["start_idx"], ev["end_idx"], span))
    print("\nNote: this is a reference detector. Thresholds and the algorithm")
    print("itself are tuning/replacement points for Aiden's real code.")

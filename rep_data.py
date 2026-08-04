"""
rep_data.py -- per-rep data structure, populated live as reps are detected

A Rep captures one repetition:
  rep_id, start_idx, end_idx
  t_start, t_end     seconds, from t_mono_s when the stream carries it
  timestamps[]       per-sample time within the rep
  pitch[]            fused pitch over the rep (deg)
  roll[]             roll over the rep (deg) -- basis for asymmetry
  tof[]              ToF over the rep (mm). EMPTY until a ToF sensor is added
                     to the stream; the field is kept so the schema is stable.
  asymmetry_score    BASELINE metric = mean |roll| over the rep (deg).
                     Replace with the team's real definition when decided.

RepBuilder buffers samples as they stream and finalizes a Rep the instant the
detector reports one -- no separate post-processing pass over the session.

Run directly to see per-rep records + session aggregates:
    python rep_data.py data/raw/sim/session_lift_sim.csv
"""

import math
import sys

from pipeline import Pipeline
from fusion import ComplementaryFilter, RepDetector


def _roll_deg(sample):
    """Side-to-side tilt from the accelerometer; ~0 when the board is level."""
    return math.degrees(math.atan2(sample["accel_y"], sample["accel_z"]))


class RepBuilder:
    """Accumulates streamed samples and emits finished Rep records."""

    def __init__(self, max_buffer=4000):
        self._buf = []                 # rolling buffer of recent samples
        self._max_buffer = max_buffer
        self.reps = []

    def add_sample(self, index, sample):
        t = sample.get("t_mono_s")
        self._buf.append({
            "index": index,
            "t": float(t) if t is not None else None,
            "pitch": sample.get("pitch_fused"),
            "roll": _roll_deg(sample),
            "tof": sample.get("tof"),          # None until ToF exists
        })
        if len(self._buf) > self._max_buffer:  # bound memory for long sessions
            self._buf = self._buf[-self._max_buffer:]

    def finalize_rep(self, event):
        start, end = event["start_idx"], event["end_idx"]
        window = [r for r in self._buf if start <= r["index"] <= end]
        if not window:
            return None                        # rep older than buffer; skip

        roll = [r["roll"] for r in window]
        ts = [r["t"] for r in window if r["t"] is not None]
        rep = {
            "rep_id": event["rep_id"],
            "start_idx": start,
            "end_idx": end,
            "t_start": ts[0] if ts else None,
            "t_end": ts[-1] if ts else None,
            "timestamps": ts,
            "pitch": [r["pitch"] for r in window],
            "roll": roll,
            "tof": [r["tof"] for r in window if r["tof"] is not None],
            "asymmetry_score": round(sum(abs(x) for x in roll) / len(roll), 4),
        }
        self.reps.append(rep)
        return rep


def process_file(path, cutoff_hz=5.0, sample_rate=100.0):
    """Run parse -> filter -> fusion -> rep detection over a file, building
    Rep records live. Returns (reps, n_samples)."""
    pipe = Pipeline(kind="lowpass", cutoff_hz=cutoff_hz, sample_rate=sample_rate)
    fuse = ComplementaryFilter(alpha=0.98, nominal_dt=1.0 / sample_rate)
    det = RepDetector(baseline_cutoff_hz=0.3, sample_rate=sample_rate, hysteresis=1.0)
    builder = RepBuilder()

    n = 0
    with open(path) as f:
        for line in f:
            clean = pipe.process(line)
            if clean is None:
                continue
            clean["pitch_fused"] = fuse.update(clean)
            builder.add_sample(n, clean)
            ev = det.update(clean["pitch_fused"], index=n)
            if ev:
                builder.finalize_rep(ev)
            n += 1
    return builder.reps, n


def session_aggregates(reps):
    """rep count, avg asymmetry, max tilt -- the session-level summary."""
    if not reps:
        return {"rep_count": 0, "avg_asymmetry": None, "max_tilt": None}
    max_tilt = max(max(abs(p) for p in r["pitch"]) for r in reps)
    avg_asym = sum(r["asymmetry_score"] for r in reps) / len(reps)
    return {
        "rep_count": len(reps),
        "avg_asymmetry": round(avg_asym, 4),
        "max_tilt": round(max_tilt, 4),
    }


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/sim/session_lift_sim.csv"
    reps, n = process_file(path)

    print("Processed %d samples from %s\n" % (n, path))
    for r in reps:
        print("rep %d: samples %d..%d | %d samples | asymmetry=%.3f deg | peak pitch=%.2f deg"
              % (r["rep_id"], r["start_idx"], r["end_idx"],
                 len(r["pitch"]), r["asymmetry_score"],
                 max(abs(p) for p in r["pitch"])))

    agg = session_aggregates(reps)
    print("\nSession aggregates:")
    print("  rep_count     = %s" % agg["rep_count"])
    print("  avg_asymmetry = %s deg" % agg["avg_asymmetry"])
    print("  max_tilt      = %s deg" % agg["max_tilt"])

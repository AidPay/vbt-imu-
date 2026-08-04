"""
robust.py -- the ugly cases

Real streams glitch. This layer detects and MAKES VISIBLE:
  - junk / partial lines    counted, skipped
  - spike samples           physically impossible values -> flagged, and the
                            previous good sample is held so the signal doesn't
                            jump before it reaches the filter
  - sensor dropouts         a time gap in t_mono_s -> flagged; reps overlapping
                            the gap are marked incomplete
  - aborted rep             stream ends mid-rep -> recorded, flagged incomplete

DECISION (explicit, not silent): an incomplete rep is FLAGGED and still
partially scored, never dropped quietly. Each rep gains:
    complete : bool
    flags    : list of reasons ("spike", "dropout", "aborted")

Live serial reconnect handling is in reconnecting_serial(): it retries instead
of crashing when the board falls off USB.

Run directly for a clean run and a torture test with injected glitches:
    python robust.py data/raw/sim/session_lift_sim.csv
"""

import sys

from pipeline import Pipeline, DATA_COLUMNS, _split_line
from fusion import ComplementaryFilter, RepDetector
from rep_data import RepBuilder, session_aggregates

# Values beyond these are physically impossible for this sensor config
# (accel range is +/-2 g, gyro +/-245 deg/s), so anything past them is a spike,
# not real motion. Limits are set wider than the valid range so normal samples
# near the rails are never falsely flagged.
PHYSICAL_LIMITS = {
    "accel_x": 4.0, "accel_y": 4.0, "accel_z": 4.0,
    "gyro_x": 300.0, "gyro_y": 300.0, "gyro_z": 300.0,
    "pitch_accel": 100.0,
}


def is_spike(sample):
    return any(abs(sample.get(k, 0.0)) > lim for k, lim in PHYSICAL_LIMITS.items())


def reconnecting_serial(port, baud, retry_s=2.0):
    """Yield lines from the board, reconnecting instead of crashing on drop."""
    import time
    import serial
    while True:
        try:
            ser = serial.Serial(port, baud, timeout=1)
            print("connected to %s" % port)
            try:
                while True:
                    raw = ser.readline().decode("utf-8", errors="ignore")
                    if raw:
                        yield raw
            finally:
                ser.close()
        except serial.SerialException as e:
            print("serial dropped (%s); retrying in %.0fs" % (e, retry_s))
            time.sleep(retry_s)


def robust_process(source, cutoff_hz=5.0, sample_rate=100.0, dropout_factor=3.0):
    """Run the full chain over a source of raw lines with quality tracking.

    Returns (reps, quality_report, n_samples). Every rep has 'complete' and
    'flags'. quality_report summarizes junk lines, spikes, and dropouts.
    """
    nominal_dt = 1.0 / sample_rate
    pipe = Pipeline(kind="lowpass", cutoff_hz=cutoff_hz, sample_rate=sample_rate)
    fuse = ComplementaryFilter(alpha=0.98, nominal_dt=nominal_dt)
    det = RepDetector(baseline_cutoff_hz=0.3, sample_rate=sample_rate, hysteresis=1.0)
    builder = RepBuilder()

    flagged = {}                 # sample index -> set of reasons
    q = {"junk_lines": 0, "spike_samples": 0, "dropouts": 0, "dropout_events": []}
    last_good_line = None
    last_t = None
    n = 0

    for line in source:
        parsed = _split_line(line)
        if parsed is None:
            q["junk_lines"] += 1          # header / partial / garbage
            continue
        ts, vals = parsed

        # dropout: a jump in t_mono_s beyond a few nominal steps
        t = float(ts["t_mono_s"]) if "t_mono_s" in ts else None
        if t is not None and last_t is not None:
            if (t - last_t) > dropout_factor * nominal_dt:
                q["dropouts"] += 1
                q["dropout_events"].append({"index": n, "gap_s": round(t - last_t, 4)})
                flagged.setdefault(n, set()).add("dropout")
        last_t = t

        # spike: hold the last good sample through the filter, flag this index
        raw_sample = dict(zip(DATA_COLUMNS, vals))
        if is_spike(raw_sample):
            q["spike_samples"] += 1
            flagged.setdefault(n, set()).add("spike")
            if last_good_line is None:
                continue                  # nothing good to hold yet
            clean = pipe.process(last_good_line)
        else:
            clean = pipe.process(line)
            last_good_line = line
        if clean is None:
            continue

        clean["pitch_fused"] = fuse.update(clean)
        builder.add_sample(n, clean)
        ev = det.update(clean["pitch_fused"], index=n)
        if ev:
            rep = builder.finalize_rep(ev)
            reasons = set()
            for i in range(rep["start_idx"], rep["end_idx"] + 1):
                reasons |= flagged.get(i, set())
            rep["complete"] = len(reasons) == 0
            rep["flags"] = sorted(reasons)
        n += 1

    # aborted rep: stream ended while the detector was mid-rep
    if det.armed and det.rep_start is not None:
        builder.reps.append({
            "rep_id": len(builder.reps) + 1,
            "start_idx": det.rep_start, "end_idx": n - 1,
            "t_start": None, "t_end": None, "timestamps": [],
            "pitch": [], "roll": [], "tof": [],
            "asymmetry_score": None,
            "complete": False, "flags": ["aborted"],
        })

    q["incomplete_reps"] = [r["rep_id"] for r in builder.reps if not r.get("complete", True)]
    return builder.reps, q, n


def robust_process_file(path, **kw):
    with open(path) as f:
        return robust_process(f, **kw)


def _inject_glitches(lines):
    """Make a torture copy: spike some samples, insert junk lines."""
    out = []
    data_seen = 0
    for line in lines:
        parsed = _split_line(line)
        if parsed is not None:
            data_seen += 1
            if data_seen % 250 == 0:                      # spike every 250th
                parts = line.strip().split(",")
                parts[0] = "50.0"                         # 50 g -> impossible
                line = ",".join(parts) + "\n"
            if data_seen % 400 == 0:                      # drop in a junk line
                out.append("garbage,,partial\n")
        out.append(line)
    return out


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/sim/session_lift_sim.csv"

    reps, q, n = robust_process_file(path)
    print("CLEAN RUN on %s" % path)
    print("  samples=%d  junk=%d  spikes=%d  dropouts=%d"
          % (n, q["junk_lines"], q["spike_samples"], q["dropouts"]))
    print("  reps=%d  incomplete=%s" % (len(reps), q["incomplete_reps"]))
    print("  aggregates=%s" % session_aggregates([r for r in reps if r.get("complete", True)]))

    with open(path) as f:
        glitched = _inject_glitches(list(f))
    reps2, q2, n2 = robust_process(glitched)
    print("\nTORTURE RUN (injected spikes + junk lines)")
    print("  samples=%d  junk=%d  spikes=%d  dropouts=%d"
          % (n2, q2["junk_lines"], q2["spike_samples"], q2["dropouts"]))
    print("  reps=%d  incomplete=%s" % (len(reps2), q2["incomplete_reps"]))
    for r in reps2:
        print("    rep %d: complete=%s flags=%s"
              % (r["rep_id"], r.get("complete"), r.get("flags")))

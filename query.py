"""
query.py -- clean query interface over saved sessions

The single place testing and the demo ask questions of a session:

    s = Session.load("sessions/session_....json")   # or Session.latest()
    s.rep(7)                      -> one rep by id
    s.stats()                     -> {rep_count, avg_asymmetry, max_tilt}
    s.reps_above(5.0)             -> reps with asymmetry above 5 deg
    s.reps_above(30, "peak_pitch")
    s.sorted_by("asymmetry_score")-> worst reps first
    len(s)                        -> number of reps
    for rep in s: ...

Per-rep metrics available to reps_above / sorted_by: asymmetry_score,
peak_pitch, duration_samples, duration_s.

Run directly for a demo (processes+saves a sim file first if no session exists):
    python query.py
"""

import glob
import os
import sys

from persistence import load_session, process_and_save


def _peak_pitch(rep):
    return max((abs(p) for p in rep["pitch"]), default=0.0)


def _duration_samples(rep):
    return rep["end_idx"] - rep["start_idx"]


def _duration_s(rep):
    if rep.get("t_start") is not None and rep.get("t_end") is not None:
        return rep["t_end"] - rep["t_start"]
    return None


METRICS = {
    "asymmetry_score": lambda r: r["asymmetry_score"],
    "peak_pitch": _peak_pitch,
    "duration_samples": _duration_samples,
    "duration_s": _duration_s,
}


class Session:
    def __init__(self, record):
        self._record = record
        self.reps = record["reps"]

    @classmethod
    def load(cls, path):
        return cls(load_session(path))

    @classmethod
    def latest(cls, out_dir="sessions"):
        files = sorted(glob.glob(os.path.join(out_dir, "*.json")))
        if not files:
            raise FileNotFoundError("no sessions found in %s/" % out_dir)
        return cls.load(files[-1])

    @property
    def id(self):
        return self._record.get("session_id")

    def stats(self):
        return self._record.get("aggregates", {})

    def rep(self, rep_id):
        for r in self.reps:
            if r["rep_id"] == rep_id:
                return r
        return None

    def metric(self, rep, name):
        if name not in METRICS:
            raise KeyError("unknown metric %r (have: %s)"
                           % (name, ", ".join(METRICS)))
        return METRICS[name](rep)

    def reps_above(self, threshold, metric="asymmetry_score"):
        fn = METRICS[metric]
        return [r for r in self.reps if fn(r) is not None and fn(r) > threshold]

    def reps_where(self, predicate):
        return [r for r in self.reps if predicate(r)]

    def sorted_by(self, metric, descending=True):
        fn = METRICS[metric]
        return sorted((r for r in self.reps if fn(r) is not None),
                      key=fn, reverse=descending)

    def __len__(self):
        return len(self.reps)

    def __iter__(self):
        return iter(self.reps)


if __name__ == "__main__":
    try:
        s = Session.latest()
    except FileNotFoundError:
        path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/sim/session_lift_sim.csv"
        process_and_save(path)
        s = Session.latest()

    print("Session: %s  (%d reps)\n" % (s.id, len(s)))
    print("s.stats() ->", s.stats())

    r = s.rep(2)
    if r:
        print("\ns.rep(2) -> samples %d..%d, asymmetry=%.3f, peak_pitch=%.2f deg"
              % (r["start_idx"], r["end_idx"],
                 r["asymmetry_score"], s.metric(r, "peak_pitch")))

    avg = s.stats().get("avg_asymmetry") or 0.0
    hits = s.reps_above(avg, "asymmetry_score")
    print("\ns.reps_above(%.3f) -> reps above average asymmetry: %s"
          % (avg, [r["rep_id"] for r in hits]))

    worst = s.sorted_by("asymmetry_score")[:3]
    print("s.sorted_by('asymmetry_score')[:3] -> %s"
          % [(r["rep_id"], r["asymmetry_score"]) for r in worst])

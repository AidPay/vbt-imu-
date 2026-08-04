"""
persistence.py -- save/load full sessions so any rep can be replayed offline

Format: one JSON file per session under sessions/. JSON (not SQLite) because
sessions are few and each rep holds variable-length arrays that map awkwardly
to relational columns; loading a session and filtering in Python is simple and
fast here. If the project later accumulates hundreds of sessions and needs
cross-session queries, promote to SQLite with the same schema (one row per rep,
arrays stored as JSON columns).

A saved session records not just the reps but HOW it was processed (filter
cutoff, sample rate), so a stored session reproduces exactly.

Run directly to process a file, save it, reload it, and replay a rep:
    python persistence.py data/raw/sim/session_lift_sim.csv
"""

import json
import os
import sys
from datetime import datetime

from rep_data import process_file, session_aggregates

SCHEMA_VERSION = "1.0"


def save_session(reps, meta, out_dir="sessions", session_id=None):
    """Write a session (reps + aggregates + processing metadata) to JSON.
    Returns the file path."""
    os.makedirs(out_dir, exist_ok=True)
    if session_id is None:
        session_id = datetime.now().strftime("session_%Y-%m-%d_%H-%M-%S")

    record = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "created": datetime.now().isoformat(timespec="seconds"),
        "source_file": meta.get("source_file"),
        "n_samples": meta.get("n_samples"),
        "processing": meta.get("processing"),
        "aggregates": session_aggregates(reps),
        "reps": reps,
    }

    path = os.path.join(out_dir, session_id + ".json")
    with open(path, "w") as f:
        json.dump(record, f, indent=2)
    return path


def load_session(path):
    """Load a saved session back into a dict."""
    with open(path) as f:
        return json.load(f)


def get_rep(session, rep_id):
    """Pull a single rep out of a loaded session by id, or None."""
    for rep in session["reps"]:
        if rep["rep_id"] == rep_id:
            return rep
    return None


def process_and_save(input_path, cutoff_hz=5.0, sample_rate=100.0, out_dir="sessions"):
    """Full chain: process a raw/replayed file into reps and persist it."""
    reps, n = process_file(input_path, cutoff_hz=cutoff_hz, sample_rate=sample_rate)
    meta = {
        "source_file": input_path,
        "n_samples": n,
        "processing": {"filter": "lowpass",
                       "cutoff_hz": cutoff_hz,
                       "sample_rate": sample_rate},
    }
    return save_session(reps, meta, out_dir)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/raw/sim/session_lift_sim.csv"

    saved_path = process_and_save(path)
    print("Saved session -> %s" % saved_path)

    # Reload from disk and prove any rep is fully recoverable.
    session = load_session(saved_path)
    print("\nReloaded session %s" % session["session_id"])
    print("  aggregates: %s" % session["aggregates"])
    print("  reps stored: %d" % len(session["reps"]))

    rep = get_rep(session, 2)
    if rep:
        print("\nReplaying rep 2 from disk:")
        print("  samples %d..%d, %d pitch points"
              % (rep["start_idx"], rep["end_idx"], len(rep["pitch"])))
        print("  asymmetry=%.3f deg, first 3 pitch values=%s"
              % (rep["asymmetry_score"], [round(p, 3) for p in rep["pitch"][:3]]))

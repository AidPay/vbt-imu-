# vbt-imu

Real-time IMU pipeline for velocity-based training: raw IMU samples come off the
board, get parsed, filtered, and fused into a pitch estimate; reps are detected
live; each rep is scored and stored so any session can be replayed and queried
offline without the hardware.

Sensor: Seeed XIAO nRF52840 Sense (LSM6DS3TR-C accelerometer + gyroscope).

## Data flow

```
board --CSV @9600--> logger --> parser --> filter --> fusion --> rep detect
                       |                                              |
                  timestamped                                    per-rep record
                   .csv log                                          |
                                                                 persistence (JSON)
                                                                      |
                                                                  query interface
```

The same code runs on a live serial feed or a replayed log file, and produces
identical output either way (verified by `pipeline.py`). That equivalence is
what makes offline testing trustworthy.

## Modules

| File | Purpose |
|------|---------|
| `SERIAL_FORMAT.md` | Proposed binary wire format spec (see Open items). |
| `data_format.md` | Current raw CSV format the firmware actually streams. |
| `parser.py` | Read a session CSV into labeled float arrays; range-validate. |
| `logger.py` | Capture a session (live serial or replay) to a timestamped CSV. |
| `filters.py` | Configurable low-pass / moving-average filter; cutoff in Hz. |
| `pipeline.py` | Streaming parse -> filter, one sample at a time; equivalence test. |
| `fusion.py` | Reference complementary filter + rep detector (real `dt`). |
| `rep_data.py` | Per-rep data structure, built live; session aggregates. |
| `persistence.py` | Save/load full sessions as JSON; replay any rep. |
| `query.py` | Clean interface: `rep(n)`, `stats()`, `reps_above(x)`. |
| `robust.py` | Spike / dropout / junk handling; incomplete-rep flagging; reconnect. |
| `latency.py` | Per-stage timing vs the 100 ms and 10 ms budgets. |

## Quick start

```bash
pip install numpy            # pyserial too, only for live capture
python pipeline.py data/raw/sim/session_lift_sim.csv   # prove live==replay
python query.py                                        # end-to-end demo
```

## Running it end to end (device -> output)

**Live capture**
1. Flash the board so it streams the CSV columns below at 9600 baud, ~100 Hz.
2. `pip install numpy pyserial`
3. Record a session: `python logger.py --port COM3 --baud 9600`
   (find your COM port in Device Manager). Writes `data/raw/real/session_*.csv`.
4. Process and store it: `python persistence.py data/raw/real/session_*.csv`
   Writes `sessions/session_*.json`.
5. Query it: `python query.py`

**Offline / replay (no hardware)**
- `python logger.py --replay data/raw/sim/session_lift_sim.csv --out data/raw/test`
- Then steps 4-5 above on the resulting file.

## Data dictionary

### Raw input columns (mirrors `data_format.md`)

| Column | Unit | Range | Meaning |
|--------|------|-------|---------|
| accel_x | g | +/-2 | lateral acceleration |
| accel_y | g | +/-2 | forward acceleration |
| accel_z | g | +/-2 | vertical acceleration |
| gyro_x | deg/s | +/-245 | roll rate |
| gyro_y | deg/s | +/-245 | pitch rate |
| gyro_z | deg/s | +/-245 | yaw rate |
| pitch_accel | deg | -90..90 | pitch from accelerometer only |

A logged CSV additionally prepends `t_iso` (ISO 8601 wall clock) and
`t_mono_s` (seconds from a monotonic clock; the value fusion uses for `dt`).

### Rep record (produced live, stored in session JSON)

| Field | Type | Unit | Notes |
|-------|------|------|-------|
| rep_id | int | - | 1-based, in detection order |
| start_idx / end_idx | int | sample index | bounds of the rep in the session |
| t_start / t_end | float or null | s | monotonic; null if input had no timestamp |
| timestamps | float[] | s | per-sample time within the rep |
| pitch | float[] | deg | fused pitch, ~ -90..90 |
| roll | float[] | deg | accel-derived roll, basis for asymmetry |
| tof | float[] | mm | empty until a ToF sensor is added to the stream |
| asymmetry_score | float or null | deg | baseline = mean absolute roll over the rep |
| complete | bool | - | false if the rep overlapped a glitch |
| flags | string[] | - | subset of {spike, dropout, aborted} |

### Session JSON

| Field | Type | Notes |
|-------|------|-------|
| schema_version | str | currently "1.0" |
| session_id | str | e.g. session_2026-08-04_16-45-52 |
| created | str | ISO 8601 |
| source_file | str | input the session was built from |
| n_samples | int | samples processed |
| processing | object | filter kind, cutoff_hz, sample_rate used |
| aggregates | object | rep_count, avg_asymmetry (deg), max_tilt (deg) |
| reps | Rep[] | the full list of rep records above |

## Design decisions

- **Incomplete reps are flagged, not dropped.** A rep touched by a spike,
  dropout, or an aborted stream is kept, partially scored, and marked
  `complete: false` with a `flags` list. Nothing fails silently.
- **Fusion `dt` is real, not assumed.** The complementary filter integrates
  using actual elapsed `t_mono_s` between samples, falling back to nominal
  only when the input carries no timestamp.
- **Persistence is JSON, not SQLite,** because sessions are few and reps hold
  variable-length arrays. Promote to SQLite (same schema) if session count
  grows into the hundreds.

## Open items

- **`SERIAL_FORMAT.md` vs `data_format.md`.** `SERIAL_FORMAT.md` describes a
  proposed *binary* wire format (with sample counter, ToF, checksum); the
  pipeline currently consumes the *CSV* format in `data_format.md`. These need
  reconciling before either is frozen.
- **ToF is not in the stream yet.** The schema reserves `tof[]` for it, but no
  ToF data exists. Confirm whether/when it's added.
- **`fusion.py` is a reference implementation.** Aiden's real complementary
  filter and rep detector should replace the insides of `ComplementaryFilter`
  and `RepDetector`; the `.update(...)` interface stays the same.
- **Asymmetry score is a baseline** (mean roll). Replace with the team's real
  definition once decided.
- **Dropout detection needs timestamps.** It activates on logged sessions that
  carry `t_mono_s`; it is inert on the raw sim files.
```

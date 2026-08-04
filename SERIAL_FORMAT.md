# Serial Frame Format — v1.0 (FROZEN)

**Status:** Frozen. Do not change any offset, type, or scaling without bumping the version number and updating every downstream consumer (parser, logger, fusion, data dictionary).
**Sensor:** LSM6DS3TR-C (accel + gyro) + ToF distance sensor.

---

## 1. Transport

- **Binary frame**, fixed length, **little-endian**.
- **One frame = one sample.**
- **Baud:** `921600` (fill in your real value). Rule of thumb: `baud ≥ frame_bytes × 10 × sample_rate_Hz`. At 21 bytes and 833 Hz that's ~175 kbps, so 921600 is comfortable.
- Chosen over CSV-over-wire because a fixed-length frame with sync bytes + checksum makes partial frames and spike bytes detectable, which the "handle the ugly cases" step depends on. (CSV is still used *on disk* — see §5.)

## 2. Frame layout (21 bytes total)

| Offset | Field            | Type       | Bytes | Notes                                                        |
|-------:|------------------|------------|------:|-------------------------------------------------------------|
| 0      | `header`         | `uint8[2]` | 2     | Sync marker `0xAA 0x55`. Frame starts here.                 |
| 2      | `sample_counter` | `uint32`   | 4     | +1 per sample, wraps at 2³². Non-consecutive value = dropped sample(s). |
| 6      | `accel_x`        | `int16`    | 2     | Raw LSM6DS3TR-C counts.                                     |
| 8      | `accel_y`        | `int16`    | 2     | Raw counts.                                                |
| 10     | `accel_z`        | `int16`    | 2     | Raw counts.                                                |
| 12     | `gyro_x`         | `int16`    | 2     | Raw counts.                                                |
| 14     | `gyro_y`         | `int16`    | 2     | Raw counts.                                                |
| 16     | `gyro_z`         | `int16`    | 2     | Raw counts.                                                |
| 18     | `tof`            | `uint16`   | 2     | Distance in **mm**.                                        |
| 20     | `checksum`       | `uint8`    | 1     | XOR of bytes `[0..19]` (all bytes before this one).        |

## 3. Scaling — raw counts → physical units

Freeze the full-scale (FS) setting on the sensor and record it here. Do **not** let firmware and parser disagree on FS.

**Accelerometer (chosen FS = ±4 g):**

`accel_g = raw × 0.122 / 1000`

| FS     | Sensitivity (mg/LSB) |
|--------|----------------------|
| ±2 g   | 0.061                |
| **±4 g** | **0.122**          |
| ±8 g   | 0.244                |
| ±16 g  | 0.488                |

**Gyroscope (chosen FS = ±500 °/s):**

`gyro_dps = raw × 17.5 / 1000`

| FS        | Sensitivity (mdps/LSB) |
|-----------|------------------------|
| ±125 °/s  | 4.375                  |
| ±250 °/s  | 8.75                   |
| **±500 °/s** | **17.5**            |
| ±1000 °/s | 35.0                   |
| ±2000 °/s | 70.0                   |

**ToF:** already in mm, no scaling.

## 4. Parse / resync rules

1. Scan the byte stream for the sync pair `0xAA 0x55`.
2. Read the next 19 bytes (21 total).
3. Compute XOR of bytes `[0..19]`; compare to byte `20`. **Reject the frame if it mismatches.**
4. On mismatch or lost sync: discard **one** byte and resync from step 1 (don't discard the whole buffer — the real frame may start mid-buffer).
5. If `sample_counter` is not previous+1, record a **dropped-sample gap** of `(new - prev - 1)` rather than silently continuing.

## 5. On-disk CSV (what the session logger writes)

The wire is binary; the log is CSV. The logger decodes each frame and writes one row. Header row (frozen):

```
timestamp_iso,t_mono_s,sample_counter,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,tof_mm
```

- `timestamp_iso` — wall-clock ISO 8601 for humans.
- `t_mono_s` — monotonic seconds from a steady clock, used for the fusion `dt`. **Fusion integration uses actual elapsed `t_mono_s` between samples, never an assumed fixed dt.**
- Remaining fields are the scaled values from §3.

## 6. Change log

- **v1.0** — initial frozen format.

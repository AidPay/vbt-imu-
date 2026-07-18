# IMU Raw Data Format

**Source:** Seeed XIAO nRF52840 Sense — LSM6DS3TR-C  
**Baud rate:** 9600  
**Sample rate:** ~100 Hz (10ms delay)

## Columns (CSV)
| Column      | Unit  | Range     | Description           |
|-------------|-------|-----------|-----------------------|
| accel_x     | g     | ±2g       | Lateral acceleration  |
| accel_y     | g     | ±2g       | Forward acceleration  |
| accel_z     | g     | ±2g       | Vertical acceleration |
| gyro_x      | °/s   | ±245°/s   | Roll rate             |
| gyro_y      | °/s   | ±245°/s   | Pitch rate            |
| gyro_z      | °/s   | ±245°/s   | Yaw rate              |
| pitch_accel | °     | -90–90°   | Pitch from accel only |

## Notes
- Row 1 is always the header
- Board flat: accel_z ≈ 1.0, accel_x/y ≈ 0.0, pitch_accel ≈ 0.0
- Simulated files are in /data/raw/sim/ — real board files go in /data/raw/real/

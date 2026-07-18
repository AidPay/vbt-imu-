# Bench Test Protocol — Pitch Validation
**For:** Katie  
**Goal:** Verify pitch_accel column is accurate at known tilt angles

## Files to test (in /data/raw/sim/ until real board data arrives)
- session_flat.csv → expected pitch ≈ 0°
- session_15deg.csv → expected pitch ≈ 15°
- session_30deg.csv → expected pitch ≈ 30°
- session_45deg.csv → expected pitch ≈ 45°
- session_motion.csv → pitch should spike badly here (shows the problem)

## What to do for each static file
1. Open the .csv
2. Skip first 5 rows
3. Calculate average of the pitch_accel column
4. Record the error: |average - expected angle|

## Pass/Fail
- Error < 3° = PASS
- Error 3–7° = FLAG
- Error > 7° = FAIL — tell Aiden

## Results table (fill this in)
| File               | Expected | Avg pitch_accel | Error |
|--------------------|----------|-----------------|-------|
| session_flat.csv   | 0°       |                 |       |
| session_15deg.csv  | 15°      |                 |       |
| session_30deg.csv  | 30°      |                 |       |
| session_45deg.csv  | 45°      |                 |       |

## Motion test
- Open session_motion.csv
- Note the max and min pitch_accel values
- This shows how badly pure-accel pitch breaks under movement

## Return results
Commit your filled-in table as bench_test_results_katie.md

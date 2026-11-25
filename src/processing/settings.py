"""Constants of the v2 processing pipeline and the quality thresholds."""

# Common time grid for both sensors.
GRID_HZ = 100.0

# Clock fit: one minimum-delay point per window; fewer windows -> offset only.
CLOCK_WINDOW_S = 2.0
CLOCK_MIN_WINDOWS = 10
CLOCK_MAX_FIT_WINDOWS = 1500  # Theil-Sen is O(n^2); thin longer sessions

# A device-time step larger than this is a gap: no gyro integration across it
# and no interpolation across it on the grid.
GAP_THRESHOLD_S = 0.050

# Rest window for the gyro bias.
REST_WINDOW_LENGTHS_S = (2.0, 2.5, 3.0)
REST_WINDOW_STEP_S = 0.1
REST_MIN_SAMPLE_FRACTION = 0.8
ZERO_POSE_SEARCH_HALF_WIDTH_S = 3.0  # search [zero_pose - 3 s, zero_pose + 3 s]
NO_ZERO_POSE_SEARCH_S = 30.0  # fallback: first 30 s of the session
NO_ZERO_POSE_WINDOW_S = 2.0
GRAVITY_MS2 = 9.81
ACC_REST_TOLERANCE = 0.2  # |mean acc| within 20 % of g during rest
# A "rest" window noisier than this is motion, not rest: no bias is removed.
REST_MAX_GYRO_STD = 0.05  # rad/s, mean per-axis std

# Default AHRS filter for v2 processing (same as v1: "ekf").
DEFAULT_FILTER = "ekf"

# Quality thresholds: quality_ok is false when any is exceeded.
QUALITY_MAX_LOSS_PCT = 2.0
QUALITY_MIN_OVERLAP_RATIO = 0.90
QUALITY_MAX_CLOCK_RESIDUAL_MS = 5.0

# Processing trigger.
PROCESSING_MAX_ATTEMPTS = 5
PROCESSING_LEASE_S = 35 * 60  # > Cloud Tasks dispatch deadline (30 min)

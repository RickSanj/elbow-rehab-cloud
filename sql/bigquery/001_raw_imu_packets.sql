-- Raw IMU packets, one row per BLE packet, stored exactly as received.
-- Append-only. Replace PROJECT_ID.DATASET before running (see docs/MIGRATIONS.md).

CREATE TABLE IF NOT EXISTS `PROJECT_ID.DATASET.raw_imu_packets` (
  user_id        STRING    NOT NULL,
  session_id     STRING    NOT NULL,
  role           STRING    NOT NULL,  -- 'A' upper arm, 'B' forearm
  seq            INT64     NOT NULL,  -- uint32 on the board, restarts at 0 on reboot
  device_ts_us   INT64     NOT NULL,  -- board clock
  phone_rx_s     FLOAT64   NOT NULL,  -- phone CLOCK_MONOTONIC at receive
  ax             FLOAT64,
  ay             FLOAT64,
  az             FLOAT64,
  gx             FLOAT64,
  gy             FLOAT64,
  gz             FLOAT64,
  batch_id       STRING    NOT NULL,
  schema_version INT64     NOT NULL,
  ingested_at    TIMESTAMP NOT NULL
)
PARTITION BY DATE(ingested_at)
CLUSTER BY user_id, session_id, role
OPTIONS (description = 'v2 raw IMU packets (append-only, unmodified sensor values)');

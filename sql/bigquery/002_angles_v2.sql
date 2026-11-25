-- Processed elbow angles on the common 100 Hz grid, per session.
-- Written per session by the processing job (append new rows, then delete the
-- session's older rows). Replace PROJECT_ID.DATASET before running.

CREATE TABLE IF NOT EXISTS `PROJECT_ID.DATASET.angles_v2` (
  session_id        STRING    NOT NULL,
  t_s               FLOAT64   NOT NULL,  -- session time: phone time - SessionStart.uptime_s
  fe_deg            FLOAT64,             -- flexion/extension, NULL when not valid
  ps_deg            FLOAT64,             -- pronation/supination, NULL when not valid
  valid             BOOL      NOT NULL,  -- false inside a gap of either sensor
  algorithm_version STRING    NOT NULL,
  computed_at       TIMESTAMP NOT NULL
)
PARTITION BY DATE(computed_at)
CLUSTER BY session_id
OPTIONS (description = 'v2 processed elbow angles (one run per session)');

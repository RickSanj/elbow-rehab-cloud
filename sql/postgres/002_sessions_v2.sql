-- 002: v2 session model (sessions, events, reports).
--
-- Additive only: v1 tables (sessions, reports, ...) are not altered.
-- Run once:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/postgres/002_sessions_v2.sql

BEGIN;

CREATE TABLE IF NOT EXISTS sessions_v2 (
    session_id            UUID PRIMARY KEY,
    patient_id            TEXT NOT NULL REFERENCES patients (patient_id),
    wall_anchor           TIMESTAMPTZ NOT NULL,       -- SessionStart.wall_iso
    uptime_anchor_s       DOUBLE PRECISION NOT NULL,  -- SessionStart.uptime_s
    sensors               JSONB NOT NULL,
    app_version           TEXT,
    status                TEXT NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'stopped', 'processing', 'done', 'failed')),
    stopped_uptime_s      DOUBLE PRECISION,
    app_stats             JSONB,
    processing_attempts   INT NOT NULL DEFAULT 0,
    processing_error      TEXT,
    processing_enqueued_at TIMESTAMPTZ,  -- set once the Cloud Task was created
    processing_started_at  TIMESTAMPTZ,  -- lease for the running processing attempt
    algorithm_version     TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sessions_v2_patient_idx ON sessions_v2 (patient_id, created_at DESC);

CREATE TABLE IF NOT EXISTS session_events_v2 (
    session_id   UUID NOT NULL REFERENCES sessions_v2 (session_id),
    type         TEXT NOT NULL CHECK (type IN ('zero_pose', 'stop')),
    uptime_s     DOUBLE PRECISION NOT NULL,
    wall_iso     TIMESTAMPTZ NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, type, uptime_s)
);

CREATE TABLE IF NOT EXISTS reports_v2 (
    session_id        UUID PRIMARY KEY REFERENCES sessions_v2 (session_id),
    duration_s        DOUBLE PRECISION,
    max_flexion       DOUBLE PRECISION,
    max_extension     DOUBLE PRECISION,
    max_pronation     DOUBLE PRECISION,
    max_supination    DOUBLE PRECISION,
    rep_count         INT,
    smoothness        DOUBLE PRECISION,
    pain_level        INT CHECK (pain_level BETWEEN 0 AND 10),
    quality           JSONB,
    quality_ok        BOOLEAN,
    algorithm_version TEXT,
    computed_at       TIMESTAMPTZ
);

COMMIT;

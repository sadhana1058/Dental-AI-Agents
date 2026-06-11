-- SQLite-compatible schema.
-- Postgres equivalents noted in comments:
--   INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY (or BIGSERIAL)
--   TEXT (dates/timestamps)           → TIMESTAMPTZ / DATE
--   TEXT (JSON columns)               → JSONB
--   INTEGER (booleans)                → BOOLEAN

CREATE TABLE IF NOT EXISTS patients (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL,
    phone     TEXT    NOT NULL UNIQUE,   -- E.164 format: +1XXXXXXXXXX
    email     TEXT,
    dob       TEXT,                      -- ISO date YYYY-MM-DD
    notes     TEXT,
    created_at TEXT   NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS appointments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id       INTEGER NOT NULL REFERENCES patients(id),
    provider         TEXT    NOT NULL,
    start_time       TEXT    NOT NULL,   -- ISO datetime, UTC: 2026-06-15T10:00:00Z
    duration         INTEGER NOT NULL,   -- minutes
    type             TEXT    NOT NULL,   -- cleaning|checkup|filling|crown|extraction
    status           TEXT    NOT NULL DEFAULT 'scheduled',
                                         -- scheduled|completed|cancelled|no_show
    calendar_event_id TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Append-only audit log — never UPDATE, only INSERT here.
-- Current state = latest row per appointment_id.
CREATE TABLE IF NOT EXISTS appointment_changes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id INTEGER NOT NULL REFERENCES appointments(id),
    changed_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    change_type    TEXT    NOT NULL,   -- create|reschedule|cancel|complete|no_show
    old_value      TEXT,               -- JSON snapshot of changed fields
    new_value      TEXT                -- JSON snapshot after change
);

-- Key/value store for practice configuration. One row per setting key.
-- Postgres: consider a single JSONB row instead.
CREATE TABLE IF NOT EXISTS practice_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL    -- JSON
);

CREATE TABLE IF NOT EXISTS call_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER REFERENCES patients(id),  -- NULL if caller unrecognised
    channel    TEXT    NOT NULL,                 -- voice|whatsapp
    transcript TEXT,
    outcome    TEXT,   -- rescheduled|cancelled|faq_answered|escalated|no_action
    escalated  INTEGER NOT NULL DEFAULT 0,       -- 0/1 boolean
    timestamp  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Indexes for the hot query paths
CREATE INDEX IF NOT EXISTS idx_appointments_patient    ON appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_appointments_start_time ON appointments(start_time);
CREATE INDEX IF NOT EXISTS idx_appointment_changes_appt ON appointment_changes(appointment_id);
CREATE INDEX IF NOT EXISTS idx_call_logs_patient       ON call_logs(patient_id);

-- Seed data for local dev / testing.
-- All dates relative to 2026-06-11 (today).
-- Phone numbers are fake US numbers in E.164 format.
-- No real PHI — safe for development.

-- ── Patients ──────────────────────────────────────────────────────────────────

INSERT INTO patients (id, name, phone, email, dob, notes) VALUES
    (1, 'John Smith',    '+15550001001', 'john.smith@example.com',  '1985-03-22', NULL),
    (2, 'Maria Garcia',  '+15550001002', 'maria.g@example.com',     '1990-07-14', 'Prefers afternoon slots'),
    (3, 'David Chen',    '+15550001003', 'dchen@example.com',       '1978-11-05', 'Anxiety — needs extra time'),
    (4, 'Sarah Johnson', '+15550001004', 'sjohnson@example.com',    '2001-01-30', NULL),
    (5, 'Emily Brown',   '+15550001005', 'emily.brown@example.com', '1965-09-19', 'On blood thinners — note for Dr. Kim');

-- ── Appointments ──────────────────────────────────────────────────────────────
-- status: scheduled | completed | cancelled | no_show
-- calendar_event_id: placeholder Google Calendar event IDs (gcal_*)

INSERT INTO appointments
    (id, patient_id, provider,    start_time,              duration, type,       status,      calendar_event_id) VALUES
-- Future appointments (upcoming)
    (1,  1,          'Dr. Patel', '2026-06-15T10:00:00Z',  60,       'cleaning', 'scheduled', 'gcal_evt_001'),
    (2,  2,          'Dr. Kim',   '2026-06-16T14:00:00Z',  60,       'filling',  'scheduled', 'gcal_evt_002'),
    (3,  3,          'Dr. Patel', '2026-06-18T09:00:00Z',  30,       'checkup',  'scheduled', 'gcal_evt_003'),
    (4,  4,          'Dr. Kim',   '2026-06-20T11:00:00Z',  45,       'extraction','scheduled','gcal_evt_004'),
-- Past appointments
    (5,  5,          'Dr. Kim',   '2026-06-05T10:00:00Z',  30,       'checkup',  'completed', 'gcal_evt_005'),
    (6,  1,          'Dr. Patel', '2026-05-20T09:00:00Z',  60,       'cleaning', 'completed', 'gcal_evt_006'),
-- Cancelled (David Chen rescheduled; original slot preserved in audit log)
    (7,  3,          'Dr. Patel', '2026-06-10T14:00:00Z',  30,       'checkup',  'cancelled', 'gcal_evt_007'),
-- No-show
    (8,  4,          'Dr. Kim',   '2026-06-03T09:00:00Z',  45,       'extraction','no_show',  'gcal_evt_008');

-- ── Appointment changes (audit log) ───────────────────────────────────────────

-- Appt #7 was created, then David rescheduled to appt #3, so #7 was cancelled.
INSERT INTO appointment_changes
    (appointment_id, changed_at,            change_type,  old_value, new_value) VALUES
    (7,  '2026-05-28T16:00:00Z', 'create',     NULL,
         '{"start_time":"2026-06-10T14:00:00Z","status":"scheduled"}'),
    (7,  '2026-06-08T10:30:00Z', 'reschedule',
         '{"start_time":"2026-06-10T14:00:00Z","status":"scheduled"}',
         '{"start_time":"2026-06-18T09:00:00Z","status":"cancelled","note":"patient called to reschedule"}'),
    (3,  '2026-06-08T10:31:00Z', 'create',     NULL,
         '{"start_time":"2026-06-18T09:00:00Z","status":"scheduled"}'),
-- Sarah no-showed appt #8; logged after the fact.
    (8,  '2026-06-03T17:00:00Z', 'no_show',
         '{"status":"scheduled"}',
         '{"status":"no_show","note":"patient did not show, called — no answer"}');

-- ── Practice settings ─────────────────────────────────────────────────────────

INSERT INTO practice_settings (key, value) VALUES

('hours', '{
  "monday":    {"open": "08:00", "close": "17:00"},
  "tuesday":   {"open": "08:00", "close": "17:00"},
  "wednesday": {"open": "08:00", "close": "17:00"},
  "thursday":  {"open": "08:00", "close": "17:00"},
  "friday":    {"open": "08:00", "close": "17:00"},
  "saturday":  {"open": "09:00", "close": "13:00"},
  "sunday":    null
}'),

('appointment_types', '[
  {"type": "cleaning",   "duration": 60, "label": "Teeth Cleaning"},
  {"type": "checkup",    "duration": 30, "label": "Routine Checkup"},
  {"type": "filling",    "duration": 60, "label": "Cavity Filling"},
  {"type": "crown",      "duration": 90, "label": "Crown Placement"},
  {"type": "extraction", "duration": 45, "label": "Tooth Extraction"},
  {"type": "xray",       "duration": 20, "label": "X-Ray"}
]'),

('providers', '[
  {"id": "patel", "name": "Dr. Patel", "title": "DDS"},
  {"id": "kim",   "name": "Dr. Kim",   "title": "DMD"}
]'),

('buffer_rules', '{
  "between_appointments_min": 15,
  "max_appointments_per_day_per_provider": 10,
  "scheduling_horizon_days": 60,
  "reminder_hours_before": [48, 2]
}');

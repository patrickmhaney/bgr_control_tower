-- The governance tool's database schema (its data/requirements.db, 2026-10-27), kept so
-- the converter's coverage test (tests/unit/test_convert.py) outlives the tool.
CREATE TABLE clients (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    slots       INTEGER NOT NULL DEFAULT 4,
    sources     TEXT NOT NULL DEFAULT '[]',     -- JSON array offered on every metric
    is_demo     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
, target_slug TEXT NOT NULL DEFAULT '');
CREATE TABLE dashboards (
    id         INTEGER PRIMARY KEY,
    client_id  INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    code       TEXT NOT NULL,
    name       TEXT NOT NULL DEFAULT '',
    position   INTEGER NOT NULL, audience TEXT NOT NULL DEFAULT '', decisions TEXT NOT NULL DEFAULT '', cadence TEXT NOT NULL DEFAULT '', access TEXT NOT NULL DEFAULT '',
    UNIQUE (client_id, code)
);
CREATE TABLE people (
    id         INTEGER PRIMARY KEY,
    client_id  INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    role       TEXT NOT NULL DEFAULT '',
    email      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
, department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL);
CREATE TABLE requirements (
    id               INTEGER PRIMARY KEY,
    dashboard_id     INTEGER NOT NULL REFERENCES dashboards(id) ON DELETE CASCADE,
    slot             INTEGER NOT NULL,
    name             TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT '',
    sources          TEXT NOT NULL DEFAULT '[]',   -- JSON array of system names
    source_other     TEXT NOT NULL DEFAULT '',
    formula          TEXT NOT NULL DEFAULT '',
    report           TEXT NOT NULL DEFAULT '',
    report_none      INTEGER NOT NULL DEFAULT 0,
    breakdowns       TEXT NOT NULL DEFAULT '',
    breakdowns_same  INTEGER NOT NULL DEFAULT 0,  -- "same as the current report"
    refresh          TEXT NOT NULL DEFAULT '',
    refresh_why      TEXT NOT NULL DEFAULT '',
    owner_id         INTEGER REFERENCES people(id) ON DELETE SET NULL,
    owner_note       TEXT NOT NULL DEFAULT '',
    assignee_id      INTEGER REFERENCES people(id) ON DELETE SET NULL,
    status           TEXT NOT NULL DEFAULT 'not_started',
    followup         INTEGER NOT NULL DEFAULT 0,
    followup_note    TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT '',
    updated_at       TEXT,
    updated_by       INTEGER REFERENCES people(id) ON DELETE SET NULL,
    completed_at     TEXT, target TEXT NOT NULL DEFAULT '', target_none INTEGER NOT NULL DEFAULT 0, time_basis TEXT NOT NULL DEFAULT '', restatement TEXT NOT NULL DEFAULT '', restatement_none INTEGER NOT NULL DEFAULT 0, sme_id INTEGER REFERENCES people(id) ON DELETE SET NULL, sme_note TEXT NOT NULL DEFAULT '', unknown TEXT NOT NULL DEFAULT '{}', process_id INTEGER REFERENCES processes(id) ON DELETE SET NULL, dimension_ids TEXT NOT NULL DEFAULT '[]', ref_id INTEGER REFERENCES requirements(id) ON DELETE SET NULL, metric_name TEXT NOT NULL DEFAULT '', binding TEXT NOT NULL DEFAULT '{}',
    UNIQUE (dashboard_id, slot)
);
CREATE TABLE activity (
    id              INTEGER PRIMARY KEY,
    requirement_id  INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    at              TEXT NOT NULL,
    actor_id        INTEGER REFERENCES people(id) ON DELETE SET NULL,
    action          TEXT NOT NULL,
    detail          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX activity_by_requirement ON activity (requirement_id, at);
CREATE TABLE archive (
    id           INTEGER PRIMARY KEY,
    client_id    INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,                  -- 'dashboard' or 'column'
    label        TEXT NOT NULL,
    payload      TEXT NOT NULL,                  -- JSON: everything needed to put it back
    archived_at  TEXT NOT NULL,
    archived_by  INTEGER REFERENCES people(id) ON DELETE SET NULL
);
CREATE TABLE departments (
    id         INTEGER PRIMARY KEY,
    client_id  INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name       TEXT NOT NULL, code TEXT NOT NULL DEFAULT '', position INTEGER,
    UNIQUE (client_id, name)
);
CREATE TABLE processes (
    id             INTEGER PRIMARY KEY,
    client_id      INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    position       INTEGER NOT NULL,
    name           TEXT NOT NULL DEFAULT '',
    answers        TEXT NOT NULL DEFAULT '{}',   -- JSON: {question key: answer}, see items.QUESTIONS
    unknown        TEXT NOT NULL DEFAULT '{}',   -- JSON: {question key: who might know}
    owner_id       INTEGER REFERENCES people(id) ON DELETE SET NULL,
    owner_dept_id  INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    owner_note     TEXT NOT NULL DEFAULT '',
    assignee_id    INTEGER REFERENCES people(id) ON DELETE SET NULL,
    status         TEXT NOT NULL DEFAULT 'not_started',
    followup       INTEGER NOT NULL DEFAULT 0,
    followup_note  TEXT NOT NULL DEFAULT '',
    notes          TEXT NOT NULL DEFAULT '',
    updated_at     TEXT,
    updated_by     INTEGER REFERENCES people(id) ON DELETE SET NULL,
    completed_at   TEXT
, code TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE dimensions (
    id             INTEGER PRIMARY KEY,
    client_id      INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    position       INTEGER NOT NULL,
    name           TEXT NOT NULL DEFAULT '',
    answers        TEXT NOT NULL DEFAULT '{}',   -- JSON: {question key: answer}, see items.QUESTIONS
    unknown        TEXT NOT NULL DEFAULT '{}',   -- JSON: {question key: who might know}
    owner_id       INTEGER REFERENCES people(id) ON DELETE SET NULL,
    owner_dept_id  INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    owner_note     TEXT NOT NULL DEFAULT '',
    assignee_id    INTEGER REFERENCES people(id) ON DELETE SET NULL,
    status         TEXT NOT NULL DEFAULT 'not_started',
    followup       INTEGER NOT NULL DEFAULT 0,
    followup_note  TEXT NOT NULL DEFAULT '',
    notes          TEXT NOT NULL DEFAULT '',
    updated_at     TEXT,
    updated_by     INTEGER REFERENCES people(id) ON DELETE SET NULL,
    completed_at   TEXT
, code TEXT NOT NULL DEFAULT '');
CREATE TABLE process_steps (
    id          INTEGER PRIMARY KEY,
    process_id  INTEGER NOT NULL REFERENCES processes(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    dept_id     INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    person_id   INTEGER REFERENCES people(id) ON DELETE SET NULL,
    system      TEXT NOT NULL DEFAULT ''
);
CREATE TABLE bus_cells (                -- a row means the box is ticked
    process_id    INTEGER NOT NULL REFERENCES processes(id) ON DELETE CASCADE,
    dimension_id  INTEGER NOT NULL REFERENCES dimensions(id) ON DELETE CASCADE,
    PRIMARY KEY (process_id, dimension_id)
);
CREATE TABLE tiles (                    -- a dashboard sketch, on a 12-column grid
    id              INTEGER PRIMARY KEY,
    dashboard_id    INTEGER NOT NULL REFERENCES dashboards(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    x               INTEGER NOT NULL,
    y               INTEGER NOT NULL,
    w               INTEGER NOT NULL,
    h               INTEGER NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    requirement_id  INTEGER REFERENCES requirements(id) ON DELETE SET NULL,
    dimension_id    INTEGER REFERENCES dimensions(id) ON DELETE SET NULL,
    note            TEXT NOT NULL DEFAULT ''
);
CREATE TABLE item_activity (            -- change history for processes and dimensions
    id         INTEGER PRIMARY KEY,
    client_id  INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    item_id    INTEGER NOT NULL,
    at         TEXT NOT NULL,
    actor_id   INTEGER REFERENCES people(id) ON DELETE SET NULL,
    action     TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX item_activity_by_item ON item_activity (kind, item_id, at);
CREATE TABLE measure_departments (     -- which departments own or contribute to a measure
    id              INTEGER PRIMARY KEY,
    requirement_id  INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
    department_id   INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    process_id      INTEGER REFERENCES processes(id) ON DELETE SET NULL,
    influence       TEXT NOT NULL CHECK (influence IN ('owns', 'contributes')),
    position        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE cubes (                    -- target binding: a saved query, a fixed set of measures at a fixed grain
    id           INTEGER PRIMARY KEY,
    client_id    INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    measures     TEXT NOT NULL DEFAULT '[]',          -- JSON: metric names
    group_by     TEXT NOT NULL DEFAULT '[]',          -- JSON: MetricFlow group-by references
    UNIQUE (client_id, name)
);

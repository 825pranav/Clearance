-- Clearance schema. Running this file drops and recreates every table.

DROP TABLE IF EXISTS audit_log, requests, role_baseline, systems, employees CASCADE;

CREATE TABLE employees (
    email          TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    role           TEXT NOT NULL,
    department     TEXT NOT NULL,
    manager_email  TEXT REFERENCES employees(email) DEFERRABLE INITIALLY DEFERRED,
    slack_user_id  TEXT UNIQUE,
    gitlab_username TEXT          -- the GitLab account whose labels count as this person's approvals
);

CREATE TABLE systems (
    key           TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    aliases       TEXT[] NOT NULL DEFAULT '{}',
    risk_tier     TEXT NOT NULL CHECK (risk_tier IN ('low', 'medium', 'high')),
    owner_email   TEXT NOT NULL REFERENCES employees(email),
    handbook_doc  TEXT NOT NULL
);

-- Access a role gets by default, without filing a request.
CREATE TABLE role_baseline (
    role          TEXT NOT NULL,
    system_key    TEXT NOT NULL REFERENCES systems(key),
    access_level  TEXT NOT NULL CHECK (access_level IN ('read', 'write', 'admin')),
    PRIMARY KEY (role, system_key)
);

CREATE TABLE requests (
    id                BIGSERIAL PRIMARY KEY,
    employee_email    TEXT NOT NULL REFERENCES employees(email),
    system_key        TEXT NOT NULL REFERENCES systems(key),
    access_level      TEXT NOT NULL CHECK (access_level IN ('read', 'write', 'admin')),
    justification     TEXT NOT NULL DEFAULT '',
    risk_tier         TEXT NOT NULL CHECK (risk_tier IN ('low', 'medium', 'high')),
    approvers         JSONB NOT NULL,
    -- Lifecycle (see policy.transition): filing -> pending -> partially_approved -> approved | rejected, or filing -> failed.
    status            TEXT NOT NULL CHECK (status IN ('filing', 'pending', 'partially_approved', 'approved', 'rejected', 'failed')),
    approvals         TEXT[] NOT NULL DEFAULT '{}',   -- approval slots recorded so far: manager, owner
    idempotency_key   UUID UNIQUE,                    -- also written into the issue body, so a crash can be repaired
    gitlab_issue_iid  INTEGER,
    gitlab_issue_url  TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One open request per employee per system. Two simultaneous requests cannot both get in.
CREATE UNIQUE INDEX one_open_request_per_system ON requests (employee_email, system_key)
    WHERE status IN ('filing', 'pending', 'partially_approved');

CREATE TABLE audit_log (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  TEXT,
    request_id       BIGINT REFERENCES requests(id),
    actor            TEXT NOT NULL,
    event            TEXT NOT NULL,
    detail           JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX audit_log_request_idx ON audit_log (request_id);

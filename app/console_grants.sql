-- What the Django console's database login may do. Safe to run repeatedly.
-- db.reset() runs this too, because dropping a table also drops its grants.
--
-- This is the real lock behind the console's read-only rules. The console can never change a request or rewrite
-- the audit log, even if a bug in its code tries to, because Postgres refuses.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'clearance_console') THEN
        CREATE ROLE clearance_console NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO clearance_console;

-- Read-only: a request's status changes only in db.advance().
GRANT SELECT ON requests, role_baseline TO clearance_console;

-- Insert-only: audit entries can be added and read, never changed or removed.
GRANT SELECT, INSERT ON audit_log TO clearance_console;
GRANT USAGE ON SEQUENCE audit_log_id_seq TO clearance_console;

-- Catalogue edits. Column grants leave out the primary keys, and there is no INSERT or DELETE.
GRANT SELECT ON employees, systems TO clearance_console;
GRANT UPDATE (name, role, department, manager_email, slack_user_id, gitlab_username) ON employees TO clearance_console;
GRANT UPDATE (name, aliases, risk_tier, owner_email, handbook_doc) ON systems TO clearance_console;

-- Django's own tables (logins, sessions, admin history). They do not exist until `manage.py migrate` has run.
DO $$
DECLARE
    item record;
BEGIN
    FOR item IN SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' AND (tablename LIKE 'auth\_%' OR tablename LIKE 'django\_%') LOOP
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO clearance_console', item.tablename);
    END LOOP;
    FOR item IN SELECT sequencename FROM pg_sequences
                WHERE schemaname = 'public' AND (sequencename LIKE 'auth\_%' OR sequencename LIKE 'django\_%') LOOP
        EXECUTE format('GRANT USAGE ON SEQUENCE %I TO clearance_console', item.sequencename);
    END LOOP;
END $$;

-- =====================================================================
-- File 02: Security  (roles, permissions, row-level security)   PostgreSQL / Supabase
-- PostgreSQL version of ../02_security.sql. Run AFTER 01_schema.sql as the
-- database owner (on Supabase: the SQL Editor, or the postgres login).
--
-- Three tiers (from the project proposal):
--   wsb_admin     Admin      all data, can delete; CANNOT edit or delete the audit log
--   wsb_staff     Staff      view and add/edit operational data; no deletes;
--                            no users/roles/audit; no Admin-level documents
--   wsb_readonly  Read-only  view only; no personal data (no license numbers or
--                            emails); only 'General' documents
-- Real people get their own login, added to ONE of these roles with
-- wsb.create_wsb_user (below). Nobody is granted anything by default.
-- The database owner (the dashboard connection) is not limited by any of this.
-- Safe to re-run.
-- =====================================================================

-- 1) Roles (cannot log in themselves; people's logins are added to them) ----
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wsb_admin')    THEN CREATE ROLE wsb_admin    NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wsb_staff')    THEN CREATE ROLE wsb_staff    NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wsb_readonly') THEN CREATE ROLE wsb_readonly NOLOGIN; END IF;
END $$;

GRANT USAGE ON SCHEMA wsb TO wsb_admin, wsb_staff, wsb_readonly;

-- Functions are runnable by everyone by default in PostgreSQL. Switch that off
-- for this schema; each role is granted exactly the functions it needs.
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA wsb FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA wsb REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
GRANT EXECUTE ON FUNCTION wsb.fiscal_year(DATE), wsb.in_role(NAME), wsb.document_visible(VARCHAR)
    TO wsb_admin, wsb_staff, wsb_readonly;

-- 2) ADMIN: everything in the schema, but the audit log is read-only ----------
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA wsb TO wsb_admin;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON wsb.audit_log FROM wsb_admin;   -- new rows come from the audit triggers only
GRANT USAGE ON ALL SEQUENCES IN SCHEMA wsb TO wsb_admin;

-- 3) STAFF: add and edit operational data, NO delete -------------------------
GRANT SELECT, INSERT, UPDATE ON
    wsb.driver, wsb.driver_license, wsb.driver_qualification,
    wsb.vehicle, wsb.vehicle_document, wsb.maintenance_rule,
    wsb.invoice, wsb.invoice_line,
    wsb.trip, wsb.fuel_record, wsb.maintenance_record
    TO wsb_staff;
GRANT SELECT ON wsb.wex_code TO wsb_staff;
GRANT SELECT ON
    wsb.v_vehicle_summary, wsb.v_cost_by_vehicle_fy, wsb.v_invoice_reconciliation,
    wsb.v_fuel_efficiency, wsb.v_maintenance_due, wsb.v_driver_directory,
    wsb.v_expiring_items, wsb.v_state_audit_vehicle_log
    TO wsb_staff;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA wsb TO wsb_staff;
-- Staff get NOTHING on app_user, app_role, audit_log (no grant = no access).

-- 4) READ-ONLY: reports and non-personal tables only -------------------------
GRANT SELECT ON
    wsb.vehicle, wsb.trip, wsb.fuel_record, wsb.maintenance_record, wsb.maintenance_rule,
    wsb.invoice, wsb.invoice_line,
    wsb.vehicle_document,          -- rows limited by the policy below
    wsb.wex_code
    TO wsb_readonly;
GRANT SELECT ON
    wsb.v_vehicle_summary, wsb.v_cost_by_vehicle_fy, wsb.v_invoice_reconciliation,
    wsb.v_fuel_efficiency, wsb.v_maintenance_due,
    wsb.v_driver_directory,        -- no email / license data
    wsb.v_state_audit_vehicle_log
    TO wsb_readonly;
-- Deliberately NOT granted: driver (email), driver_license, driver_qualification,
-- app_user, app_role, audit_log, v_expiring_items.

-- 5) Row-level security ------------------------------------------------------
-- RLS is on for every wsb table (01_schema). With RLS on, a role sees no rows
-- unless a policy lets it, so the three wsb roles get an "all rows" policy on
-- every table; the GRANTs above still decide what each role may do.
DO $$
DECLARE t TEXT;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables
             WHERE schemaname = 'wsb' AND tablename NOT LIKE 'stg\_%' AND tablename <> 'vehicle_document' LOOP
        EXECUTE format('ALTER TABLE wsb.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS wsb_roles_all_rows ON wsb.%I', t);
        EXECUTE format('CREATE POLICY wsb_roles_all_rows ON wsb.%I TO wsb_admin, wsb_staff, wsb_readonly
                        USING (true) WITH CHECK (true)', t);
    END LOOP;
END $$;

-- Documents: access_level General < Staff < Admin
--   Admin sees and writes everything; Staff sees/writes General + Staff only;
--   Read-only sees General only. (Same as the SQL Server security policy.)
ALTER TABLE wsb.vehicle_document ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS doc_admin    ON wsb.vehicle_document;
DROP POLICY IF EXISTS doc_staff    ON wsb.vehicle_document;
DROP POLICY IF EXISTS doc_readonly ON wsb.vehicle_document;
CREATE POLICY doc_admin ON wsb.vehicle_document TO wsb_admin
    USING (true) WITH CHECK (true);
CREATE POLICY doc_staff ON wsb.vehicle_document TO wsb_staff
    USING (access_level IN ('General','Staff')) WITH CHECK (access_level IN ('General','Staff'));
CREATE POLICY doc_readonly ON wsb.vehicle_document FOR SELECT TO wsb_readonly
    USING (access_level = 'General');

-- 6) Role catalogue rows (mirrors the roles above) ---------------------------
INSERT INTO wsb.app_role (role_name, pg_role, description) VALUES
    ('Admin',     'wsb_admin',    'Full access: manage users, delete records, see all documents'),
    ('Staff',     'wsb_staff',    'Add and edit operational data; cannot delete or manage users'),
    ('Read-only', 'wsb_readonly', 'View vehicles, trips, fuel, maintenance, invoices and reports only')
ON CONFLICT (role_name) DO NOTHING;

-- 7) Helper: create a login + role membership + app_user row in one call.
--    Run it as the database owner (creating logins needs CREATEROLE, so it is
--    NOT granted to wsb_admin). On Supabase the person then signs in with the
--    username '<username>.<project ref>' through the Session pooler.
CREATE OR REPLACE FUNCTION wsb.create_wsb_user(
    p_username  TEXT,
    p_full_name TEXT,
    p_email     TEXT,
    p_role      TEXT,      -- Admin | Staff | Read-only
    p_password  TEXT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE v_role_id INT; v_db_role TEXT;
BEGIN
    SELECT role_id, pg_role INTO v_role_id, v_db_role
    FROM wsb.app_role WHERE role_name = p_role;

    IF v_role_id IS NULL THEN
        RAISE EXCEPTION 'Unknown role %. Use Admin, Staff or Read-only.', p_role;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_username) THEN
        EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', p_username, p_password);
    END IF;

    EXECUTE format('GRANT %I TO %I', v_db_role, p_username);

    INSERT INTO wsb.app_user (username, full_name, email, role_id)
    VALUES (p_username, p_full_name, p_email, v_role_id)
    ON CONFLICT (username) DO NOTHING;
END;
$$;
REVOKE ALL ON FUNCTION wsb.create_wsb_user(TEXT, TEXT, TEXT, TEXT, TEXT) FROM PUBLIC;

-- Example (use a letters-and-numbers password; ask the person to change it):
-- SELECT wsb.create_wsb_user('jsmith', 'Jane Smith', 'jsmith@fgcu.edu', 'Staff', 'ChangeMe2026xyz');

-- 8) Keep the Supabase public API locked out ---------------------------------
SELECT wsb.lock_out_public_api();

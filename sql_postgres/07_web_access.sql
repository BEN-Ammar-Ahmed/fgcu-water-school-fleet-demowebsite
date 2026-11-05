-- =====================================================================
-- File 07: Web site access   PostgreSQL / Supabase
-- Adds what the web site needs on top of 01-05 for the client's access tiers:
--   Tier 1  = app_role 'Admin'      view, add, edit, delete
--   Tier 2  = app_role 'Read-only'  view only
--   License access ("Tier 3") = app_user.can_see_licenses, an extra switch
--     for the ~3 people allowed to open driver's license records.
-- Run AFTER 01-05. Safe to re-run.
-- =====================================================================

ALTER TABLE wsb.app_user
    ADD COLUMN IF NOT EXISTS can_see_licenses BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN wsb.app_user.can_see_licenses IS
    'Can open driver''s license records (the client''s Tier 3). Set by the fleet manager.';

SELECT wsb.lock_out_public_api();

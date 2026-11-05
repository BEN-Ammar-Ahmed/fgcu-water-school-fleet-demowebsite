-- =====================================================================
-- File 07b: Demo sign-in users   PostgreSQL / Supabase
-- FICTIONAL people (@example.edu) so the web site's demo sign-in works
-- until Reagan sends the real list of people per tier.
-- Run AFTER 07_web_access.sql. Safe to re-run.
--
-- Remove them once real users are added:
--   DELETE FROM wsb.app_user WHERE email LIKE '%@example.edu';
-- =====================================================================

INSERT INTO wsb.app_user (username, full_name, email, role_id, can_see_licenses, active)
SELECT u.username, u.full_name, u.email, r.role_id, u.licenses, u.active
FROM (VALUES
    ('demo_tier1',          'Demo Fleet Manager',    'fleet.manager@example.edu',    'Admin',     TRUE,  TRUE),
    ('demo_tier1_backup',   'Demo Backup Manager',   'fleet.backup@example.edu',     'Admin',     FALSE, TRUE),
    ('demo_tier2',          'Demo Campus Staff',     'campus.staff@example.edu',     'Read-only', FALSE, TRUE),
    ('demo_tier2_licenses', 'Demo Insurance Office', 'insurance.office@example.edu', 'Read-only', TRUE,  TRUE),
    ('demo_inactive',       'Demo Former Staff',     'former.staff@example.edu',     'Read-only', FALSE, FALSE)
) AS u(username, full_name, email, role_name, licenses, active)
JOIN wsb.app_role AS r ON r.role_name = u.role_name
ON CONFLICT (username) DO UPDATE
    SET full_name = EXCLUDED.full_name,
        email = EXCLUDED.email,
        role_id = EXCLUDED.role_id,
        can_see_licenses = EXCLUDED.can_see_licenses,
        active = EXCLUDED.active;

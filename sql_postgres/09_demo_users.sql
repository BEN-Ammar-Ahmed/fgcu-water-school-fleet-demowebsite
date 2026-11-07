-- =====================================================================
-- File 09: Demo sign-in users   PostgreSQL / Supabase  (was 07b_demo_users.sql)
-- FICTIONAL people (@example.edu) so the web site's demo sign-in works
-- until Reagan sends the real list of people per level.
-- Run AFTER 08_admin_levels.sql (it needs the 'Top admin' level). Safe to re-run.
--
-- Remove them once real users are added:
--   DELETE FROM wsb.app_user WHERE email LIKE '%@example.edu';
-- =====================================================================

INSERT INTO wsb.app_user (username, full_name, email, role_id, can_see_licenses, active)
SELECT u.username, u.full_name, u.email, r.role_id, u.licenses, u.active
FROM (VALUES
    ('demo_tier1',          'Fleet Manager',    'fleet.manager@example.edu',    'Top admin', TRUE,  TRUE),
    ('demo_tier1_backup',   'Backup Fleet Manager',   'fleet.backup@example.edu',     'Admin',     FALSE, TRUE),
    ('demo_editor',         'Boat Captain',     'editor.staff@example.edu',     'Staff',     FALSE, TRUE),
    ('demo_tier2',          'Campus Staff',     'campus.staff@example.edu',     'Read-only', FALSE, TRUE),
    ('demo_tier2_licenses', 'Insurance Office', 'insurance.office@example.edu', 'Read-only', FALSE, TRUE),
    ('demo_inactive',       'Former Staff',     'former.staff@example.edu',     'Read-only', FALSE, FALSE)
) AS u(username, full_name, email, role_name, licenses, active)
JOIN wsb.app_role AS r ON r.role_name = u.role_name
ON CONFLICT (username) DO UPDATE
    SET full_name = EXCLUDED.full_name,
        email = EXCLUDED.email,
        role_id = EXCLUDED.role_id,
        can_see_licenses = EXCLUDED.can_see_licenses,
        active = EXCLUDED.active;

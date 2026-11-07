-- 12_tiers.sql
-- Three tiers (agreed with the client, Nov 2026) plus per-person "switches":
--   Tier 1 · Top admin  ('Top admin')  everything, incl. driver's licenses and managing people
--   Tier 2 · Editor     ('Staff')      maintenance records and check-in/checkout
--   Tier 3 · Viewer     ('Read-only')  view only (and, later, request a vehicle)
-- A top admin can switch on extra abilities for one person (wsb.app_user_permission).
-- The old middle level 'Admin' is folded into Tier 1: its people become top admins.
-- Safe to run more than once.

CREATE TABLE IF NOT EXISTS wsb.app_user_permission (
    user_id     INT          NOT NULL REFERENCES wsb.app_user (user_id) ON DELETE CASCADE,
    permission  VARCHAR(30)  NOT NULL CHECK (permission IN
                    ('maintenance', 'checkout', 'trips_fuel', 'vehicles', 'documents', 'approve', 'delete')),
    granted_by  VARCHAR(100),
    granted_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, permission)
);
COMMENT ON TABLE wsb.app_user_permission IS
    'Extra abilities a top admin switched on for one person, on top of their tier''s defaults.';

-- Fold the middle level into Tier 1.
UPDATE wsb.app_user SET role_id = (SELECT role_id FROM wsb.app_role WHERE role_name = 'Top admin')
WHERE role_id = (SELECT role_id FROM wsb.app_role WHERE role_name = 'Admin');

UPDATE wsb.app_role SET description = 'Tier 1 · Top admin: everything, incl. driver''s licenses and managing people'
WHERE role_name = 'Top admin';
UPDATE wsb.app_role SET description = 'Tier 2 · Editor: maintenance and check-in/checkout, plus any switches'
WHERE role_name = 'Staff';
UPDATE wsb.app_role SET description = 'Tier 3 · Viewer: view only, plus any switches'
WHERE role_name = 'Read-only';
UPDATE wsb.app_role SET description = 'No longer used: merged into Tier 1 (12_tiers.sql)'
WHERE role_name = 'Admin';

GRANT SELECT ON wsb.app_user_permission TO wsb_admin;
ALTER TABLE wsb.app_user_permission ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS wsb_roles_all_rows ON wsb.app_user_permission;
CREATE POLICY wsb_roles_all_rows ON wsb.app_user_permission FOR SELECT TO wsb_admin USING (true);

SELECT wsb.lock_out_public_api();

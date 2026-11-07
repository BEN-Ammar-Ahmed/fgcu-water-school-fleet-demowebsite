-- 14_passwords.sql
-- Username + password sign-in for the fleet site.
-- Passwords live in their own table, stored only as salted hashes (never the password itself).
-- No database role is granted access: only the website reads it.
-- After running this, nobody has a password yet. Set the first one from a terminal:
--     cd dashboard
--     python set_password.py <username or email>
-- Then that top admin sets everyone else's from Admin -> People.
-- Safe to run more than once.

CREATE TABLE IF NOT EXISTS wsb.app_user_password (
    user_id               INT          PRIMARY KEY REFERENCES wsb.app_user (user_id) ON DELETE CASCADE,
    password_hash         TEXT         NOT NULL,
    must_change           BOOLEAN      NOT NULL DEFAULT TRUE,   -- temporary password: change it after signing in
    failed_logins         INT          NOT NULL DEFAULT 0,
    locked_until          TIMESTAMPTZ,                          -- too many wrong passwords: wait until then
    changed_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);
COMMENT ON TABLE wsb.app_user_password IS
    'Fleet site passwords (hashed). Read only by the website; no role has access.';

ALTER TABLE wsb.app_user_password ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON wsb.app_user_password FROM PUBLIC;

SELECT wsb.lock_out_public_api();

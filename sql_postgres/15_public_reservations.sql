-- 15_public_reservations.sql
-- The separate reservation website (dashboard/reserve_app.py): anyone with the link can request a vehicle,
-- without a fleet account.
--   wsb.reservation.public_token          secret part of the requester's private link (in their emails)
--   wsb.reservation.requested_vehicle_id  the vehicle they picked; the approver can confirm it or give another
--   wsb.reservation.request_ip            where the request came from (spam limits only)
-- Safe to run more than once.

ALTER TABLE wsb.reservation ADD COLUMN IF NOT EXISTS public_token VARCHAR(64);
ALTER TABLE wsb.reservation ADD COLUMN IF NOT EXISTS requested_vehicle_id INT
    REFERENCES wsb.vehicle (vehicle_id) ON DELETE SET NULL;
ALTER TABLE wsb.reservation ADD COLUMN IF NOT EXISTS request_ip VARCHAR(45);

UPDATE wsb.reservation SET public_token = md5(random()::text || clock_timestamp()::text) || md5(random()::text)
WHERE public_token IS NULL;
ALTER TABLE wsb.reservation ALTER COLUMN public_token SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS reservation_public_token_idx ON wsb.reservation (public_token);
CREATE INDEX IF NOT EXISTS reservation_recent_email_idx ON wsb.reservation (lower(requester_email), created_at);

COMMENT ON COLUMN wsb.reservation.public_token IS 'Secret for the requester''s private link. Never show it to others.';
COMMENT ON COLUMN wsb.reservation.requested_vehicle_id IS 'Vehicle the requester picked (vehicle_id is the one approved).';

SELECT wsb.lock_out_public_api();

-- 13_reservations.sql
-- Vehicle reservations: someone fills in a request, it lands in the inbox of everyone who may approve,
-- and they approve (choosing a vehicle), deny, or ask for missing information.
--   wsb.reservation        one request (who, where, when, extra drivers, status, assigned vehicle)
--   wsb.reservation_event  its history: requested, updated, approved, denied, needs info, cancelled
--   wsb.email_outbox       every email the site wants to send. Rows wait here until a mailer sends them
--                          (see dashboard/docs/reservations.md). Nothing is lost if email is not set up yet.
-- Safe to run more than once.

CREATE TABLE IF NOT EXISTS wsb.reservation (
    reservation_id   SERIAL        PRIMARY KEY,
    requested_by     INT           REFERENCES wsb.app_user (user_id) ON DELETE SET NULL,
    requester_name   VARCHAR(100)  NOT NULL,
    requester_email  VARCHAR(150)  NOT NULL,
    uin              VARCHAR(20)   NOT NULL,
    phone            VARCHAR(30)   NOT NULL,
    destination      VARCHAR(200)  NOT NULL,
    purpose          VARCHAR(300),
    vehicle_type     VARCHAR(30),                 -- what they asked for; NULL = any
    passengers       INT           CHECK (passengers IS NULL OR passengers BETWEEN 1 AND 100),
    pickup_at        TIMESTAMP     NOT NULL,
    return_at        TIMESTAMP     NOT NULL,
    drivers          JSONB         NOT NULL DEFAULT '[]',   -- other drivers: [{"name": ..., "email": ...}]
    notes            TEXT,
    status           VARCHAR(20)   NOT NULL DEFAULT 'Pending'
                     CHECK (status IN ('Pending', 'Needs info', 'Approved', 'Denied', 'Cancelled')),
    vehicle_id       INT           REFERENCES wsb.vehicle (vehicle_id) ON DELETE SET NULL,   -- set on approval
    decided_by       VARCHAR(100),
    decided_at       TIMESTAMPTZ,
    decision_note    TEXT,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT reservation_return_after_pickup CHECK (return_at > pickup_at)
);
CREATE INDEX IF NOT EXISTS reservation_status_idx ON wsb.reservation (status, pickup_at);
CREATE INDEX IF NOT EXISTS reservation_vehicle_idx ON wsb.reservation (vehicle_id, pickup_at, return_at);
CREATE INDEX IF NOT EXISTS reservation_requested_by_idx ON wsb.reservation (requested_by);
COMMENT ON TABLE wsb.reservation IS 'Vehicle requests and their approval status.';

CREATE TABLE IF NOT EXISTS wsb.reservation_event (
    event_id        SERIAL        PRIMARY KEY,
    reservation_id  INT           NOT NULL REFERENCES wsb.reservation (reservation_id) ON DELETE CASCADE,
    at              TIMESTAMPTZ   NOT NULL DEFAULT now(),
    by_name         VARCHAR(100),
    action          VARCHAR(30)   NOT NULL,
    note            TEXT
);
CREATE INDEX IF NOT EXISTS reservation_event_idx ON wsb.reservation_event (reservation_id, at);
COMMENT ON TABLE wsb.reservation_event IS 'History of one reservation: who did what, when, and the message they wrote.';

CREATE TABLE IF NOT EXISTS wsb.email_outbox (
    email_id        SERIAL        PRIMARY KEY,
    to_email        VARCHAR(150)  NOT NULL,
    subject         VARCHAR(200)  NOT NULL,
    body            TEXT          NOT NULL,
    reservation_id  INT           REFERENCES wsb.reservation (reservation_id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ,                 -- NULL = still waiting to be sent
    error           TEXT                         -- last sending error, if any
);
CREATE INDEX IF NOT EXISTS email_outbox_waiting_idx ON wsb.email_outbox (created_at) WHERE sent_at IS NULL;
COMMENT ON TABLE wsb.email_outbox IS 'Emails waiting to be sent (sent_at IS NULL) and emails already sent.';

-- The activity log gets its own kind for reservation decisions.
ALTER TABLE wsb.activity_log DROP CONSTRAINT IF EXISTS activity_log_kind_check;
ALTER TABLE wsb.activity_log ADD CONSTRAINT activity_log_kind_check
    CHECK (kind IN ('sign-in', 'sign-out', 'view', 'change', 'download', 'access', 'reservation'));

GRANT SELECT ON wsb.reservation, wsb.reservation_event, wsb.email_outbox TO wsb_admin;
ALTER TABLE wsb.reservation ENABLE ROW LEVEL SECURITY;
ALTER TABLE wsb.reservation_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE wsb.email_outbox ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS wsb_roles_all_rows ON wsb.reservation;
CREATE POLICY wsb_roles_all_rows ON wsb.reservation FOR SELECT TO wsb_admin USING (true);
DROP POLICY IF EXISTS wsb_roles_all_rows ON wsb.reservation_event;
CREATE POLICY wsb_roles_all_rows ON wsb.reservation_event FOR SELECT TO wsb_admin USING (true);
DROP POLICY IF EXISTS wsb_roles_all_rows ON wsb.email_outbox;
CREATE POLICY wsb_roles_all_rows ON wsb.email_outbox FOR SELECT TO wsb_admin USING (true);

SELECT wsb.lock_out_public_api();

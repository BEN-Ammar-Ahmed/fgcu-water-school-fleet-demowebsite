"""Reservations logic shared by both websites. Nothing here depends on Flask.

    reserve_app.py   the request site: anyone with the link picks free vehicles and sends a request
    reservations.py  the fleet site's inbox: approvers approve, deny, or ask for more information

Functions take `q` (read) and `run` (write + commit) so each site passes its own database helpers.
"""
import datetime as dt
import json
import re
import secrets

import mailer
from common import VEHICLE_TYPES, fleet_url, reserve_url
from forms import Field

STATUSES = ['Pending', 'Needs info', 'Approved', 'Denied', 'Cancelled']
OPEN = ('Pending', 'Needs info')            # still waiting for a decision
EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
MAX_DRIVERS = 10
NOT_RESERVABLE = ('Retired', 'Out of Service')          # never offered
HIDDEN_FROM_REQUESTERS = NOT_RESERVABLE + ('In Maintenance',)


def when(value):
    """'Fri Nov 13, 2026, 8:00 AM'."""
    if not value:
        return ''
    return value.strftime('%a %b %d, %Y, ') + value.strftime('%I:%M %p').lstrip('0')


def new_token():
    return secrets.token_urlsafe(24)


# SQL for a vehicle's display name (same rule as common.display_name).
def _label_sql(a):
    return (f"COALESCE(NULLIF(trim({a}.name), ''), NULLIF(concat_ws(' ', {a}.year, {a}.make, {a}.model), ''), "
            f"'Vehicle #' || {a}.vehicle_id)")


SELECT = f"""SELECT r.*, {_label_sql('v')} AS vehicle_label, v.asset_number AS v_asset,
                    {_label_sql('rv')} AS requested_label, rv.vehicle_type AS requested_type
             FROM wsb.reservation r
             LEFT JOIN wsb.vehicle v ON v.vehicle_id = r.vehicle_id
             LEFT JOIN wsb.vehicle rv ON rv.vehicle_id = r.requested_vehicle_id"""


def get(q, rid=None, token=None):
    if token is not None:
        return q(SELECT + ' WHERE r.public_token = %s', (token,), one=True)
    return q(SELECT + ' WHERE r.reservation_id = %s', (rid,), one=True)


def event(run, rid, by, action, note=None):
    run('INSERT INTO wsb.reservation_event (reservation_id, by_name, action, note) VALUES (%s, %s, %s, %s)',
        (rid, by, action, note))


# ---------------------------------------------------------------------------
# Which vehicles are free
# ---------------------------------------------------------------------------
def vehicles(q, pick, ret, exclude_rid=0, for_requesters=True, vtype=None):
    """Vehicles for that time. booked = already approved for part of it.
    Requesters see only free vehicles that aren't in maintenance; approvers see all reservable ones, booked flagged."""
    hidden = HIDDEN_FROM_REQUESTERS if for_requesters else NOT_RESERVABLE
    rows = q(f"""
        SELECT v.vehicle_id, {_label_sql('v')} AS label, v.vehicle_type, v.location, v.status, v.asset_number,
               EXISTS (SELECT 1 FROM wsb.reservation o
                       WHERE o.vehicle_id = v.vehicle_id AND o.status = 'Approved'
                         AND o.reservation_id <> %(rid)s
                         AND o.pickup_at < %(ret)s AND o.return_at > %(pick)s) AS booked
        FROM wsb.vehicle v
        WHERE v.active AND v.status <> ALL(%(hidden)s)
          AND (%(vtype)s = '' OR v.vehicle_type = %(vtype)s)
        ORDER BY (v.vehicle_type = %(want)s) DESC, v.vehicle_type, 2""",
             {'rid': exclude_rid or 0, 'ret': ret, 'pick': pick, 'hidden': list(hidden),
              'vtype': vtype if for_requesters and vtype else '', 'want': vtype or ''})
    return [r for r in rows if not r['booked']] if for_requesters else rows


def is_free(q, vid, pick, ret, exclude_rid=0):
    return any(v['vehicle_id'] == vid for v in vehicles(q, pick, ret, exclude_rid))


# ---------------------------------------------------------------------------
# The request form (request site)
# ---------------------------------------------------------------------------
def fields(vehicle_choices):
    return [Field('requester_name', 'Your name', required=True),
            Field('requester_email', 'Email', required=True, help='Where the answer is sent.'),
            Field('uin', 'UIN', required=True, help='Your FGCU ID number.'),
            Field('phone', 'Phone', required=True),
            Field('pickup_at', 'Pick up', 'datetime', True),
            Field('return_at', 'Return', 'datetime', True),
            Field('requested_vehicle_id', 'Vehicle', 'select', options=vehicle_choices,
                  help='Free for the times above. Leave on "Choose…" if any vehicle of the type below works.'),
            Field('vehicle_type', 'Vehicle type', 'select', options=[(t, t) for t in VEHICLE_TYPES]),
            Field('destination', 'Destination', required=True),
            Field('purpose', 'Purpose'),
            Field('passengers', 'Passengers', 'int'),
            Field('drivers', 'Other drivers', 'textarea', wide=True,
                  help='One per line: name, email. Leave empty if you are the only driver.'),
            Field('notes', 'Anything else we should know', 'textarea', wide=True)]


def parse_drivers(text):
    """'Ana Lee, alee@fgcu.edu' per line -> ([{'name', 'email'}], errors)."""
    drivers, errors = [], []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r'[,;\t]', line, maxsplit=1)
        name, email = parts[0].strip(), (parts[1].strip() if len(parts) > 1 else '')
        if not name:
            errors.append(f'Other drivers: "{line}" needs a name before the email.')
        if email and not EMAIL.match(email):
            errors.append(f'Other drivers: "{email}" does not look like an email address.')
        drivers.append({'name': name[:100], 'email': email[:150]})
    if len(drivers) > MAX_DRIVERS:
        errors.append(f'Other drivers: at most {MAX_DRIVERS}.')
    return drivers, errors


def drivers_text(drivers):
    return '\n'.join(f"{d['name']}, {d['email']}" if d.get('email') else d['name'] for d in drivers or [])


def check(v, is_new=True):
    """Checks forms.parse can't do. Returns (drivers, errors)."""
    errors = []
    if v.get('requester_email') and not EMAIL.match(v['requester_email']):
        errors.append('Email must look like name@fgcu.edu.')
    if v.get('uin') and not re.fullmatch(r'\d{4,20}', v['uin']):
        errors.append('UIN must be numbers only.')
    if v.get('phone') and len(re.sub(r'\D', '', v['phone'])) < 7:
        errors.append('Phone needs at least 7 digits.')
    if v.get('passengers') is not None and not 1 <= v['passengers'] <= 100:
        errors.append('Passengers must be between 1 and 100.')
    p, r = v.get('pickup_at'), v.get('return_at')
    if isinstance(p, dt.datetime) and isinstance(r, dt.datetime):
        if r <= p:
            errors.append('Return must be after pick up.')
        if is_new and p < dt.datetime.now() - dt.timedelta(hours=1):
            errors.append("Pick up can't be in the past.")
        if r - p > dt.timedelta(days=60):
            errors.append('A reservation can be at most 60 days.')
    drivers, more = parse_drivers(v.get('drivers'))
    return drivers, errors + more


def row_args(v, drivers):
    cut = lambda k, n: (v.get(k) or '').strip()[:n] or None
    vid = v.get('requested_vehicle_id')
    return {'name': cut('requester_name', 100), 'email': cut('requester_email', 150), 'uin': cut('uin', 20),
            'phone': cut('phone', 30), 'dest': cut('destination', 200), 'purpose': cut('purpose', 300),
            'vtype': v.get('vehicle_type') or None, 'pass': v.get('passengers'), 'pick': v['pickup_at'],
            'ret': v['return_at'], 'drivers': json.dumps(drivers), 'notes': (v.get('notes') or '').strip() or None,
            'rvid': int(vid) if vid else None}


# ---------------------------------------------------------------------------
# Emails (queued in wsb.email_outbox; mailer.py sends them when SMTP is set up)
# ---------------------------------------------------------------------------
def approver_emails(q):
    """Tier 1, plus anyone with the "Approve reservations" switch."""
    return [r['email'] for r in q("""
        SELECT DISTINCT u.email FROM wsb.app_user u JOIN wsb.app_role ro USING (role_id)
        WHERE u.active AND u.email IS NOT NULL
          AND (ro.role_name IN ('Top admin', 'Admin')
               OR EXISTS (SELECT 1 FROM wsb.app_user_permission p
                          WHERE p.user_id = u.user_id AND p.permission = 'approve'))
        ORDER BY 1""")]


def approver_link(r):
    return f"{fleet_url()}/reservations/{r['reservation_id']}"


def summary(r):
    lines = [f"Request #{r['reservation_id']}",
             f"Name: {r['requester_name']}", f"Email: {r['requester_email']}", f"UIN: {r['uin']}",
             f"Phone: {r['phone']}", f"Pick up: {when(r['pickup_at'])}", f"Return: {when(r['return_at'])}",
             f"Destination: {r['destination']}"]
    if r.get('purpose'):
        lines.append(f"Purpose: {r['purpose']}")
    if r.get('requested_label'):
        lines.append(f"Vehicle asked for: {r['requested_label']}")
    lines.append(f"Vehicle type: {r['vehicle_type'] or r.get('requested_type') or 'Any'}")
    if r.get('passengers'):
        lines.append(f"Passengers: {r['passengers']}")
    if r.get('drivers'):
        lines.append('Other drivers: ' + '; '.join(
            d['name'] + (f" ({d['email']})" if d.get('email') else '') for d in r['drivers']))
    if r.get('notes'):
        lines.append(f"Notes: {r['notes']}")
    if r.get('vehicle_id'):
        lines.append(f"Vehicle given: {r['vehicle_label']}" + (f" ({r['v_asset']})" if r.get('v_asset') else ''))
    return '\n'.join(lines)


# Who gets each email: the requester, or every approver.
TO_APPROVERS = ('new',)


def email_for(kind, r):
    """(subject, body). kind: received, new, cancelled, or a decision status (Approved, Denied, Needs info).
    The requester has no link to come back to: everything after the request happens by email
    (they reply to the email; MAIL_REPLY_TO, if set, is where replies go)."""
    n, name = r['reservation_id'], r['requester_name']
    note = (r.get('decision_note') or '').strip()
    facts = summary(r)
    if kind == 'received':
        return (f'Thank you for your vehicle request (#{n})',
                f"Hi {name},\n\nThank you for your vehicle request. It is pending review by the fleet managers.\n"
                f"You will get an email when it is approved or denied, or if we need more information.\n\n"
                f"Here is what you sent:\n\n{facts}\n\n"
                f"Need to change or cancel something? Just reply to this email.\n")
    if kind == 'new':
        return (f'New vehicle request from {name} (#{n})',
                f"{name} asked for a vehicle. Approve it, deny it, or ask for missing information here:\n"
                f"{approver_link(r)}\n\n{facts}\n")
    if kind == 'cancelled':
        return (f'Your vehicle reservation was cancelled (#{n})',
                f"Hi {name},\n\nYour vehicle reservation was cancelled." + (f"\n\nNote: {note}" if note else '')
                + f"\n\n{facts}\n\nQuestions? Reply to this email. You can send a new request at any time: "
                  f"{reserve_url()}\n")
    if kind == 'Approved':
        return (f'Your vehicle request is approved (#{n})',
                f"Hi {name},\n\nGood news: your vehicle request is approved." + (f"\n\nMessage: {note}" if note else '')
                + f"\n\n{facts}\n\nNeed to change or cancel it? Reply to this email.\n")
    if kind == 'Denied':
        return (f'Your vehicle request was denied (#{n})',
                f"Hi {name},\n\nSorry, your vehicle request was denied.\n\nReason: {note}\n\n{facts}\n\n"
                f"You can send a new request at any time: {reserve_url()}\n")
    if kind == 'Needs info':
        return (f'We need more information for your vehicle request (#{n})',
                f"Hi {name},\n\nBefore we can approve your vehicle request, we need more information:\n\n{note}\n\n"
                f"Please reply to this email with the answer. We will update your request and let you know.\n\n"
                f"{facts}\n")
    raise ValueError(kind)


def notify(q, run, kind, r):
    """Queue the emails for one step: to every approver (a new request) or to the requester (everything else)."""
    to = approver_emails(q) if kind in TO_APPROVERS else [r['requester_email']]
    for addr in to:
        mailer.queue(run, addr, *email_for(kind, r), reservation_id=r['reservation_id'])


def send_now(q, run, logger):
    """Deliver waiting emails right away when SMTP is set up. A mail problem never breaks the page."""
    try:
        mailer.send_waiting(q, run)
    except Exception:            # noqa: BLE001  (network, login, ...)
        logger.exception('Could not send emails; they stay in the outbox')

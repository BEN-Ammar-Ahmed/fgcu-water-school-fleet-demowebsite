"""Vehicle reservations (/reserve, /reservations). Reaches the main app's helpers through `core`, like admin.py.

Anyone signed in can request a vehicle. The request lands in the inbox of everyone who may approve
(Tier 1, or anyone with the "Approve reservations" switch). They approve it (choosing a vehicle), deny it,
or ask for missing information. Every step adds a line to the history, queues an email to the requester
(mailer.py) and writes to the Activity log. See docs/reservations.md.
"""
import datetime as dt
import json
import re

import psycopg2
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import mailer
from forms import Field, parse

res = Blueprint('res', __name__)
core = None          # the main app module; set by app.py

STATUSES = ['Pending', 'Needs info', 'Approved', 'Denied', 'Cancelled']
OPEN = ('Pending', 'Needs info')            # still waiting for a decision
EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
MAX_DRIVERS = 10


@res.before_request
def _signed_in():
    if not core.current_user():
        return redirect(url_for('login', next=request.path))


@res.app_context_processor
def _waiting_count():
    """How many requests wait for a decision: shown next to Reservations in the top bar for approvers."""
    u = core._user_or_none()
    if not u or not u.can('approve'):
        return {'reservations_waiting': 0}
    try:
        n = core.q("SELECT count(*) n FROM wsb.reservation WHERE status = 'Pending'", one=True)['n']
    except psycopg2.Error:
        core.db().rollback()
        n = 0
    return {'reservations_waiting': n}


@res.app_template_filter('when')
def when(value):
    """'Fri Nov 13, 2026, 8:00 AM'."""
    if not value:
        return ''
    return value.strftime('%a %b %d, %Y, ') + value.strftime('%I:%M %p').lstrip('0')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fields():
    return [Field('requester_name', 'Your name', required=True),
            Field('requester_email', 'Email', required=True, help='Where the answer is sent.'),
            Field('uin', 'UIN', required=True, help='Your FGCU ID number.'),
            Field('phone', 'Phone', required=True),
            Field('pickup_at', 'Pick up', 'datetime', True),
            Field('return_at', 'Return', 'datetime', True),
            Field('destination', 'Destination', required=True, suggest='destination'),
            Field('purpose', 'Purpose', suggest='purpose'),
            Field('vehicle_type', 'Vehicle type', 'select', options=[(t, t) for t in core.VEHICLE_TYPES],
                  help='Leave on "Choose…" if any vehicle works.'),
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


def _check(v, is_new=True):
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
    drivers, more = parse_drivers(v.get('drivers'))
    return drivers, errors + more


def _row_args(v, drivers):
    cut = lambda k, n: (v.get(k) or '').strip()[:n] or None
    return {'name': cut('requester_name', 100), 'email': cut('requester_email', 150), 'uin': cut('uin', 20),
            'phone': cut('phone', 30), 'dest': cut('destination', 200), 'purpose': cut('purpose', 300),
            'vtype': v.get('vehicle_type') or None, 'pass': v.get('passengers'), 'pick': v['pickup_at'],
            'ret': v['return_at'], 'drivers': json.dumps(drivers), 'notes': (v.get('notes') or '').strip() or None}


_SELECT = """SELECT r.*, v.name AS v_name, v.year AS v_year, v.make AS v_make, v.model AS v_model,
                    v.asset_number AS v_asset
             FROM wsb.reservation r LEFT JOIN wsb.vehicle v ON v.vehicle_id = r.vehicle_id"""


def _label(r):
    r['vehicle_label'] = core.display_name({'name': r['v_name'], 'year': r['v_year'], 'make': r['v_make'],
                                            'model': r['v_model'], 'vehicle_id': r['vehicle_id']}) \
        if r.get('vehicle_id') else None
    return r


def _get(rid):
    r = core.q(_SELECT + ' WHERE r.reservation_id = %s', (rid,), one=True)
    return _label(r) if r else None


def _event(rid, by, action, note=None):
    core.run('INSERT INTO wsb.reservation_event (reservation_id, by_name, action, note) VALUES (%s, %s, %s, %s)',
             (rid, by, action, note))


def approver_emails():
    return [r['email'] for r in core.q("""
        SELECT DISTINCT u.email FROM wsb.app_user u JOIN wsb.app_role ro USING (role_id)
        WHERE u.active AND u.email IS NOT NULL
          AND (ro.role_name IN ('Top admin', 'Admin')
               OR EXISTS (SELECT 1 FROM wsb.app_user_permission p
                          WHERE p.user_id = u.user_id AND p.permission = 'approve'))
        ORDER BY 1""")]


def vehicle_options(r):
    """Vehicles that can be reserved, the requested type first. booked = already approved for part of that time."""
    rows = core.q("""
        SELECT v.vehicle_id, v.name, v.year, v.make, v.model, v.notes, v.asset_number, v.vehicle_type, v.status,
               EXISTS (SELECT 1 FROM wsb.reservation o
                       WHERE o.vehicle_id = v.vehicle_id AND o.status = 'Approved'
                         AND o.reservation_id <> %(rid)s
                         AND o.pickup_at < %(ret)s AND o.return_at > %(pick)s) AS booked
        FROM wsb.vehicle v
        WHERE v.active AND v.status NOT IN ('Retired', 'Out of Service')
        ORDER BY (v.vehicle_type = %(vtype)s) DESC, 10, v.vehicle_type, v.year DESC NULLS LAST""",
                  {'rid': r['reservation_id'], 'ret': r['return_at'], 'pick': r['pickup_at'],
                   'vtype': r['vehicle_type'] or ''})
    for o in rows:
        o['label'] = core.display_name(o)
    return rows


def _summary(r):
    lines = [f"Request #{r['reservation_id']}",
             f"Name: {r['requester_name']}", f"Email: {r['requester_email']}", f"UIN: {r['uin']}",
             f"Phone: {r['phone']}", f"Pick up: {when(r['pickup_at'])}", f"Return: {when(r['return_at'])}",
             f"Destination: {r['destination']}"]
    if r.get('purpose'):
        lines.append(f"Purpose: {r['purpose']}")
    lines.append(f"Vehicle type: {r['vehicle_type'] or 'Any'}")
    if r.get('passengers'):
        lines.append(f"Passengers: {r['passengers']}")
    if r.get('drivers'):
        lines.append('Other drivers: ' + '; '.join(
            d['name'] + (f" ({d['email']})" if d.get('email') else '') for d in r['drivers']))
    if r.get('notes'):
        lines.append(f"Notes: {r['notes']}")
    if r.get('vehicle_label'):
        lines.append(f"Vehicle: {r['vehicle_label']}" + (f" ({r['v_asset']})" if r.get('v_asset') else ''))
    return '\n'.join(lines)


def email_for(kind, r):
    """(subject, body) for one email. kind: received, new, updated, cancelled, or a decision status."""
    n, name = r['reservation_id'], r['requester_name']
    link = url_for('res.detail', rid=n, _external=True)
    note = (r.get('decision_note') or '').strip()
    facts = _summary(r)
    if kind == 'received':
        return (f'We got your vehicle request (#{n})',
                f"Hi {name},\n\nWe received your vehicle request. You will get another email when it is approved "
                f"or denied, or if we need more information.\n\n{facts}\n\nSee it any time: {link}\n")
    if kind == 'new':
        return (f'New vehicle request from {name} (#{n})',
                f"{name} asked for a vehicle. Approve it, deny it, or ask for missing information here:\n{link}\n\n{facts}\n")
    if kind == 'updated':
        return (f'Vehicle request #{n} was updated',
                f"{name} updated their vehicle request. It is waiting for a decision again:\n{link}\n\n{facts}\n")
    if kind == 'cancelled':
        return (f'Vehicle request #{n} was cancelled',
                f"{name} cancelled their vehicle request. The vehicle is free again for that time.\n\n{facts}\n")
    if kind == 'Approved':
        return (f'Your vehicle request is approved (#{n})',
                f"Hi {name},\n\nYour vehicle request is approved." + (f"\n\nMessage: {note}" if note else '')
                + f"\n\n{facts}\n\nSee it any time: {link}\n")
    if kind == 'Denied':
        return (f'Your vehicle request was denied (#{n})',
                f"Hi {name},\n\nSorry, your vehicle request was denied.\n\nReason: {note}\n\n{facts}\n\n"
                f"You can send a new request at any time.\n")
    if kind == 'Needs info':
        return (f'We need more information for your vehicle request (#{n})',
                f"Hi {name},\n\nBefore we can approve your vehicle request, we need more information:\n\n{note}\n\n"
                f"Update your request here: {url_for('res.edit', rid=n, _external=True)}\n\n{facts}\n")
    raise ValueError(kind)


def _send_now():
    """Deliver waiting emails right away when SMTP is set up. A mail problem never breaks the page."""
    try:
        mailer.send_waiting(core.q, core.run)
    except Exception:            # noqa: BLE001  (network, login, ...)
        core.app.logger.exception('Could not send emails; they stay in the outbox')


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@res.route('/reserve', methods=['GET', 'POST'])
def request_form():
    u = core.current_user()
    g.page_label = 'Request a vehicle'
    fields, errors = _fields(), []
    if request.method == 'POST':
        values, errors = parse(fields, request.form)
        drivers, more = _check(values)
        errors += more
        if not errors:
            a = _row_args(values, drivers)
            a['by'] = u.user_id
            rid = core.run("""INSERT INTO wsb.reservation
                (requested_by, requester_name, requester_email, uin, phone, destination, purpose, vehicle_type,
                 passengers, pickup_at, return_at, drivers, notes)
                VALUES (%(by)s, %(name)s, %(email)s, %(uin)s, %(phone)s, %(dest)s, %(purpose)s, %(vtype)s,
                        %(pass)s, %(pick)s, %(ret)s, %(drivers)s, %(notes)s)
                RETURNING reservation_id""", a)['reservation_id']
            _event(rid, u.full_name, 'Requested')
            r = _get(rid)
            mailer.queue(core.run, r['requester_email'], *email_for('received', r), reservation_id=rid)
            for to in approver_emails():
                mailer.queue(core.run, to, *email_for('new', r), reservation_id=rid)
            core.log_activity('reservation', f"Requested a vehicle (#{rid}) for {when(r['pickup_at'])}: {r['destination']}")
            _send_now()
            flash('Request sent. You will get an email when it is approved or denied, or if more information is needed.', 'ok')
            return redirect(url_for('res.detail', rid=rid))
    else:
        values = {'requester_name': u.full_name, 'requester_email': u.email or ''}
    return render_template('form_entry.html', title='Request a vehicle', fields=fields, values=values, errors=errors,
                           intro='Fill this in and it goes to the fleet managers. You get an email when they '
                                 'approve or deny it, or if they need more information.',
                           cancel=url_for('res.mine'), submit_label='Send request')


@res.route('/reservations')
def inbox():
    u = core.current_user()
    if not u.can('approve'):
        return redirect(url_for('res.mine'))
    g.page_label = 'Reservations'
    status = request.args.get('status', 'Pending')
    if status not in STATUSES + ['All']:
        status = 'Pending'
    counts = {r['status']: r['n'] for r in core.q('SELECT status, count(*) n FROM wsb.reservation GROUP BY status')}
    order = 'r.pickup_at ASC' if status in OPEN else 'r.pickup_at DESC'
    rows = [_label(r) for r in core.q(
        _SELECT + f" WHERE (%(s)s = 'All' OR r.status = %(s)s) ORDER BY {order} LIMIT 300", {'s': status})]
    return render_template('reservations.html', mode='inbox', rows=rows, status=status, counts=counts,
                           tabs=STATUSES + ['All'])


@res.route('/reservations/mine')
def mine():
    u = core.current_user()
    g.page_label = 'My vehicle requests'
    rows = [_label(r) for r in core.q(_SELECT + ' WHERE r.requested_by = %s ORDER BY r.created_at DESC LIMIT 300',
                                      (u.user_id,))]
    return render_template('reservations.html', mode='mine', rows=rows)


def _load(rid):
    u = core.current_user()
    r = _get(rid)
    if not r:
        abort(404)
    is_mine = r['requested_by'] == u.user_id
    if not (is_mine or u.can('approve')):
        abort(403)
    return u, r, is_mine


@res.route('/reservations/<int:rid>')
def detail(rid):
    u, r, is_mine = _load(rid)
    g.page_label = f'Reservation #{rid}'
    events = core.q('SELECT * FROM wsb.reservation_event WHERE reservation_id = %s ORDER BY at, event_id', (rid,))
    if u.can('approve'):
        emails = core.q('SELECT * FROM wsb.email_outbox WHERE reservation_id = %s ORDER BY email_id', (rid,))
    else:
        emails = core.q('SELECT * FROM wsb.email_outbox WHERE reservation_id = %s AND lower(to_email) = lower(%s) '
                        'ORDER BY email_id', (rid, r['requester_email']))
    can_decide = u.can('approve') and r['status'] in OPEN
    return render_template('reservation.html', r=r, is_mine=is_mine, events=events, emails=emails,
                           can_decide=can_decide, vehicles=vehicle_options(r) if can_decide else [],
                           open=OPEN, mail_on=mailer.configured(),
                           can_cancel=is_mine and (r['status'] in OPEN or
                                                   (r['status'] == 'Approved' and r['return_at'] > dt.datetime.now())))


@res.route('/reservations/<int:rid>/decide', methods=['POST'])
def decide(rid):
    u = core.current_user()
    if not u.can('approve'):
        abort(403)
    r = _get(rid)
    if not r:
        abort(404)
    back = redirect(url_for('res.detail', rid=rid))
    if r['status'] not in OPEN:
        flash(f"This request is already {r['status'].lower()}.", 'error')
        return back
    action = request.form.get('action')
    note = (request.form.get('note') or '').strip()[:2000] or None
    vid = None
    if action == 'approve':
        try:
            vid = int(request.form.get('vehicle_id', ''))
        except ValueError:
            flash('Choose the vehicle to give them, then press Approve.', 'error')
            return back
        pick = next((o for o in vehicle_options(r) if o['vehicle_id'] == vid), None)
        if not pick:
            flash("That vehicle can't be reserved.", 'error')
            return back
        if pick['booked']:
            flash(f"{pick['label']} is already reserved for part of that time. Choose another vehicle.", 'error')
            return back
        new = 'Approved'
    elif action in ('deny', 'info'):
        new = 'Denied' if action == 'deny' else 'Needs info'
        if not note:
            flash('Write the reason for denying it. The requester gets it by email.' if action == 'deny'
                  else 'Write what information is missing. The requester gets it by email.', 'error')
            return back
    else:
        abort(400)
    done = core.run("""UPDATE wsb.reservation
                       SET status = %s, vehicle_id = %s, decided_by = %s, decided_at = now(), decision_note = %s,
                           updated_at = now()
                       WHERE reservation_id = %s AND status IN ('Pending', 'Needs info')
                       RETURNING reservation_id""", (new, vid, u.full_name, note, rid))
    if not done:
        flash('Someone else decided this request first.', 'error')
        return back
    _event(rid, u.full_name, new, note)
    old = r['status']
    r = _get(rid)
    mailer.queue(core.run, r['requester_email'], *email_for(new, r), reservation_id=rid)
    details = [{'field': 'Status', 'old': old, 'new': new}]
    if r['vehicle_label']:
        details.append({'field': 'Vehicle', 'old': '', 'new': r['vehicle_label']})
    verb = {'Approved': 'Approved', 'Denied': 'Denied', 'Needs info': 'Asked for more information on'}[new]
    core.log_activity('reservation', f"{verb} vehicle request #{rid} from {r['requester_name']} "
                                     f"({when(r['pickup_at'])})", details=details)
    _send_now()
    flash({'Approved': f"Approved. {r['requester_name']} gets an email with the details.",
           'Denied': f"Denied. {r['requester_name']} gets an email with your reason.",
           'Needs info': f"Sent. {r['requester_name']} gets an email asking for the missing information."}[new], 'ok')
    return back


@res.route('/reservations/<int:rid>/edit', methods=['GET', 'POST'])
def edit(rid):
    u, r, is_mine = _load(rid)
    if not is_mine:
        abort(403)
    if r['status'] not in OPEN:
        flash(f"This request is {r['status'].lower()} and can't be changed. Send a new request instead.", 'error')
        return redirect(url_for('res.detail', rid=rid))
    g.page_label = f'Update reservation #{rid}'
    fields, errors = _fields(), []
    if request.method == 'POST':
        values, errors = parse(fields, request.form)
        drivers, more = _check(values, is_new=False)
        errors += more
        if not errors:
            a = _row_args(values, drivers)
            a['rid'] = rid
            core.run("""UPDATE wsb.reservation SET requester_name = %(name)s, requester_email = %(email)s,
                            uin = %(uin)s, phone = %(phone)s, destination = %(dest)s, purpose = %(purpose)s,
                            vehicle_type = %(vtype)s, passengers = %(pass)s, pickup_at = %(pick)s,
                            return_at = %(ret)s, drivers = %(drivers)s, notes = %(notes)s,
                            status = 'Pending', updated_at = now()
                        WHERE reservation_id = %(rid)s""", a)
            _event(rid, u.full_name, 'Updated', 'Sent back for a decision.' if r['status'] == 'Needs info' else None)
            r = _get(rid)
            for to in approver_emails():
                mailer.queue(core.run, to, *email_for('updated', r), reservation_id=rid)
            core.log_activity('reservation', f'Updated vehicle request #{rid}')
            _send_now()
            flash('Request updated. It is waiting for a decision again.', 'ok')
            return redirect(url_for('res.detail', rid=rid))
    else:
        values = dict(r, drivers=drivers_text(r['drivers']))
    intro = None
    if r['status'] == 'Needs info' and r['decision_note']:
        intro = f"They asked: {r['decision_note']}"
    return render_template('form_entry.html', title=f'Update request #{rid}', fields=fields, values=values,
                           errors=errors, intro=intro, cancel=url_for('res.detail', rid=rid),
                           submit_label='Send updated request')


@res.route('/reservations/<int:rid>/cancel', methods=['POST'])
def cancel(rid):
    u, r, is_mine = _load(rid)
    if not is_mine:
        abort(403)
    was = r['status']
    if not (was in OPEN or (was == 'Approved' and r['return_at'] > dt.datetime.now())):
        flash(f"This request is {was.lower()} and can't be cancelled.", 'error')
        return redirect(url_for('res.detail', rid=rid))
    core.run("UPDATE wsb.reservation SET status = 'Cancelled', updated_at = now() WHERE reservation_id = %s", (rid,))
    _event(rid, u.full_name, 'Cancelled')
    if was == 'Approved':
        for to in approver_emails():
            mailer.queue(core.run, to, *email_for('cancelled', r), reservation_id=rid)
    core.log_activity('reservation', f'Cancelled vehicle request #{rid}',
                      details=[{'field': 'Status', 'old': was, 'new': 'Cancelled'}])
    _send_now()
    flash('Request cancelled.', 'ok')
    return redirect(url_for('res.detail', rid=rid))

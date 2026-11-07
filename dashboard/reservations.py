"""The approvers' reservation inbox on the fleet site (/reservations). Requests come from the separate
request site (reserve_app.py). Shared logic: reservation_core.py. See docs/reservations.md.

Who: Tier 1, or anyone with the "Approve reservations" switch. They approve (choosing the vehicle: the one the
requester picked is pre-selected), deny, or ask for more information. Every step adds a history line, queues an
email to the requester and writes to the Activity log.
"""
import psycopg2
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import mailer
import reservation_core as rc
from common import reserve_url

res = Blueprint('res', __name__)
core = None          # the main app module; set by app.py


@res.before_request
def _approvers_only():
    u = core.current_user()
    if not u:
        return redirect(url_for('login', next=request.path))
    if not u.can('approve'):
        abort(403)
    return None


@res.app_context_processor
def _reservation_links():
    """Top bar: how many requests wait (approvers), and where the request site is (everyone)."""
    u = core._user_or_none()
    n = 0
    if u and u.can('approve'):
        try:
            n = core.q("SELECT count(*) n FROM wsb.reservation WHERE status = 'Pending'", one=True)['n']
        except psycopg2.Error:
            core.db().rollback()
    return {'reservations_waiting': n, 'reserve_site': reserve_url()}


res.add_app_template_filter(rc.when, 'when')


@res.route('/reservations')
def inbox():
    g.page_label = 'Reservations'
    status = request.args.get('status', 'Pending')
    if status not in rc.STATUSES + ['All']:
        status = 'Pending'
    counts = {r['status']: r['n'] for r in core.q('SELECT status, count(*) n FROM wsb.reservation GROUP BY status')}
    order = 'r.pickup_at ASC' if status in rc.OPEN else 'r.pickup_at DESC'
    rows = core.q(rc.SELECT + f" WHERE (%(s)s = 'All' OR r.status = %(s)s) ORDER BY {order} LIMIT 300", {'s': status})
    return render_template('reservations.html', rows=rows, status=status, counts=counts, tabs=rc.STATUSES + ['All'])


def _load(rid):
    r = rc.get(core.q, rid)
    if not r:
        abort(404)
    return r


@res.route('/reservations/<int:rid>')
def detail(rid):
    r = _load(rid)
    g.page_label = f'Reservation #{rid}'
    events = core.q('SELECT * FROM wsb.reservation_event WHERE reservation_id = %s ORDER BY at, event_id', (rid,))
    emails = core.q('SELECT * FROM wsb.email_outbox WHERE reservation_id = %s ORDER BY email_id', (rid,))
    can_decide = r['status'] in rc.OPEN
    options = rc.vehicles(core.q, r['pickup_at'], r['return_at'], rid, for_requesters=False,
                          vtype=r['vehicle_type'] or r['requested_type']) if can_decide else []
    picked = next((o['vehicle_id'] for o in options
                   if o['vehicle_id'] == r['requested_vehicle_id'] and not o['booked']), None)
    return render_template('reservation.html', r=r, events=events, emails=emails, can_decide=can_decide,
                           vehicles=options, picked=picked, mail_on=mailer.configured())


@res.route('/reservations/<int:rid>/decide', methods=['POST'])
def decide(rid):
    u = core.current_user()
    r = _load(rid)
    back = redirect(url_for('res.detail', rid=rid))
    if r['status'] not in rc.OPEN:
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
        pick = next((o for o in rc.vehicles(core.q, r['pickup_at'], r['return_at'], rid, for_requesters=False)
                     if o['vehicle_id'] == vid), None)
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
    rc.event(core.run, rid, u.full_name, new, note)
    old, r = r['status'], rc.get(core.q, rid)
    rc.notify(core.q, core.run, new, r)
    details = [{'field': 'Status', 'old': old, 'new': new}]
    if r['vehicle_id']:
        details.append({'field': 'Vehicle', 'old': r['requested_label'] or 'Any', 'new': r['vehicle_label']})
    verb = {'Approved': 'Approved', 'Denied': 'Denied', 'Needs info': 'Asked for more information on'}[new]
    core.log_activity('reservation', f"{verb} vehicle request #{rid} from {r['requester_name']} "
                                     f"({rc.when(r['pickup_at'])})", details=details)
    rc.send_now(core.q, core.run, core.app.logger)
    flash({'Approved': f"Approved. {r['requester_name']} gets an email with the details.",
           'Denied': f"Denied. {r['requester_name']} gets an email with your reason.",
           'Needs info': f"Sent. {r['requester_name']} gets an email asking for the missing information."}[new], 'ok')
    return back

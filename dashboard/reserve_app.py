"""Vehicle request site: a separate website where anyone with the link can request a vehicle.

Run:  python reserve_app.py      then open http://localhost:5001
Uses the same database as the fleet site (DATABASE_URL in dashboard/.env). Requests land in the fleet site's
Reservations inbox (reservations.py). No account is needed:
the requester gets a thank-you page and emails; anything after that (missing information, changes,
cancelling) happens by email, and an approver updates the request on the fleet site. See docs/reservations.md.

Shows only what a requester needs: vehicle names, types and locations. No VINs, plates, costs or driver data.
"""
import collections
import datetime as dt
import os
import secrets
import time
from pathlib import Path

import psycopg2
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from jinja2 import ChoiceLoader, FileSystemLoader

import reservation_core as rc
from common import VEHICLE_TYPES, Database, database_url, fleet_url, load_env_file, static_url_for
from forms import parse

HERE = Path(__file__).parent
load_env_file(HERE / '.env')
DB_URL = database_url()

app = Flask(__name__, static_folder='static')
# Its own pages first, then the shared ones (form_entry.html, _icons.html, _res.html).
app.jinja_loader = ChoiceLoader([FileSystemLoader(HERE / 'reserve_templates'), FileSystemLoader(HERE / 'templates')])
app.secret_key = os.environ.get('RESERVE_SECRET_KEY') or secrets.token_hex(32)
app.config.update(MAX_CONTENT_LENGTH=64 * 1024,
                  SESSION_COOKIE_NAME='wsb_reserve',      # never mixes with the fleet site's sign-in cookie
                  SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_HTTPONLY=True)
app.config.setdefault('CSRF_ENABLED', True)
app.add_template_filter(rc.when, 'when')
static_url_for(app)

PER_IP_PER_HOUR = 10       # new requests from one address
PER_EMAIL_PER_DAY = 5      # new requests for one email address
_recent = collections.defaultdict(collections.deque)
TYPE_ICONS = {'Boat': 'boat', 'Car': 'car', 'Truck': 'truck', 'Trailer': 'trailer', 'Golf Cart': 'cart'}


# ---------------------------------------------------------------------------
# Database, form protection, headers
# ---------------------------------------------------------------------------
DATABASE = Database(lambda: DB_URL, lambda: app.config.get('DB_POOL', True), maxconn=3)   # connections kept open
app.teardown_appcontext(DATABASE.release)


def q(sql, args=(), one=False):
    return DATABASE.q(sql, args, one)


def run(sql, args=()):
    return DATABASE.run(sql, args)


def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']


app.jinja_env.globals.update(csrf_token=csrf_token, type_icons=TYPE_ICONS, fleet_url=fleet_url,
                              contact_email=os.environ.get('FLEET_CONTACT_EMAIL', ''), this_year=dt.date.today().year)


@app.before_request
def check_csrf():
    if request.method != 'POST' or not app.config['CSRF_ENABLED']:
        return None
    sent = request.form.get('csrf_token') or ''
    if not session.get('_csrf') or not secrets.compare_digest(sent, session['_csrf']):
        return error_page(400, 'This page was open too long. Go back, refresh the page, and try again.')
    return None


@app.after_request
def headers(resp):
    resp.headers['Referrer-Policy'] = 'no-referrer'          # private links never leak to other sites
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    if request.path == '/thanks':
        resp.headers['Cache-Control'] = 'no-store'
    return resp


def error_page(code, msg=None):
    default = {400: "Something in that request didn't look right.", 404: "That page or link doesn't exist.",
               413: 'That was too much text.', 429: 'Too many requests. Please try again later.',
               503: "The vehicle list can't be reached right now. Try again in a few minutes."}
    return render_template('r_error.html', code=code, msg=msg or default.get(code, 'Something went wrong.')), code


for _code in (400, 404, 405, 413):
    app.register_error_handler(_code, lambda e, c=_code: error_page(c))


@app.errorhandler(psycopg2.OperationalError)
def database_down(e):
    app.logger.error('Database unreachable: %s', e)
    return error_page(503)


@app.errorhandler(500)
def server_error(e):
    app.logger.exception('Unhandled error on %s', request.path)
    return error_page(500, 'Something went wrong on our side. Please try again.')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _when_arg(src, name):
    try:
        return dt.datetime.fromisoformat((src.get(name) or '').strip())
    except ValueError:
        return None


def _window_problem(pick, ret):
    if not pick or not ret:
        return 'Choose both a pick-up and a return time.'
    if ret <= pick:
        return 'Return must be after pick up.'
    if pick < dt.datetime.now() - dt.timedelta(hours=1):
        return "Pick up can't be in the past."
    if ret - pick > dt.timedelta(days=60):
        return 'A reservation can be at most 60 days.'
    return None


def _choices(pick, ret, exclude_rid=0):
    """(value, label) for the Vehicle list: the vehicles free for that time."""
    if not pick or not ret or ret <= pick:
        return []
    return [(v['vehicle_id'], f"{v['label']} · {v['vehicle_type']}" + (f" · {v['location']}" if v['location'] else ''))
            for v in rc.vehicles(q, pick, ret, exclude_rid)]


def _too_many(email):
    now = time.monotonic()
    hits = _recent[request.remote_addr or '?']
    while hits and now - hits[0] > 3600:
        hits.popleft()
    if len(hits) >= PER_IP_PER_HOUR:
        return True
    n = q("""SELECT count(*) n FROM wsb.reservation
             WHERE lower(requester_email) = lower(%s) AND created_at > now() - interval '1 day'""",
          (email or '',), one=True)['n']
    return n >= PER_EMAIL_PER_DAY


def _form_page(title, fields, values, errors, cancel, submit_label, intro=None):
    return render_template('form_entry.html', title=title, fields=fields, values=values, errors=errors, intro=intro,
                           cancel=cancel, submit_label=submit_label, honeypot=True)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    """Step 1: when, and which vehicles are free then."""
    pick, ret = _when_arg(request.args, 'pickup_at'), _when_arg(request.args, 'return_at')
    vtype = request.args.get('type') if request.args.get('type') in VEHICLE_TYPES else ''
    asked = 'pickup_at' in request.args
    problem = _window_problem(pick, ret) if asked else None
    free = rc.vehicles(q, pick, ret, vtype=vtype) if asked and not problem else None
    fmt = lambda d: d.strftime('%Y-%m-%dT%H:%M') if d else ''
    return render_template('index.html', types=VEHICLE_TYPES, vtype=vtype, problem=problem, free=free,
                           pick_dt=pick, ret_dt=ret,
                           pickup=fmt(pick) or request.args.get('pickup_at', ''),
                           ret=fmt(ret) or request.args.get('return_at', ''))


@app.route('/request', methods=['GET', 'POST'])
def request_form():
    """Step 2: who, where, and the details. Sends the request to the approvers' inbox."""
    src = request.form if request.method == 'POST' else request.args
    pick, ret = _when_arg(src, 'pickup_at'), _when_arg(src, 'return_at')
    fields = rc.fields(_choices(pick, ret))
    errors = []
    if request.method == 'POST':
        if request.form.get('website'):                       # hidden field only robots fill in
            abort(400)
        values, errors = parse(fields, request.form)
        drivers, more = rc.check(values)
        errors += more
        if values.get('requested_vehicle_id') and isinstance(pick, dt.datetime) and isinstance(ret, dt.datetime) \
                and not rc.is_free(q, int(values['requested_vehicle_id']), pick, ret):
            errors.append('That vehicle is no longer free for those times. Choose another, or leave it on "Choose…".')
        if not errors and _too_many(values.get('requester_email')):
            return error_page(429)
        if not errors:
            a = rc.row_args(values, drivers)
            a.update(token=rc.new_token(), ip=(request.remote_addr or '')[:45])
            if a['rvid'] and not a['vtype']:
                a['vtype'] = q('SELECT vehicle_type FROM wsb.vehicle WHERE vehicle_id = %s', (a['rvid'],), one=True)['vehicle_type']
            rid = run("""INSERT INTO wsb.reservation
                (requester_name, requester_email, uin, phone, destination, purpose, vehicle_type, passengers,
                 pickup_at, return_at, drivers, notes, requested_vehicle_id, public_token, request_ip)
                VALUES (%(name)s, %(email)s, %(uin)s, %(phone)s, %(dest)s, %(purpose)s, %(vtype)s, %(pass)s,
                        %(pick)s, %(ret)s, %(drivers)s, %(notes)s, %(rvid)s, %(token)s, %(ip)s)
                RETURNING reservation_id""", a)['reservation_id']
            _recent[request.remote_addr or '?'].append(time.monotonic())
            rc.event(run, rid, a['name'], 'Requested')
            r = rc.get(q, rid)
            rc.notify(q, run, 'received', r)
            rc.notify(q, run, 'new', r)
            rc.send_now(q, run, app.logger)
            # The thank-you page shows what they sent; it is kept in their own browser session only.
            session['sent'] = {'id': rid, 'name': r['requester_name'], 'email': r['requester_email'],
                               'vehicle': r['requested_label'] or f"Any {(r['vehicle_type'] or 'vehicle').lower()}",
                               'pickup': rc.when(r['pickup_at']), 'return': rc.when(r['return_at']),
                               'destination': r['destination']}
            return redirect(url_for('thanks'))
    else:
        values = {'pickup_at': pick, 'return_at': ret,
                  'requested_vehicle_id': request.args.get('vehicle', ''),
                  'vehicle_type': request.args.get('type') if request.args.get('type') in VEHICLE_TYPES else None}
    back = url_for('index', pickup_at=src.get('pickup_at', ''), return_at=src.get('return_at', ''))
    return _form_page('Your details', fields, values, errors, back, 'Send request',
                      intro='The vehicle list shows what is free for the times you chose. If you change the times, '
                            'go back to see what is free then.')


@app.route('/thanks')
def thanks():
    sent = session.get('sent')
    if not sent:
        return redirect(url_for('index'))
    return render_template('thanks.html', sent=sent)


if __name__ == '__main__':
    port = int(os.environ.get('RESERVE_PORT', 5001))
    where = 'Supabase' if 'supabase' in DB_URL else 'local PostgreSQL'
    print(f'Water School vehicle request site ({where}): http://localhost:{port}')
    app.run(host='127.0.0.1', port=port, debug=False)

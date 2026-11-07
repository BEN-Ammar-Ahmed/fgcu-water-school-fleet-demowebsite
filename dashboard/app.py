"""Water School Fleet dashboard (prototype).

Run:  python app.py      then open http://localhost:5000
Database connection comes from the DATABASE_URL environment variable
(default: your local water_school_fleet database).
"""
import os, sys, uuid, datetime, secrets
from functools import wraps
from pathlib import Path

import psycopg2, psycopg2.extras
from flask import (Flask, render_template, request, redirect, url_for, session,
                   flash, abort, send_from_directory, g, jsonify)
from werkzeug.utils import secure_filename

from changes import diff as change_diff
from forms import Field, parse
from search import KINDS, run_search
from tiers import LEVEL_LABELS, doc_levels, level_for_role, load_user, user_for_email

HERE = Path(__file__).parent
UPLOADS = HERE / 'uploads'


def load_env_file(path):
    """Read KEY=value lines from dashboard/.env (kept out of git) into the environment."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env_file(HERE / '.env')
# Supabase: put the "Session pooler" connection string in dashboard/.env as DATABASE_URL=...
# Without it, the app falls back to your local PostgreSQL.
DB_URL = os.environ.get('DATABASE_URL', 'dbname=water_school_fleet user=postgres host=localhost')
if 'supabase' in DB_URL and 'sslmode' not in DB_URL:
    DB_URL += ('&' if '?' in DB_URL else '?') + 'sslmode=require'
DB_WHERE = 'Supabase' if 'supabase' in DB_URL else 'local PostgreSQL'

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', uuid.uuid4().hex)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20 MB per upload

# ---------------------------------------------------------------------------
# Access tiers (see tiers.py). Real FGCU sign-in will call sign_in_email().
# ---------------------------------------------------------------------------
VEHICLE_TYPES = ['Boat', 'Car', 'Truck', 'Trailer', 'Golf Cart', 'ATV', 'Other']
STATUSES = ['Available', 'In Use', 'In Maintenance', 'Out of Service', 'Retired']
DOC_TYPES = ['Registration', 'Insurance - Auto Liability', 'Insurance - General Liability',
             'Insurance - Workers Comp', 'Title', 'Inspection', 'Manual', 'Other']
ALLOWED_EXT = {'pdf', 'png', 'jpg', 'jpeg', 'docx', 'xlsx', 'doc', 'xls', 'txt'}


def current_user():
    """The signed-in person, or None. A missing or deactivated user is signed out."""
    if 'user' not in g:
        uid = session.get('user_id')
        g.user = load_user(q, uid) if uid else None
        if uid and g.user is None:
            session.clear()
    return g.user


def require(perm=None, delete=False, licenses=False, admin=False):
    """Signed in, plus (optionally) one ability from tiers.PERMS, delete rights, license access or Tier 1."""
    def deco(f):
        @wraps(f)
        def inner(*a, **k):
            u = current_user()
            if not u:
                return redirect(url_for('login', next=request.path))
            if ((perm and not u.can(perm)) or (delete and not u.can_delete)
                    or (licenses and not u.can_see_licenses) or (admin and not u.is_admin)):
                abort(403)
            return f(*a, **k)
        return inner
    return deco


def safe_next(target):
    """A path on this site to go to after sign-in, or None. Blocks links to other sites."""
    from urllib.parse import urlsplit
    if not target or not target.startswith('/') or '\\' in target or any(ord(c) < 32 for c in target):
        return None
    parts = urlsplit(target)
    return target if not parts.scheme and not parts.netloc else None


DEMO_DOMAIN = '@example.edu'   # the demo sign-in only works for the fictional users from 09_demo_users.sql


def sign_in_email(email):
    """The one place a sign-in turns into a session. Real FGCU sign-in calls this later."""
    u = user_for_email(q, email)
    session.clear()
    if u:
        session['user_id'] = u.user_id
    return u


def _user_or_none():
    try:
        return current_user()
    except psycopg2.Error:
        return None


@app.context_processor
def inject():
    return dict(user=_user_or_none(), today=datetime.date.today(), DB_WHERE=DB_WHERE,
                now=datetime.datetime.now(datetime.timezone.utc),
                url_map_endpoints={r.endpoint for r in app.url_map.iter_rules()})


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def db():
    if 'db' not in g:
        g.db = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=10)
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop('db', None)
    if conn is not None:
        conn.close()


def q(sql, args=(), one=False):
    with db().cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall() if cur.description else []
    return (rows[0] if rows else None) if one else rows


def run(sql, args=()):
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            row = cur.fetchone() if cur.description else None
        conn.commit()
        return row
    except psycopg2.Error:
        conn.rollback()
        raise


ACTIVITY_KINDS = ('sign-in', 'sign-out', 'view', 'change', 'download', 'access')


def log_activity(kind, summary, user=None, path=None, details=None):
    """Append one line to wsb.activity_log. details: what an edit changed (changes.diff). Never breaks the page."""
    u = user or current_user()
    try:
        run("""INSERT INTO wsb.activity_log (user_id, username, full_name, kind, summary, path, details)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (u.user_id if u else None, u.username if u else None, u.full_name if u else None,
             kind, str(summary)[:2000], (path or request.full_path)[:300] if request else None,
             psycopg2.extras.Json(details) if details else None))
    except psycopg2.Error:
        app.logger.exception('Could not write the activity log')


PAGE_LABELS = {'dashboard': 'Home', 'help_page': 'Help', 'maintenance_page': 'Maintenance list',
               'documents': 'Documents list'}


@app.after_request
def remember_last_seen(response):
    """Record when each person was last active and what they were looking at (at most once a minute)."""
    u = g.get('user')
    if u and request.method == 'GET' and response.status_code == 200 and request.endpoint not in (None, 'static', 'suggest_json'):
        label = g.get('page_label') or PAGE_LABELS.get(request.endpoint) or request.path
        try:
            run("""UPDATE wsb.app_user SET last_seen = now(), last_page = %s
                   WHERE user_id = %s AND (last_seen IS NULL OR last_seen < now() - interval '60 seconds'
                                           OR last_page IS DISTINCT FROM %s)""", (label[:200], u.user_id, label[:200]))
        except psycopg2.Error:
            app.logger.exception('Could not update last_seen')
    return response


def ensure_setup():
    with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute((HERE / 'setup.sql').read_text(encoding='utf-8'))


def display_name(v):
    """The vehicle's Name (edited on its Edit page), else year make model, e.g. '2013 Ford F150 4x4'."""
    if (v.get('name') or '').strip():
        return v['name'].strip()
    return ' '.join(str(x) for x in (v.get('year'), v.get('make'), v.get('model')) if x) or f"Vehicle #{v['vehicle_id']}"


app.jinja_env.globals['display_name'] = display_name


# ---------------------------------------------------------------------------
# Form protection (CSRF): every form that saves something carries a secret from this person's
# session, so another website can't make a signed-in person's browser submit a form here.
# ---------------------------------------------------------------------------
def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']


app.jinja_env.globals['csrf_token'] = csrf_token
app.config.setdefault('CSRF_ENABLED', True)


@app.before_request
def check_csrf():
    if request.method != 'POST' or not app.config['CSRF_ENABLED']:
        return None
    sent = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token') or ''
    if not session.get('_csrf') or not secrets.compare_digest(sent, session['_csrf']):
        return error_page(400, 'This page was open too long or came from somewhere else. '
                               'Go back, refresh the page, and try again.')
    return None
app.jinja_env.globals['change_text'] = __import__('changes').text

MAINT_SQL = """
SELECT r.*, v.vehicle_type, v.make, v.model, v.year, v.notes, v.name, v.location, v.current_mileage,
       (r.last_completed_date + make_interval(months => r.time_interval_months))::date AS due_date
FROM wsb.maintenance_rule r JOIN wsb.vehicle v USING (vehicle_id)
WHERE r.enabled AND v.active {extra}
"""


MILES_SOON = 500   # "Due soon" when this close to the mileage limit


def maint_status(r):
    """Worst of the date check and the mileage check. Unknown only when neither can be worked out."""
    found = []
    if r.get('due_date'):
        days = (r['due_date'] - datetime.date.today()).days
        r['days'] = days
        found.append('Overdue' if days < 0 else 'Due soon' if days <= 30 else 'OK')
    if r.get('mileage_interval') and r.get('last_completed_mileage') is not None and r.get('current_mileage') is not None:
        left = r['last_completed_mileage'] + r['mileage_interval'] - r['current_mileage']
        r['miles_left'] = left
        r['due_mileage'] = r['last_completed_mileage'] + r['mileage_interval']
        found.append('Overdue' if left < 0 else 'Due soon' if left <= MILES_SOON else 'OK')
    for s in ('Overdue', 'Due soon', 'OK'):
        if s in found:
            return s
    return 'Unknown'


def maintenance(extra='', args=()):
    rows = q(MAINT_SQL.format(extra=extra), args)
    order = {'Overdue': 0, 'Due soon': 1, 'Unknown': 2, 'OK': 3}
    for r in rows:
        r['status'] = maint_status(r)
    rows.sort(key=lambda r: (order[r['status']], r['due_date'] or datetime.date.max))
    return rows


# ---------------------------------------------------------------------------
# Sign-in (FGCU placeholder + account picker for the test accounts)
# ---------------------------------------------------------------------------
@app.route('/login')
def login():
    return render_template('login.html', next=request.args.get('next', ''))


@app.route('/login/fgcu')
def login_fgcu():
    # Placeholder: FGCU sign-in (likely Microsoft Entra ID) gets connected here later.
    return redirect(url_for('login_account', next=request.args.get('next', '')))


@app.route('/login/account', methods=['GET', 'POST'])
def login_account():
    nxt = request.values.get('next') or ''
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        u = sign_in_email(email) if email.lower().endswith(DEMO_DOMAIN) else None
        if not u:
            return render_template('no_access.html'), 403
        log_activity('sign-in', 'Signed in', user=u)
        return redirect(safe_next(nxt) or url_for('dashboard'))
    people = q("""SELECT u.full_name, u.email, r.role_name FROM wsb.app_user u
                  JOIN wsb.app_role r USING (role_id) WHERE u.active AND lower(u.email) LIKE %s
                  ORDER BY r.role_name, u.full_name""", ('%' + DEMO_DOMAIN,))
    for p in people:
        p['level_label'] = LEVEL_LABELS[level_for_role(p['role_name'])]
    return render_template('account_signin.html', people=people, next=nxt)


@app.route('/logout')
def logout():
    u = current_user()
    if u:
        log_activity('sign-out', 'Signed out', user=u)
        try:
            run('UPDATE wsb.app_user SET last_seen = NULL WHERE user_id = %s', (u.user_id,))
        except psycopg2.Error:
            pass
        g.user = None   # so the after-request hook doesn't mark them active again
    session.clear()
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route('/')
@require()
def dashboard():
    """Home page: the search, then a short dashboard. Editors get things to act on; viewers get what's available."""
    u = current_user()
    ctx = _search_context('', 'all', {})
    maint = maintenance()
    dash = {'attention': [m for m in maint if m['status'] in ('Overdue', 'Due soon')][:8],
            'out_now': q("""SELECT t.trip_id, t.vehicle_id, t.start_datetime, t.destination,
                                   v.year, v.make, v.model, v.notes, v.name, v.asset_number,
                                   d.first_name || ' ' || d.last_name AS driver_name
                            FROM wsb.trip t JOIN wsb.vehicle v USING (vehicle_id) JOIN wsb.driver d USING (driver_id)
                            WHERE t.end_datetime IS NULL ORDER BY t.start_datetime DESC LIMIT 8""")}
    if u.can_edit:
        dash['mine'] = q("""SELECT at, summary, details FROM wsb.activity_log
                            WHERE user_id = %s AND kind IN ('change', 'access') ORDER BY activity_id DESC LIMIT 6""",
                         (u.user_id,))
    else:
        dash['available'] = q("""SELECT vehicle_id, vehicle_type, year, make, model, notes, name, asset_number, location
                                 FROM wsb.vehicle WHERE active AND status = 'Available'
                                 ORDER BY vehicle_type, year DESC NULLS LAST LIMIT 12""")
        dash['available_total'] = q("SELECT count(*) n FROM wsb.vehicle WHERE active AND status = 'Available'",
                                    one=True)['n']
    return render_template('home.html', searched=False, dash=dash, **ctx)


KIND_LABELS = {'all': 'All', 'vehicles': 'Vehicles', 'trips': 'Trips', 'fuel': 'Fuel',
               'maintenance': 'Maintenance', 'documents': 'Documents', 'drivers': 'Drivers', 'licenses': 'Licenses'}


def _int_arg(name):
    try:
        return int(request.args.get(name, ''))
    except ValueError:
        return None


def _date_arg(name):
    try:
        return datetime.date.fromisoformat(request.args.get(name, ''))
    except ValueError:
        return None


def _search_filters():
    f = {'vehicle_id': _int_arg('vehicle_id'), 'driver_id': _int_arg('driver_id'),
         'date_from': _date_arg('date_from'), 'date_to': _date_arg('date_to')}
    for key, allowed in (('vehicle_type', VEHICLE_TYPES), ('status', STATUSES), ('document_type', DOC_TYPES)):
        if request.args.get(key) in allowed:
            f[key] = request.args[key]
    if request.args.get('location'):
        f['location'] = request.args['location'][:50]
    return {k: v for k, v in f.items() if v is not None}


def _search_context(text, kind, filters):
    u = current_user()
    kinds = [k for k in KINDS if (k != 'licenses' or u.can_see_licenses) and (k != 'drivers' or u.is_admin)]
    maint = maintenance()
    return dict(q=text, kind=kind, filters=filters, kinds=kinds, kind_labels=KIND_LABELS,
                overdue=sum(m['status'] == 'Overdue' for m in maint),
                soon=sum(m['status'] == 'Due soon' for m in maint))


@app.route('/search')
@require()
def search_page():
    u = current_user()
    text = request.args.get('q', '').strip()[:200]
    kind = request.args.get('kind', 'all')
    if kind not in KINDS or (kind == 'licenses' and not u.can_see_licenses) or (kind == 'drivers' and not u.is_admin):
        kind = 'all'
    filters = _search_filters()
    browse = request.args.get('browse') == '1' and kind != 'all'
    if not text and not filters and not browse:
        return redirect(url_for('dashboard'))
    ctx = _search_context(text, kind, filters)
    ctx['browse'] = browse
    ctx['results'] = run_search(q, u, text, kind, filters, browse=browse)
    pairs = lambda xs: [(x, x) for x in xs]
    ctx['opts'] = {
        'vehicles': [(v['vehicle_id'], display_name(v)) for v in q(
            "SELECT vehicle_id, asset_number, year, make, model, notes, name FROM wsb.vehicle ORDER BY vehicle_type, year DESC NULLS LAST")],
        'drivers': [(d['driver_id'], d['name']) for d in q(
            "SELECT driver_id, first_name || ' ' || last_name AS name FROM wsb.driver ORDER BY last_name, first_name")],
        'locations': pairs(r['location'] for r in q(
            "SELECT DISTINCT location FROM wsb.vehicle WHERE location IS NOT NULL ORDER BY 1")),
        'types': pairs(VEHICLE_TYPES), 'statuses': pairs(STATUSES), 'doc_types': pairs(DOC_TYPES),
    }
    confidential = kind == 'licenses' or bool(ctx['results'].get('licenses', {}).get('total'))
    if confidential:   # never copy what a top admin searched for in license records into logs others can read
        g.page_label = 'Search (confidential)'
    else:
        g.page_label = f'Search: {text}' if text else f"Browse: {KIND_LABELS.get(kind, kind)}"
    log_activity('view', g.page_label, path=request.path if confidential else None)
    return render_template('home.html', searched=True, **ctx)


@app.route('/vehicles')
@require()
def vehicles():
    """Old list page: now a vehicle search."""
    args = {'kind': 'vehicles', 'q': request.args.get('q', '')}
    if request.args.get('type'):
        args['vehicle_type'] = request.args['type']
    if request.args.get('status') in STATUSES:
        args['status'] = request.args['status']
    return redirect(url_for('search_page', **args))


@app.route('/vehicles/<int:vid>')
@require()
def vehicle(vid):
    v = q('SELECT * FROM wsb.vehicle WHERE vehicle_id = %s', (vid,), one=True) or abort(404)
    levels = doc_levels(current_user())
    rules = maintenance('AND r.vehicle_id = %s', (vid,)) if v['active'] else         q('SELECT * FROM wsb.maintenance_rule WHERE vehicle_id = %s', (vid,))
    records = q("""SELECT * FROM wsb.maintenance_record WHERE vehicle_id = %s
                   ORDER BY service_date DESC, maintenance_id DESC LIMIT 50""", (vid,))
    trips = q("""SELECT t.*, d.first_name || ' ' || d.last_name AS driver_name
                 FROM wsb.trip t JOIN wsb.driver d USING (driver_id) WHERE t.vehicle_id = %s
                 ORDER BY t.start_datetime DESC, t.trip_id DESC LIMIT 50""", (vid,))
    fuel = q("""SELECT * FROM wsb.fuel_record WHERE vehicle_id = %s
                ORDER BY fuel_date DESC, fuel_id DESC LIMIT 50""", (vid,))
    costs = q("SELECT * FROM wsb.v_cost_by_vehicle_fy WHERE vehicle_id = %s ORDER BY fiscal_year DESC", (vid,))
    docs = q("""SELECT * FROM wsb.vehicle_document WHERE vehicle_id = %s AND access_level = ANY(%s)
                ORDER BY document_id DESC""", (vid, levels))
    g.page_label = f'Vehicle: {display_name(v)}'
    log_activity('view', g.page_label)
    return render_template('vehicle.html', v=v, rules=rules, records=records, trips=trips, fuel=fuel,
                           costs=costs, docs=docs, doc_types=DOC_TYPES, levels=levels)


VEHICLE_FIELDS = ['name', 'asset_number', 'vehicle_type', 'make', 'model', 'year', 'vin', 'license_plate',
                  'department', 'current_mileage', 'current_hours', 'location', 'status', 'notes']
VEHICLE_LABELS = {'name': 'Name', 'asset_number': 'Property tag', 'vehicle_type': 'Type', 'vin': 'VIN / HIN',
                  'license_plate': 'Plate / registration', 'current_mileage': 'Mileage',
                  'current_hours': 'Engine hours'}


def form_vehicle():
    data = {f: (request.form.get(f) or '').strip() or None for f in VEHICLE_FIELDS}
    data['active'] = data['status'] != 'Retired'
    return data


@app.route('/vehicles/new', methods=['GET', 'POST'])
@require(perm='vehicles')
def vehicle_new():
    if request.method == 'POST':
        d = form_vehicle()
        try:
            row = run(f"INSERT INTO wsb.vehicle ({', '.join(d)}) VALUES ({', '.join(['%s'] * len(d))}) RETURNING vehicle_id",
                      list(d.values()))
            flash('Vehicle added.', 'ok')
            log_activity('change', f"Added vehicle {display_name(dict(d, vehicle_id=row['vehicle_id']))}")
            return redirect(url_for('vehicle', vid=row['vehicle_id']))
        except psycopg2.Error as e:
            flash(f'Could not save: {e.diag.message_primary}', 'error')
            return render_template('vehicle_form.html', v=d, types=VEHICLE_TYPES, statuses=STATUSES, new=True)
    return render_template('vehicle_form.html', v={'status': 'Available', 'department': 'The Water School'},
                           types=VEHICLE_TYPES, statuses=STATUSES, new=True)


@app.route('/vehicles/<int:vid>/edit', methods=['GET', 'POST'])
@require(perm='vehicles')
def vehicle_edit(vid):
    v = q('SELECT * FROM wsb.vehicle WHERE vehicle_id = %s', (vid,), one=True) or abort(404)
    if request.method == 'POST':
        d = form_vehicle()
        try:
            run(f"UPDATE wsb.vehicle SET {', '.join(f'{k} = %s' for k in d)} WHERE vehicle_id = %s",
                list(d.values()) + [vid])
            flash('Changes saved.', 'ok')
            log_activity('change', f"Edited vehicle {display_name(dict(d, vehicle_id=vid))}",
                         details=change_diff(v, {k: x for k, x in d.items() if k != 'active'}, VEHICLE_LABELS))
            return redirect(url_for('vehicle', vid=vid))
        except psycopg2.Error as e:
            flash(f'Could not save: {e.diag.message_primary}', 'error')
            v.update(d)
    return render_template('vehicle_form.html', v=v, types=VEHICLE_TYPES, statuses=STATUSES, new=False)


@app.route('/vehicles/<int:vid>/delete', methods=['POST'])
@require(delete=True)
def vehicle_delete(vid):
    before = q('SELECT * FROM wsb.vehicle WHERE vehicle_id = %s', (vid,), one=True) or abort(404)
    files = [d['file_location'] for d in q('SELECT file_location FROM wsb.vehicle_document WHERE vehicle_id = %s', (vid,))]
    try:
        run('DELETE FROM wsb.vehicle WHERE vehicle_id = %s', (vid,))
    except psycopg2.Error as e:
        if getattr(e, 'pgcode', '') == '23503':
            flash('This vehicle has trips, fuel, service or invoice records, so it cannot be deleted. '
                  'Set its status to Retired instead.', 'error')
        else:
            flash(db_error_message(e), 'error')
        return redirect(url_for('vehicle', vid=vid))
    for f in files:
        (UPLOADS / f).unlink(missing_ok=True)
    flash('Vehicle deleted.', 'ok')
    log_activity('change', f"Deleted vehicle #{vid} {display_name(before) if before else ''}".strip())
    return redirect(url_for('dashboard'))


# ---------------------------------------------------------------------------
# Add forms (Tier 1). Trips, fuel and maintenance go through the database's own
# functions (sql_postgres/05_procedures.sql), so its checks and messages apply.
# ---------------------------------------------------------------------------
def db_error_message(e):
    """The database's own message for checks it raises; a plain fallback otherwise."""
    if getattr(e, 'pgcode', None) == 'P0001' and e.diag.message_primary:
        return e.diag.message_primary
    return 'Could not save. Check the values and try again.'


def _vehicle_choices():
    return [(v['vehicle_id'], display_name(v) + (f" ({v['asset_number']})" if v['asset_number'] else ''))
            for v in q("""SELECT vehicle_id, asset_number, year, make, model, notes, name FROM wsb.vehicle
                          WHERE active ORDER BY vehicle_type, year DESC NULLS LAST""")]


def _asset_for(vehicle_id):
    row = q('SELECT asset_number FROM wsb.vehicle WHERE vehicle_id = %s', (vehicle_id,), one=True)
    return row and row['asset_number']


def _entry_form(title, fields, call_sql, anchor, defaults=None):
    """GET shows the form; POST checks it, calls the database function, and returns to the vehicle."""
    values = dict(defaults or {})
    if request.method == 'GET' and request.args.get('vehicle_id'):
        values['vehicle_id'] = _int_arg('vehicle_id')
    errors = []
    if request.method == 'POST':
        values, errors = parse(fields, request.form)
        asset = _asset_for(values.get('vehicle_id')) if values.get('vehicle_id') and not errors else None
        if not errors and not asset:
            errors.append('This vehicle has no property tag yet. Add one on its Edit page first.')
        if not errors:
            args = {k: v for k, v in values.items() if k != 'vehicle_id'}
            args['asset_number'] = asset
            try:
                run(call_sql, args)
                flash('Saved.', 'ok')
                vrow = q('SELECT * FROM wsb.vehicle WHERE vehicle_id = %s', (values['vehicle_id'],), one=True)
                log_activity('change', f"{title.replace('Log ', 'Logged ', 1)} · {display_name(vrow)}")
                return redirect(url_for('vehicle', vid=values['vehicle_id']) + anchor)
            except psycopg2.Error as e:
                errors.append(db_error_message(e))
    back = url_for('vehicle', vid=values['vehicle_id']) + anchor if values.get('vehicle_id') else url_for('dashboard')
    return render_template('form_entry.html', title=title, fields=fields, values=values, errors=errors, cancel=back)


@app.route('/trips/new', methods=['GET', 'POST'])
@require(perm='trips_fuel')
def trip_new():
    drivers = [(d['driver_id'], f"{d['first_name']} {d['last_name']}") for d in q(
        """SELECT driver_id, first_name, last_name FROM wsb.driver WHERE approved AND active AND email IS NOT NULL
           ORDER BY last_name, first_name""")]
    fields = [Field('vehicle_id', 'Vehicle', 'select', True, _vehicle_choices(), suggest='vehicle'),
              Field('driver_id', 'Driver', 'select', True, drivers, help='Only approved, active drivers are listed.', suggest='driver'),
              Field('start_datetime', 'Start', 'datetime', True),
              Field('end_datetime', 'End', 'datetime', help='Leave empty for a trip still in progress.'),
              Field('starting_mileage', 'Starting mileage', 'int'), Field('ending_mileage', 'Ending mileage', 'int'),
              Field('destination', 'Destination', suggest='destination'), Field('purpose', 'Purpose', suggest='purpose'),
              Field('project_program', 'Project / program', suggest='project_program'), Field('notes', 'Notes', 'textarea', wide=True)]
    return _entry_form('Log a trip', fields, """SELECT wsb.add_trip(
        p_asset_number => %(asset_number)s,
        p_driver_email => (SELECT email FROM wsb.driver WHERE driver_id = %(driver_id)s), p_start_datetime => %(start_datetime)s,
        p_end_datetime => %(end_datetime)s, p_starting_mileage => %(starting_mileage)s,
        p_ending_mileage => %(ending_mileage)s, p_destination => %(destination)s, p_purpose => %(purpose)s,
        p_project_program => %(project_program)s, p_notes => %(notes)s)""", '#trips')


@app.route('/fuel/new', methods=['GET', 'POST'])
@require(perm='trips_fuel')
def fuel_new():
    fields = [Field('vehicle_id', 'Vehicle', 'select', True, _vehicle_choices(), suggest='vehicle'),
              Field('fuel_date', 'Date', 'date', True), Field('gallons', 'Gallons', 'num', True),
              Field('total_cost', 'Total cost', 'num', True), Field('mileage', 'Mileage', 'int'),
              Field('vendor', 'Station / vendor', suggest='vendor')]
    return _entry_form('Log fuel', fields, """SELECT wsb.add_fuel(
        p_asset_number => %(asset_number)s, p_fuel_date => %(fuel_date)s, p_gallons => %(gallons)s,
        p_total_cost => %(total_cost)s, p_mileage => %(mileage)s, p_vendor => %(vendor)s)""", '#fuel',
        {'fuel_date': datetime.date.today()})


@app.route('/maintenance/new', methods=['GET', 'POST'])
@require(perm='maintenance')
def maintenance_new():
    fields = [Field('vehicle_id', 'Vehicle', 'select', True, _vehicle_choices(), suggest='vehicle'),
              Field('service_date', 'Date', 'date', True),
              Field('service_type', 'Service', required=True, suggest='service_type',
                    help='Use the same name as the schedule (e.g. Oil Change) to move it forward.'),
              Field('cost', 'Cost', 'num'), Field('vendor', 'Vendor', suggest='vendor'), Field('mileage_at_service', 'Mileage', 'int'),
              Field('next_service_date', 'Next service date', 'date'),
              Field('next_service_mileage', 'Next service mileage', 'int'),
              Field('description', 'What was done', 'textarea', wide=True)]
    return _entry_form('Log a service', fields, """SELECT wsb.add_maintenance(
        p_asset_number => %(asset_number)s, p_service_date => %(service_date)s, p_service_type => %(service_type)s,
        p_cost => %(cost)s, p_vendor => %(vendor)s, p_mileage_at_service => %(mileage_at_service)s,
        p_description => %(description)s, p_next_service_date => %(next_service_date)s,
        p_next_service_mileage => %(next_service_mileage)s)""", '#maintenance', {'service_date': datetime.date.today()})


# ---------------------------------------------------------------------------
# Drivers. License fields only for people with license access.
# ---------------------------------------------------------------------------
DRIVER_TYPES = ['Faculty', 'Staff', 'OPS', 'Other']
DRIVER_COLS = ('first_name', 'last_name', 'email', 'department', 'driver_type', 'approved', 'active')


def _driver_fields():
    fields = [Field('first_name', 'First name', required=True), Field('last_name', 'Last name', required=True),
              Field('email', 'Email'), Field('department', 'Department', suggest='department'),
              Field('driver_type', 'Type', 'select', options=[(t, t) for t in DRIVER_TYPES]),
              Field('approved', 'Approved to drive', 'bool'), Field('active', 'Active', 'bool')]
    if current_user().can_see_licenses:
        fields += [Field('license_number', 'License number'), Field('state', 'License state'),
                   Field('license_expiration', 'License expires', 'date')]
    return fields


def _driver_done(did):
    if current_user().can_see_licenses:
        return url_for('driver_page', did=did)
    d = q('SELECT last_name FROM wsb.driver WHERE driver_id = %s', (did,), one=True)
    return url_for('search_page', q=d['last_name'] if d else '', kind='drivers')


def _save_driver(did=None):
    fields = _driver_fields()
    values, errors = parse(fields, request.form)
    if not errors:
        d = {k: values[k] for k in DRIVER_COLS}
        before = {}
        if did:
            before = dict(q('SELECT * FROM wsb.driver WHERE driver_id = %s', (did,), one=True) or {})
            lic0 = q('SELECT license_number, state, expiration_date AS license_expiration FROM wsb.driver_license '
                     'WHERE driver_id = %s ORDER BY license_id DESC LIMIT 1', (did,), one=True)
            before.update(lic0 or {})
        try:
            if did:
                run(f"UPDATE wsb.driver SET {', '.join(f'{k} = %s' for k in d)} WHERE driver_id = %s",
                    list(d.values()) + [did])
            else:
                did = run(f"INSERT INTO wsb.driver ({', '.join(d)}) VALUES ({', '.join(['%s'] * len(d))}) "
                          "RETURNING driver_id", list(d.values()))['driver_id']
            if current_user().can_see_licenses and any(values.get(k) for k in ('license_number', 'state', 'license_expiration')):
                lic = (values.get('license_number'), values.get('state'), values.get('license_expiration'))
                existing = q('SELECT license_id FROM wsb.driver_license WHERE driver_id = %s ORDER BY license_id DESC LIMIT 1',
                             (did,), one=True)
                if existing:
                    run('UPDATE wsb.driver_license SET license_number = %s, state = %s, expiration_date = %s '
                        'WHERE license_id = %s', lic + (existing['license_id'],))
                else:
                    run('INSERT INTO wsb.driver_license (license_number, state, expiration_date, driver_id) '
                        'VALUES (%s, %s, %s, %s)', lic + (did,))
            flash('Saved.', 'ok')
            after = {f.name: values.get(f.name) for f in fields}
            log_activity('change', f"{'Edited' if request.view_args.get('did') else 'Added'} driver "
                                   f"{values['first_name']} {values['last_name']}",
                         details=change_diff(before, after, {f.name: f.label for f in fields}) if did else None)
            return redirect(_driver_done(did))
        except psycopg2.Error as e:
            errors.append('That email is already used by another driver.' if getattr(e, 'pgcode', '') == '23505'
                          else db_error_message(e))
    return render_template('form_entry.html', title='Edit driver' if did else 'Add a driver', fields=fields,
                           values=values, errors=errors, cancel=url_for('dashboard'))


@app.route('/drivers/new', methods=['GET', 'POST'])
@require(admin=True)
def driver_new():
    if request.method == 'POST':
        return _save_driver()
    return render_template('form_entry.html', title='Add a driver', fields=_driver_fields(),
                           values={'active': True, 'approved': False}, errors=[], cancel=url_for('dashboard'))


@app.route('/drivers/<int:did>/edit', methods=['GET', 'POST'])
@require(admin=True)
def driver_edit(did):
    d = q('SELECT * FROM wsb.driver WHERE driver_id = %s', (did,), one=True) or abort(404)
    if request.method == 'POST':
        return _save_driver(did)
    values = dict(d)
    if current_user().can_see_licenses:
        lic = q('SELECT * FROM wsb.driver_license WHERE driver_id = %s ORDER BY license_id DESC LIMIT 1', (did,), one=True)
        if lic:
            values.update(license_number=lic['license_number'], state=lic['state'],
                          license_expiration=lic['expiration_date'])
    return render_template('form_entry.html', title='Edit driver', fields=_driver_fields(), values=values,
                           errors=[], cancel=_driver_done(did))


@app.route('/drivers/<int:did>')
@require(licenses=True)
def driver_page(did):
    d = q('SELECT * FROM wsb.driver WHERE driver_id = %s', (did,), one=True) or abort(404)
    licenses = q('SELECT * FROM wsb.driver_license WHERE driver_id = %s ORDER BY license_id DESC', (did,))
    quals = q('SELECT * FROM wsb.driver_qualification WHERE driver_id = %s ORDER BY qualification_type', (did,))
    g.page_label = f"Driver: {d['first_name']} {d['last_name']}"
    log_activity('view', g.page_label + ' (license record)')
    return render_template('driver.html', d=d, licenses=licenses, quals=quals)


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------
@app.route('/maintenance')
@require()
def maintenance_page():
    rows = maintenance()
    f = request.args.get('show', 'attention')
    if f == 'attention':
        rows = [r for r in rows if r['status'] in ('Overdue', 'Due soon', 'Unknown')]
    return render_template('maintenance.html', rows=rows, show=f)


@app.route('/maintenance/<int:rid>/done', methods=['POST'])
@require(perm='maintenance')
def maintenance_done(rid):
    try:
        day = datetime.date.fromisoformat(request.form.get('date') or datetime.date.today().isoformat())
        miles = int(request.form['mileage'].replace(',', '')) if (request.form.get('mileage') or '').strip() else None
        if miles is not None and miles < 0:
            raise ValueError
    except ValueError:
        flash('Enter a real date and a whole number for mileage.', 'error')
        return redirect(safe_next(request.form.get('back')) or url_for('maintenance_page'))
    r0 = q("""SELECT r.maintenance_type, r.last_completed_date, r.last_completed_mileage, r.vehicle_id
              FROM wsb.maintenance_rule r WHERE rule_id = %s""", (rid,), one=True) or abort(404)
    run("""UPDATE wsb.maintenance_rule SET last_completed_date = %s,
           last_completed_mileage = COALESCE(%s, last_completed_mileage) WHERE rule_id = %s""", (day, miles, rid))
    flash('Marked as done.', 'ok')
    log_activity('change', f"Marked {r0['maintenance_type']} done · vehicle #{r0['vehicle_id']}",
                 details=change_diff(r0, {'last_completed_date': day, 'last_completed_mileage': miles or r0['last_completed_mileage']},
                                     {'last_completed_date': 'Last done', 'last_completed_mileage': 'Mileage when done'}))
    return redirect(safe_next(request.form.get('back')) or url_for('maintenance_page'))


@app.route('/vehicles/<int:vid>/rules', methods=['POST'])
@require(perm='maintenance')
def rule_add(vid):
    try:
        run("""INSERT INTO wsb.maintenance_rule (vehicle_id, maintenance_type, mileage_interval, time_interval_months,
               last_completed_date) VALUES (%s, %s, %s, %s, %s)""",
            (vid, (request.form.get('maintenance_type') or '').strip() or abort(400), request.form.get('mileage_interval') or None,
             request.form.get('time_interval_months') or None, request.form.get('last_completed_date') or None))
        flash('Maintenance rule added.', 'ok')
        log_activity('change', f"Added schedule rule {request.form['maintenance_type'].strip()} · vehicle #{vid}")
    except psycopg2.Error as e:
        flash(f'Could not add rule: {e.diag.message_primary}', 'error')
    return redirect(url_for('vehicle', vid=vid))


@app.route('/rules/<int:rid>/delete', methods=['POST'])
@require(delete=True)
def rule_delete(rid):
    r = run('DELETE FROM wsb.maintenance_rule WHERE rule_id = %s RETURNING vehicle_id', (rid,)) or abort(404)
    flash('Rule removed.', 'ok')
    log_activity('change', f'Removed schedule rule #{rid}')
    return redirect(url_for('vehicle', vid=r['vehicle_id']) if r else url_for('maintenance_page'))


# ---------------------------------------------------------------------------
# Documents (upload, list, download) - filtered by role
# ---------------------------------------------------------------------------
@app.route('/vehicles/<int:vid>/documents', methods=['POST'])
@require(perm='documents')
def doc_upload(vid):
    q('SELECT 1 FROM wsb.vehicle WHERE vehicle_id = %s', (vid,), one=True) or abort(404)
    f = request.files.get('file')
    level = request.form.get('access_level', 'General')
    if level not in doc_levels(current_user()):
        abort(403)
    if not f or not f.filename:
        flash('Choose a file to upload.', 'error')
        return redirect(url_for('vehicle', vid=vid))
    name = secure_filename(f.filename)
    if name.rsplit('.', 1)[-1].lower() not in ALLOWED_EXT:
        flash('That file type is not allowed. Use PDF, image, Word, Excel or text.', 'error')
        return redirect(url_for('vehicle', vid=vid))
    rel = f'{vid}/{uuid.uuid4().hex[:8]}_{name}'
    (UPLOADS / str(vid)).mkdir(parents=True, exist_ok=True)
    f.save(UPLOADS / rel)
    try:
        run("""INSERT INTO wsb.vehicle_document (vehicle_id, document_type, file_location, issue_date,
               expiration_date, access_level, notes) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (vid, request.form.get('document_type'), rel, request.form.get('issue_date') or None,
             request.form.get('expiration_date') or None, level, request.form.get('notes') or None))
        flash('File uploaded.', 'ok')
        log_activity('change', f"Uploaded {request.form.get('document_type')} · vehicle #{vid} · {name}")
    except psycopg2.Error as e:
        (UPLOADS / rel).unlink(missing_ok=True)
        flash(f'Could not save: {e.diag.message_primary}', 'error')
    return redirect(url_for('vehicle', vid=vid))


@app.route('/documents')
@require()
def documents():
    rows = q("""SELECT d.*, v.notes AS vnotes, v.name AS vname, v.vehicle_id, v.make, v.model, v.year
                FROM wsb.vehicle_document d JOIN wsb.vehicle v USING (vehicle_id)
                WHERE d.access_level = ANY(%s) ORDER BY d.document_id DESC""", (doc_levels(current_user()),))
    return render_template('documents.html', rows=rows)


@app.route('/documents/<int:did>/file')
@require()
def doc_file(did):
    d = q('SELECT * FROM wsb.vehicle_document WHERE document_id = %s', (did,), one=True) or abort(404)
    if d['access_level'] not in doc_levels(current_user()):
        abort(403)
    folder, fname = d['file_location'].split('/', 1)
    log_activity('download', f"Opened {d['document_type']} · vehicle #{d['vehicle_id']} · {fname}")
    return send_from_directory(UPLOADS / folder, fname, as_attachment=request.args.get('dl') == '1')


@app.route('/documents/<int:did>/delete', methods=['POST'])
@require(delete=True)
def doc_delete(did):
    d = run('DELETE FROM wsb.vehicle_document WHERE document_id = %s RETURNING vehicle_id, file_location', (did,)) or abort(404)
    (UPLOADS / d['file_location']).unlink(missing_ok=True)
    flash('Document deleted.', 'ok')
    log_activity('change', f'Deleted document #{did}')
    return redirect(safe_next(request.form.get('back')) or url_for('documents'))


# ---------------------------------------------------------------------------
# Old roles page -> help
# ---------------------------------------------------------------------------
@app.route('/suggest')
@require()
def suggest_json():
    """Suggestions while typing. Not logged: it runs on every pause in typing."""
    from suggest import suggest
    return jsonify(suggest(q, current_user(), request.args.get('field', ''), request.args.get('q', '')))


@app.route('/roles')
def roles():
    return redirect(url_for('help_page') + '#tiers', code=301)


@app.route('/help')
@require()
def help_page():
    return render_template('help.html')


# ---------------------------------------------------------------------------
# Error pages. Each one says what happened and what to do next, never a stack trace.
# ---------------------------------------------------------------------------
ERRORS = {
    400: ('Something was wrong with that request', 'The form or link was incomplete. Go back and try again.'),
    403: ('Not allowed', 'Your access level does not include this page. Ask an admin if you need it.'),
    404: ('Not found', 'That page or record does not exist. It may have been deleted, or the link is wrong.'),
    405: ('That action is not allowed here', 'Go back and use the buttons on the page.'),
    413: ('File too large', 'Uploads can be up to 20 MB. Make the file smaller and try again.'),
    500: ('Something went wrong', 'The site hit an error. Nothing you did caused it. Try again, '
                                 'and if it keeps happening tell the fleet manager what you were doing.'),
    503: ('Cannot reach the database', 'The site cannot reach the database right now. Wait a minute and try again.'),
}


def error_page(code, msg=None):
    title, default = ERRORS.get(code, ERRORS[500])
    if request.path.startswith('/suggest'):
        return jsonify({'error': title, 'groups': [], 'did_you_mean': None}), code
    try:
        return render_template('error.html', code=code, title=title, msg=msg or default), code
    except Exception:   # e.g. the database is down and the page header can't load
        app.logger.exception('Could not render the error page')
        return (f'<!doctype html><title>{title}</title><h1>{title}</h1><p>{msg or default}</p>'
                '<p><a href="/">Go to the home page</a></p>'), code


for _code in (400, 403, 404, 405, 413):
    app.register_error_handler(_code, lambda e, c=_code: error_page(c))


@app.errorhandler(psycopg2.OperationalError)
def database_down(e):
    app.logger.error('Database unreachable: %s', e)
    return error_page(503)


@app.errorhandler(500)
def server_error(e):
    app.logger.exception('Unhandled error on %s', request.path)
    return error_page(500)


# Admin area (admin.py). It reaches this module's helpers through admin.core.
import admin  # noqa: E402
admin.core = sys.modules[__name__]
app.register_blueprint(admin.bp)
import import_views  # noqa: E402
import_views.core = sys.modules[__name__]
app.register_blueprint(import_views.imp)


if __name__ == '__main__':
    ensure_setup()
    UPLOADS.mkdir(exist_ok=True)
    port = int(os.environ.get('PORT', 5000))
    print(f'Water School Fleet dashboard ({DB_WHERE}): http://localhost:{port}')
    app.run(host='127.0.0.1', port=port, debug=False)

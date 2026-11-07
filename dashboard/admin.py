"""Admin area (/admin): overview stats, people & access, activity, manage data.

Only admins and top admins get in. The rules for who may change whom are in tiers.py
(assignable_levels / can_change); this module adds "never zero top admins" and
"nobody changes themselves".
"""
import re

import psycopg2
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from tiers import LEVEL_LABELS, LEVELS, ROLE_FOR_LEVEL, assignable_levels, can_change, level_for_role

bp = Blueprint('admin', __name__, url_prefix='/admin')
core = None          # the main app module; set by app.py before the blueprint is used
ONLINE_MINUTES = 15
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


@bp.before_request
def only_admins():
    u = core.current_user()
    if not u:
        return redirect(url_for('login', next=request.full_path.rstrip('?')))
    if not u.is_admin:
        abort(403)


@bp.context_processor
def admin_context():
    return dict(level_labels=LEVEL_LABELS, section=request.endpoint.split('.')[-1] if request.endpoint else '')


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
@bp.route('')
def overview():
    """Layout B: four numbers, then the latest activity (left) and what needs attention + who's online (right)."""
    q = core.q
    online = q(f"""SELECT u.full_name, u.last_page, u.last_seen, r.role_name FROM wsb.app_user u
                   JOIN wsb.app_role r USING (role_id)
                   WHERE u.active AND u.last_seen > now() - interval '{ONLINE_MINUTES} minutes'
                   ORDER BY u.last_seen DESC""")
    for o in online:
        o['level'] = level_for_role(o['role_name'])
    maint = core.maintenance()
    nums = q("""SELECT (SELECT count(*) FROM wsb.vehicle WHERE status <> 'Retired') AS vehicles,
                       (SELECT count(*) FROM wsb.trip WHERE start_datetime >= date_trunc('month', now())) AS trips,
                       (SELECT COALESCE(sum(total_cost), 0) FROM wsb.fuel_record
                         WHERE fuel_date >= date_trunc('month', now())::date) AS fuel,
                       (SELECT COALESCE(sum(grand_total), 0) FROM wsb.v_cost_by_vehicle_fy
                         WHERE fiscal_year = wsb.fiscal_year(CURRENT_DATE)) AS fy_total,
                       wsb.fiscal_year(CURRENT_DATE) AS fy,
                       (SELECT count(*) FROM wsb.vehicle_document
                         WHERE expiration_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 60) AS expiring""", one=True)
    recent = q('SELECT * FROM wsb.activity_log ORDER BY activity_id DESC LIMIT 10')
    g.page_label = 'Admin: Overview'
    return render_template('admin/overview.html', online=online, nums=nums, recent=recent,
                           overdue=sum(m['status'] == 'Overdue' for m in maint),
                           soon=sum(m['status'] == 'Due soon' for m in maint))


def level_counts():
    """Active people per level, for the People page."""
    counts = {l: 0 for l in LEVELS}
    for r in core.q("""SELECT r.role_name, count(*) n FROM wsb.app_user u JOIN wsb.app_role r USING (role_id)
                       WHERE u.active GROUP BY r.role_name"""):
        counts[level_for_role(r['role_name'])] += r['n']
    return counts


# ---------------------------------------------------------------------------
# People & access
# ---------------------------------------------------------------------------
def keeps_a_top_admin(user_id, new_level, new_active):
    """False if changing this person to (new_level, new_active) would leave no active top admin."""
    others = core.q("""SELECT count(*) n FROM wsb.app_user u JOIN wsb.app_role r USING (role_id)
                       WHERE u.active AND r.role_name = %s AND u.user_id <> %s""",
                    (ROLE_FOR_LEVEL['top_admin'], user_id), one=True)['n']
    return others + (1 if new_level == 'top_admin' and new_active else 0) > 0


def _people():
    rows = core.q(f"""SELECT u.user_id, u.username, u.full_name, u.email, u.active, u.last_seen, r.role_name,
                             u.last_seen > now() - interval '{ONLINE_MINUTES} minutes' AS online
                      FROM wsb.app_user u JOIN wsb.app_role r USING (role_id)""")
    order = {l: i for i, l in enumerate(LEVELS)}
    for r in rows:
        r['level'] = level_for_role(r['role_name'])
    rows.sort(key=lambda r: (not r['active'], order[r['level']], r['full_name'].lower()))
    return rows


def _render_people(errors=(), form=None, status=200):
    me = core.current_user()
    text = request.args.get('q', '').strip().lower()
    show = request.args.get('show', '')
    rows = _people()
    if text:
        rows = [r for r in rows if text in r['full_name'].lower() or text in (r['email'] or '').lower()]
    if show in LEVELS:
        rows = [r for r in rows if r['level'] == show and r['active']]
    elif show == 'removed':
        rows = [r for r in rows if not r['active']]
    for r in rows:
        r['changeable'] = r['user_id'] != me.user_id and can_change(me, r['level'])
    g.page_label = 'Admin: People & access'
    return render_template('admin/people.html', rows=rows, me=me, assignable=assignable_levels(me), by_level=level_counts(),
                           errors=errors, form=form or {}, text=text, show=show), status


@bp.route('/people')
def people():
    return _render_people()


def _username_for(email):
    base = re.sub(r'[^a-z0-9_.]', '', email.split('@')[0].lower())[:40] or 'user'
    name, n = base, 1
    while core.q('SELECT 1 FROM wsb.app_user WHERE username = %s', (name,), one=True):
        n += 1
        name = f'{base}{n}'
    return name


@bp.route('/people', methods=['POST'])
def add_person():
    me = core.current_user()
    form = {k: (request.form.get(k) or '').strip() for k in ('full_name', 'email', 'level')}
    if form['level'] not in LEVELS or form['level'] not in assignable_levels(me):
        abort(403)
    errors = []
    if not form['full_name']:
        errors.append('Enter a name.')
    if not EMAIL_RE.match(form['email']):
        errors.append('Enter a valid email address.')
    elif core.q('SELECT 1 FROM wsb.app_user WHERE lower(email) = lower(%s)', (form['email'],), one=True):
        errors.append('That email already has access (or is in the list with access removed).')
    if errors:
        return _render_people(errors, form)
    role = core.q('SELECT role_id FROM wsb.app_role WHERE role_name = %s', (ROLE_FOR_LEVEL[form['level']],), one=True)
    try:
        core.run("""INSERT INTO wsb.app_user (username, full_name, email, role_id, active)
                    VALUES (%s, %s, %s, %s, TRUE)""",
                 (_username_for(form['email']), form['full_name'][:100], form['email'][:100], role['role_id']))
    except psycopg2.Error:
        return _render_people(['Could not add that person. Check the name and email.'], form)
    core.log_activity('access', f"Added {form['full_name']} ({form['email']}) as {LEVEL_LABELS[form['level']]}")
    flash(f"{form['full_name']} can now sign in as {LEVEL_LABELS[form['level']]}.", 'ok')
    return redirect(url_for('admin.people'))


def _target(uid):
    me = core.current_user()
    row = core.q("""SELECT u.user_id, u.full_name, u.active, r.role_name FROM wsb.app_user u
                    JOIN wsb.app_role r USING (role_id) WHERE u.user_id = %s""", (uid,), one=True) or abort(404)
    row['level'] = level_for_role(row['role_name'])
    if uid == me.user_id or not can_change(me, row['level']):
        abort(403)
    return me, row


@bp.route('/people/<int:uid>/level', methods=['POST'])
def change_level(uid):
    me, t = _target(uid)
    new = request.form.get('level', '')
    if new not in assignable_levels(me):
        abort(403)
    if new == t['level']:
        return redirect(url_for('admin.people'))
    if not keeps_a_top_admin(uid, new, t['active']):
        flash('The site needs at least one top admin. Make someone else a top admin first.', 'error')
        return redirect(url_for('admin.people'))
    core.run("""UPDATE wsb.app_user SET role_id = (SELECT role_id FROM wsb.app_role WHERE role_name = %s)
                WHERE user_id = %s""", (ROLE_FOR_LEVEL[new], uid))
    core.log_activity('access', f"Changed {t['full_name']} from {LEVEL_LABELS[t['level']]} to {LEVEL_LABELS[new]}",
                      details=[{'field': 'Level', 'old': LEVEL_LABELS[t['level']], 'new': LEVEL_LABELS[new]}])
    flash(f"{t['full_name']} is now {LEVEL_LABELS[new]}.", 'ok')
    return redirect(url_for('admin.people'))


@bp.route('/people/<int:uid>/access', methods=['POST'])
def change_access(uid):
    _, t = _target(uid)
    active = request.form.get('active') == '1'
    if active == t['active']:
        return redirect(url_for('admin.people'))
    if not keeps_a_top_admin(uid, t['level'], active):
        flash('The site needs at least one top admin. Make someone else a top admin first.', 'error')
        return redirect(url_for('admin.people'))
    core.run('UPDATE wsb.app_user SET active = %s WHERE user_id = %s', (active, uid))
    core.log_activity('access', f"{'Gave back' if active else 'Removed'} {t['full_name']}'s access",
                      details=[{'field': 'Can sign in', 'old': 'No' if active else 'Yes', 'new': 'Yes' if active else 'No'}])
    flash(f"{t['full_name']} {'can sign in again' if active else 'can no longer sign in'}.", 'ok')
    return redirect(url_for('admin.people'))


# ---------------------------------------------------------------------------
# Activity (read-only list of the append-only log)
# ---------------------------------------------------------------------------
ACTIVITY_PAGE = 100
ACTIVITY_KINDS = ('sign-in', 'sign-out', 'view', 'change', 'download', 'access')


def _date(name):
    import datetime as dt
    try:
        return dt.date.fromisoformat(request.args.get(name, ''))
    except ValueError:
        return None


@bp.route('/activity')
def activity():
    import datetime as dt
    kind = request.args.get('kind', '')
    text = request.args.get('q', '').strip()[:100]
    d0, d1 = _date('date_from'), _date('date_to')
    try:
        page = max(1, int(request.args.get('page', '1')))
    except ValueError:
        page = 1
    where, args = ['TRUE'], []
    if kind in ACTIVITY_KINDS:
        where.append('kind = %s'); args.append(kind)
    if text:
        from search import escape_like
        where.append("(full_name ILIKE %s ESCAPE '\\' OR summary ILIKE %s ESCAPE '\\')")
        args += [f'%{escape_like(text)}%'] * 2
    if d0:
        where.append('at >= %s'); args.append(d0)
    if d1 and d1 < dt.date.max:
        where.append('at < %s'); args.append(d1 + dt.timedelta(days=1))
    rows = core.q(f"""SELECT * FROM wsb.activity_log WHERE {' AND '.join(where)}
                      ORDER BY at DESC, activity_id DESC LIMIT {ACTIVITY_PAGE + 1} OFFSET %s""",
                  args + [(page - 1) * ACTIVITY_PAGE])
    g.page_label = 'Admin: Activity'
    return render_template('admin/activity.html', rows=rows[:ACTIVITY_PAGE], has_next=len(rows) > ACTIVITY_PAGE,
                           page=page, kind=kind, text=text, d0=d0, d1=d1, kinds=ACTIVITY_KINDS)


# ---------------------------------------------------------------------------
# Manage data
# ---------------------------------------------------------------------------
@bp.route('/data')
def data():
    me = core.current_user()
    n = core.q("""SELECT (SELECT count(*) FROM wsb.vehicle) vehicles, (SELECT count(*) FROM wsb.driver) drivers,
                         (SELECT count(*) FROM wsb.driver_license) licenses, (SELECT count(*) FROM wsb.trip) trips,
                         (SELECT count(*) FROM wsb.fuel_record) fuel, (SELECT count(*) FROM wsb.maintenance_rule) rules,
                         (SELECT count(*) FROM wsb.maintenance_record) records,
                         (SELECT count(*) FROM wsb.vehicle_document) documents""", one=True)
    cards = [('vehicles', 'Vehicles', n['vehicles'], 'vehicle_new'),
             ('drivers', 'Drivers', n['drivers'], 'driver_new'),
             ('trips', 'Trips', n['trips'], 'trip_new'),
             ('fuel', 'Fuel records', n['fuel'], 'fuel_new'),
             ('maintenance', 'Maintenance', n['rules'] + n['records'], 'maintenance_new'),
             ('documents', 'Documents', n['documents'], None)]
    if me.can_see_licenses:
        cards.insert(2, ('licenses', "Driver's licenses", n['licenses'], None))
    g.page_label = 'Admin: Manage data'
    return render_template('admin/data.html', cards=cards, n=n)

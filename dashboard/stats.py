"""Stats pages: where the money goes (/stats/spending) and how the vehicles are used (/stats/trips).

Everyone signed in can see them (the tier table: all tiers see costs). Each page runs its queries together
(Database.q_many), so it costs about one round trip to the database.

Spending = fuel purchases + service records + invoice lines that are not already linked to one of those
(so nothing is counted twice).
"""
import datetime as dt

from flask import Blueprint, g, render_template, request

from common import VEHICLE_TYPES, display_name

stats = Blueprint('stats', __name__)
core = None          # the main app module; set by app.py

_COSTS = """
    SELECT f.vehicle_id, f.fuel_date AS d, 'Fuel' AS kind, f.vendor,
           coalesce(f.total_cost, 0) + coalesce(f.other_cost, 0) AS amount
    FROM wsb.fuel_record f
    UNION ALL
    SELECT m.vehicle_id, m.service_date, 'Maintenance', m.vendor, coalesce(m.cost, 0)
    FROM wsb.maintenance_record m
    UNION ALL
    SELECT l.vehicle_id, coalesce(l.line_date, i.invoice_date),
           CASE WHEN l.category = 'Fuel' THEN 'Fuel'
                WHEN l.category IN ('Repair', 'Parts', 'Service') THEN 'Maintenance' ELSE 'Other' END,
           i.vendor, l.amount
    FROM wsb.invoice_line l JOIN wsb.invoice i USING (invoice_id)
    WHERE NOT EXISTS (SELECT 1 FROM wsb.fuel_record f WHERE f.invoice_line_id = l.line_id)
      AND NOT EXISTS (SELECT 1 FROM wsb.maintenance_record m WHERE m.invoice_line_id = l.line_id)"""

_TRIPS = """
    SELECT t.*, greatest(t.ending_mileage - t.starting_mileage, 0) AS miles,
           d.first_name || ' ' || d.last_name AS driver_name
    FROM wsb.trip t JOIN wsb.driver d USING (driver_id)"""

_VEHICLE_COLS = 'v.vehicle_id, v.name, v.year, v.make, v.model, v.vehicle_type, v.asset_number'


def fiscal_year_of(d: dt.date) -> int:
    """Start year of the fiscal year (July to June) that d falls in."""
    return d.year if d.month >= 7 else d.year - 1


def fy_label(start: int) -> str:
    return f'FY{start % 100:02d}-{(start + 1) % 100:02d}'


def _period():
    """(first day, day after the last, label, chosen FY start, FY choices) from ?fy=2026."""
    this = fiscal_year_of(dt.date.today())
    try:
        start = int(request.args.get('fy', this))
    except ValueError:
        start = this
    start = min(max(start, this - 10), this)
    choices = [(y, fy_label(y)) for y in range(this, this - 6, -1)]
    return dt.date(start, 7, 1), dt.date(start + 1, 7, 1), fy_label(start), start, choices


def _months(d0):
    return [dt.date(d0.year + (d0.month - 1 + i) // 12, (d0.month - 1 + i) % 12 + 1, 1) for i in range(12)]


def _vtype():
    t = request.args.get('type', '')
    return t if t in VEHICLE_TYPES else ''


def _bars(rows, key):
    """Add 'pct' (0-100, for the bar width) to each row, relative to the biggest value of `key`."""
    top = max([float(r[key] or 0) for r in rows] or [0])
    for r in rows:
        r['pct'] = round(100 * float(r[key] or 0) / top) if top else 0
    return rows


def _label(rows):
    for r in rows:
        if r.get('vehicle_id'):
            r['label'] = display_name(r)
    return rows


@stats.before_request
def _signed_in():
    from flask import redirect, url_for
    if not core.current_user():
        return redirect(url_for('login', next=request.full_path))
    return None


@stats.route('/stats/spending')
def spending():
    d0, d1, label, fy, choices = _period()
    vtype = _vtype()
    a = {'d0': d0, 'd1': d1, 'vtype': vtype}
    where = "c.d >= %(d0)s AND c.d < %(d1)s AND (%(vtype)s = '' OR v.vehicle_type = %(vtype)s)"
    base = f'FROM ({_COSTS}) c LEFT JOIN wsb.vehicle v ON v.vehicle_id = c.vehicle_id WHERE {where}'
    totals, by_month, by_vehicle, by_type, biggest = core.DATABASE.q_many([
        (f"""SELECT coalesce(sum(amount), 0) AS total,
                    coalesce(sum(amount) FILTER (WHERE kind = 'Fuel'), 0) AS fuel,
                    coalesce(sum(amount) FILTER (WHERE kind = 'Maintenance'), 0) AS maintenance,
                    coalesce(sum(amount) FILTER (WHERE kind = 'Other'), 0) AS other,
                    count(DISTINCT c.vehicle_id) AS vehicles, count(*) AS entries {base}""", a),
        (f"""SELECT date_trunc('month', c.d)::date AS month, sum(amount) AS total,
                    coalesce(sum(amount) FILTER (WHERE kind = 'Fuel'), 0) AS fuel,
                    coalesce(sum(amount) FILTER (WHERE kind = 'Maintenance'), 0) AS maintenance
             {base} GROUP BY 1""", a),
        (f"""SELECT {_VEHICLE_COLS}, sum(amount) AS total,
                    coalesce(sum(amount) FILTER (WHERE kind = 'Fuel'), 0) AS fuel,
                    coalesce(sum(amount) FILTER (WHERE kind = 'Maintenance'), 0) AS maintenance,
                    coalesce(sum(amount) FILTER (WHERE kind = 'Other'), 0) AS other, count(*) AS entries
             {base} GROUP BY {_VEHICLE_COLS} ORDER BY total DESC NULLS LAST LIMIT 100""", a),
        (f"""SELECT coalesce(v.vehicle_type, 'Not linked to a vehicle') AS vehicle_type, sum(amount) AS total,
                    count(DISTINCT c.vehicle_id) AS vehicles
             {base} GROUP BY 1 ORDER BY total DESC""", a),
        (f"""SELECT c.d, c.kind, c.vendor, c.amount, {_VEHICLE_COLS}
             {base} ORDER BY c.amount DESC, c.d DESC LIMIT 10""", a)])
    got = {r['month']: r for r in by_month}
    months = _bars([dict(month=m, **{k: (got.get(m) or {}).get(k) or 0 for k in ('total', 'fuel', 'maintenance')})
                    for m in _months(d0)], 'total')
    g.page_label = f'Stats: spending {label}'
    return render_template('stats_spending.html', t=totals[0], months=months, by_type=_bars(by_type, 'total'),
                           by_vehicle=_bars(_label(by_vehicle), 'total'), biggest=_label(biggest),
                           label=label, fy=fy, choices=choices, vtype=vtype, types=VEHICLE_TYPES)


@stats.route('/stats/trips')
def trips():
    d0, d1, label, fy, choices = _period()
    vtype = _vtype()
    a = {'d0': d0, 'd1': d1, 'vtype': vtype}
    where = "t.start_datetime >= %(d0)s AND t.start_datetime < %(d1)s AND (%(vtype)s = '' OR v.vehicle_type = %(vtype)s)"
    base = f'FROM ({_TRIPS}) t JOIN wsb.vehicle v ON v.vehicle_id = t.vehicle_id WHERE {where}'
    top = lambda col: (f"""SELECT {col} AS name, count(*) AS trips, coalesce(sum(miles), 0) AS miles {base}
                           AND nullif(trim({col}), '') IS NOT NULL GROUP BY 1 ORDER BY trips DESC, miles DESC LIMIT 8""", a)
    totals, by_month, by_vehicle, by_driver, dests, purposes, recent = core.DATABASE.q_many([
        (f"""SELECT count(*) AS trips, coalesce(sum(miles), 0) AS miles, count(DISTINCT t.vehicle_id) AS vehicles,
                    count(DISTINCT t.driver_id) AS drivers,
                    round(avg(miles) FILTER (WHERE miles IS NOT NULL)) AS avg_miles,
                    count(*) FILTER (WHERE t.end_datetime IS NULL) AS open,
                    round(coalesce(sum(extract(epoch FROM t.end_datetime - t.start_datetime)) / 3600, 0)) AS hours
             {base}""", a),
        (f"""SELECT date_trunc('month', t.start_datetime)::date AS month, count(*) AS trips,
                    coalesce(sum(miles), 0) AS miles {base} GROUP BY 1""", a),
        (f"""SELECT {_VEHICLE_COLS}, count(*) AS trips, coalesce(sum(miles), 0) AS miles,
                    max(t.start_datetime) AS last_trip
             {base} GROUP BY {_VEHICLE_COLS} ORDER BY trips DESC, miles DESC LIMIT 100""", a),
        (f"""SELECT t.driver_name AS name, count(*) AS trips, coalesce(sum(miles), 0) AS miles
             {base} GROUP BY 1 ORDER BY trips DESC, miles DESC LIMIT 15""", a),
        top('t.destination'), top('coalesce(t.project_program, t.purpose)'),
        (f"""SELECT t.trip_id, t.start_datetime, t.end_datetime, t.destination, t.purpose, t.miles, t.driver_name,
                    {_VEHICLE_COLS} {base} ORDER BY t.start_datetime DESC LIMIT 15""", a)])
    got = {r['month']: r for r in by_month}
    months = _bars([dict(month=m, trips=(got.get(m) or {}).get('trips') or 0, miles=(got.get(m) or {}).get('miles') or 0)
                    for m in _months(d0)], 'trips')
    g.page_label = f'Stats: trips {label}'
    return render_template('stats_trips.html', t=totals[0], months=months, by_vehicle=_bars(_label(by_vehicle), 'trips'),
                           by_driver=_bars(by_driver, 'trips'), dests=_bars(dests, 'trips'),
                           purposes=_bars(purposes, 'trips'), recent=_label(recent),
                           label=label, fy=fy, choices=choices, vtype=vtype, types=VEHICLE_TYPES)


HOME_SQL = f"""
    SELECT (SELECT coalesce(sum(amount), 0) FROM ({_COSTS}) c
             WHERE c.d >= %(fy0)s AND c.d < %(fy1)s) AS spent_fy,
           (SELECT coalesce(sum(amount), 0) FROM ({_COSTS}) c
             WHERE c.d >= date_trunc('month', CURRENT_DATE)::date AND kind = 'Fuel') AS fuel_month,
           (SELECT count(*) FROM wsb.trip WHERE start_datetime >= date_trunc('month', now())) AS trips_month,
           (SELECT coalesce(sum(greatest(ending_mileage - starting_mileage, 0)), 0) FROM wsb.trip
             WHERE start_datetime >= date_trunc('month', now())) AS miles_month,
           (SELECT count(*) FROM wsb.vehicle WHERE active AND status = 'Available') AS available,
           (SELECT count(*) FROM wsb.vehicle WHERE status <> 'Retired') AS vehicles,
           (SELECT count(*) FROM wsb.trip WHERE end_datetime IS NULL) AS out_now,
           (SELECT count(*) FROM wsb.vehicle_document
             WHERE expiration_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 60) AS expiring"""


def home_args():
    start = fiscal_year_of(dt.date.today())
    return {'fy0': dt.date(start, 7, 1), 'fy1': dt.date(start + 1, 7, 1)}, fy_label(start)

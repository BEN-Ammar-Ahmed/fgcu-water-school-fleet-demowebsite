"""Search across the fleet, grouped by type, limited to what the person may see.

Each group is a base SELECT that exposes:
  _text   everything that plain-text search looks in
  _date   (and optionally _date2) the date(s) a date search matches
  _vtype  vehicle type, for the vehicle-type filter
The outer query adds the text / date / filter conditions, so every group
searches the same way. User text only ever goes in as a query parameter.
"""
import calendar
import datetime as dt
import re

from tiers import doc_levels

KINDS = ['all', 'vehicles', 'trips', 'fuel', 'maintenance', 'documents', 'drivers', 'licenses']
GROUP_LIMIT = 50

_VT = ("concat_ws(' ', v.name, v.asset_number, v.year, v.make, v.model, v.notes, v.license_plate, v.vin, "
       "v.location, v.department, v.vehicle_type)")
_VCOLS = 'v.asset_number, v.year, v.make, v.model, v.notes, v.name, v.vehicle_type'

GROUPS = {
    'vehicles': {
        'sql': f"""SELECT v.vehicle_id, v.asset_number, v.vehicle_type, v.make, v.model, v.year, v.notes, v.name,
                          v.location, v.status, v.active, v.license_plate,
                          {_VT} AS _text, NULL::date AS _date, NULL::date AS _date2, v.vehicle_type AS _vtype
                   FROM wsb.vehicle v""",
        'order': 'vehicle_type, year DESC NULLS LAST, vehicle_id',
        'filters': {'vehicle_id', 'vehicle_type', 'status', 'location'},
    },
    'trips': {
        'sql': f"""SELECT t.trip_id, t.vehicle_id, {_VCOLS}, t.start_datetime, t.end_datetime,
                          t.starting_mileage, t.ending_mileage, t.destination, t.purpose, t.driver_id,
                          d.first_name || ' ' || d.last_name AS driver_name,
                          concat_ws(' ', {_VT}, t.destination, t.purpose, t.project_program,
                                    d.first_name || ' ' || d.last_name) AS _text,
                          t.start_datetime::date AS _date, NULL::date AS _date2, v.vehicle_type AS _vtype
                   FROM wsb.trip t JOIN wsb.vehicle v USING (vehicle_id) JOIN wsb.driver d ON d.driver_id = t.driver_id""",
        'order': 'start_datetime DESC, trip_id DESC',
        'filters': {'vehicle_id', 'driver_id', 'vehicle_type', 'date'},
    },
    'fuel': {
        'sql': f"""SELECT f.fuel_id, f.vehicle_id, {_VCOLS}, f.fuel_date, f.mileage, f.gallons, f.total_cost,
                          f.vendor, f.site_address, f.ticket_number,
                          concat_ws(' ', {_VT}, f.vendor, f.site_address, f.ticket_number, f.product) AS _text,
                          f.fuel_date AS _date, NULL::date AS _date2, v.vehicle_type AS _vtype
                   FROM wsb.fuel_record f JOIN wsb.vehicle v USING (vehicle_id)""",
        'order': 'fuel_date DESC, fuel_id DESC',
        'filters': {'vehicle_id', 'vehicle_type', 'date'},
    },
    'maintenance': {
        'sql': f"""SELECT 'Service record'::text AS entry, mr.maintenance_id AS id, mr.vehicle_id, {_VCOLS},
                          mr.service_type::text AS service, mr.service_date AS date, mr.vendor::text AS vendor, mr.cost,
                          concat_ws(' ', {_VT}, mr.service_type, mr.vendor, mr.description) AS _text,
                          mr.service_date AS _date, NULL::date AS _date2, v.vehicle_type AS _vtype
                   FROM wsb.maintenance_record mr JOIN wsb.vehicle v USING (vehicle_id)
                   UNION ALL
                   SELECT 'Schedule', r.rule_id, r.vehicle_id, {_VCOLS},
                          r.maintenance_type, r.last_completed_date, NULL, NULL,
                          concat_ws(' ', {_VT}, r.maintenance_type),
                          r.last_completed_date, NULL::date, v.vehicle_type
                   FROM wsb.maintenance_rule r JOIN wsb.vehicle v USING (vehicle_id) WHERE r.enabled""",
        'order': 'date DESC NULLS LAST, id DESC',
        'filters': {'vehicle_id', 'vehicle_type', 'date'},
    },
    'documents': {
        'sql': f"""SELECT d.document_id, d.vehicle_id, {_VCOLS}, d.document_type, d.issue_date, d.expiration_date,
                          d.access_level, d.notes AS doc_notes,
                          concat_ws(' ', {_VT}, d.document_type, d.notes) AS _text,
                          d.expiration_date AS _date, d.issue_date AS _date2, v.vehicle_type AS _vtype
                   FROM wsb.vehicle_document d JOIN wsb.vehicle v USING (vehicle_id)
                   WHERE d.access_level = ANY(%(levels)s)""",
        'order': 'expiration_date DESC NULLS LAST, document_id DESC',
        'filters': {'vehicle_id', 'vehicle_type', 'document_type', 'date'},
    },
    'drivers': {   # Tier 1 only: the way to reach a driver to edit them
        'sql': """SELECT d.driver_id, d.first_name || ' ' || d.last_name AS driver_name, d.department,
                         d.driver_type, d.approved, d.active,
                         concat_ws(' ', d.first_name, d.last_name, d.first_name || ' ' || d.last_name,
                                   d.department, d.email) AS _text,
                         NULL::date AS _date, NULL::date AS _date2, NULL::text AS _vtype
                  FROM wsb.driver d""",
        'order': 'driver_name, driver_id',
        'filters': {'driver_id'},
    },
    'licenses': {
        'sql': """SELECT l.license_id, l.driver_id, d.first_name || ' ' || d.last_name AS driver_name,
                         l.license_number, l.state, l.expiration_date,
                         concat_ws(' ', d.first_name, d.last_name, d.first_name || ' ' || d.last_name, l.license_number) AS _text,
                         l.expiration_date AS _date, NULL::date AS _date2, NULL::text AS _vtype
                  FROM wsb.driver_license l JOIN wsb.driver d USING (driver_id)""",
        'order': 'expiration_date DESC NULLS LAST, license_id DESC',
        'filters': {'driver_id', 'date'},
    },
}

_FILTER_SQL = {
    'vehicle_id': 'vehicle_id = %(vehicle_id)s',
    'driver_id': 'driver_id = %(driver_id)s',
    'vehicle_type': '_vtype = %(vehicle_type)s',
    'status': 'status = %(status)s',
    'location': 'location = %(location)s',
    'document_type': 'document_type = %(document_type)s',
}

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})


def _month_range(year: int, month: int) -> tuple[dt.date, dt.date]:
    start = dt.date(year, month, 1)
    return start, (dt.date(year + 1, 1, 1) if month == 12 else dt.date(year, month + 1, 1))  # year 9999 Dec -> ValueError


def parse_date_term(text: str) -> tuple[dt.date, dt.date] | None:
    """A date the text names, as a half-open range [start, end), or None."""
    t = (text or '').strip().lower()
    try:
        if m := re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})', t):
            d = dt.date(int(m[1]), int(m[2]), int(m[3]))
            return d, d + dt.timedelta(days=1)
        if m := re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', t):
            d = dt.date(int(m[3]), int(m[1]), int(m[2]))
            return d, d + dt.timedelta(days=1)
        if m := re.fullmatch(r'([a-z]+)\.?(?:\s+(\d{4}))?', t):
            if m[1] in _MONTHS:
                return _month_range(int(m[2]) if m[2] else dt.date.today().year, _MONTHS[m[1]])
    except (ValueError, OverflowError):   # e.g. 2026-13-45, or 9999-12-31 + 1 day
        return None
    return None


def escape_like(text: str) -> str:
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def run_search(q, user, text: str, kind: str = 'all', filters: dict | None = None, browse: bool = False) -> dict[str, dict]:
    """browse=True lists every row of one kind (no search text needed); not allowed for 'all'."""
    text = (text or '').strip()
    filters = {k: v for k, v in (filters or {}).items() if v not in (None, '')}
    if browse and kind not in GROUPS:
        return {}
    if not text and not filters and not browse:
        return {}
    names = [g for g in GROUPS if kind in ('all', None, '') or g == kind] if kind in KINDS else list(GROUPS)
    if not user.can_see_licenses:
        names = [g for g in names if g != 'licenses']
    if not user.is_admin:
        names = [g for g in names if g != 'drivers']

    params = {'pattern': f'%{escape_like(text)}%', 'levels': doc_levels(user), **filters}
    dates = parse_date_term(text) if text else None
    if dates:
        params['d0'], params['d1'] = dates
    if 'date_to' in filters:
        params['date_to_end'] = (filters['date_to'] + dt.timedelta(days=1)
                                 if filters['date_to'] < dt.date.max else filters['date_to'])

    out = {}
    for name in names:
        spec = GROUPS[name]
        where = []
        if text:
            cond = "_text ILIKE %(pattern)s ESCAPE '\\'"
            if dates:
                cond += (' OR (_date >= %(d0)s AND _date < %(d1)s)'
                         ' OR (_date2 >= %(d0)s AND _date2 < %(d1)s)')
            where.append(f'({cond})')
        # A group that can't apply one of the chosen filters is left out (break skips the else).
        for key, sql in _FILTER_SQL.items():
            if key in filters:
                if key not in spec['filters']:
                    break
                where.append(sql)
        else:
            if 'date' in spec['filters']:
                if 'date_from' in filters:
                    where.append('_date >= %(date_from)s')
                if 'date_to' in filters:
                    where.append('_date < %(date_to_end)s')
            elif 'date_from' in filters or 'date_to' in filters:
                continue
            cond = ' AND '.join(where) or 'TRUE'
            base = f"SELECT * FROM ({spec['sql']}) s WHERE {cond}"
            total = q(f'SELECT count(*) AS n FROM ({base}) c', params, one=True)['n']
            rows = q(f"{base} ORDER BY {spec['order']} LIMIT {GROUP_LIMIT}", params)
            for r in rows:
                for k in ('_text', '_date', '_date2', '_vtype'):
                    r.pop(k, None)
            out[name] = {'rows': rows, 'total': total}
    return out

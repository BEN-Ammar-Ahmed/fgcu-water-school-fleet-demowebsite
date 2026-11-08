"""Suggestions while typing: GET /suggest?field=<name>&q=<text> → grouped JSON.

Same access rules as search.py: drivers for admins only, documents by access level,
and driver licenses never. Close matches ("Rivra" → "Rivera") need pg_trgm; without it
only starts-with / contains matches are returned. User text only ever goes in as a parameter.
"""
from search import escape_like
from tiers import doc_levels

MIN_CHARS = 2
MAX_ITEMS = 8
PER_GROUP = 4
CLOSE = 0.4          # pg_trgm word_similarity needed to count as a close match

# None = not checked yet; '' = pg_trgm missing; otherwise the schema it lives in (Supabase: 'extensions').
TRGM_SCHEMA = None


def trgm_schema(q) -> str:
    global TRGM_SCHEMA
    if TRGM_SCHEMA is None:
        row = q("""SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
                   WHERE e.extname = 'pg_trgm'""", one=True)
        TRGM_SCHEMA = row['nspname'] if row else ''
    return TRGM_SCHEMA


_VEHICLE = """SELECT concat_ws(' · ', coalesce(nullif(trim(v.name), ''), nullif(concat_ws(' ', v.year, v.make, v.model), ''),
                                                'Vehicle #' || v.vehicle_id),
                               v.asset_number) AS label,
                     v.status AS detail, '/vehicles/' || v.vehicle_id AS url, v.vehicle_id::text AS value,
                     concat_ws(' ', v.name, v.asset_number, v.year, v.make, v.model, v.notes, v.vehicle_type, v.location) AS _t,
                     CASE WHEN v.active THEN 1 ELSE 0 END AS _n
              FROM wsb.vehicle v {where}"""

_DISTINCT = """SELECT x AS label, '' AS detail, NULL AS url, x AS value, x AS _t, count(*) AS _n
               FROM ({inner}) d(x) WHERE nullif(trim(x), '') IS NOT NULL GROUP BY x"""

_FREE_TEXT = {
    'vendor': 'SELECT vendor FROM wsb.fuel_record UNION ALL SELECT vendor FROM wsb.maintenance_record',
    'destination': 'SELECT destination FROM wsb.trip',
    'purpose': 'SELECT purpose FROM wsb.trip',
    'project_program': 'SELECT project_program FROM wsb.trip',
    'service_type': 'SELECT service_type FROM wsb.maintenance_record UNION ALL SELECT maintenance_type FROM wsb.maintenance_rule',
    'department': 'SELECT department FROM wsb.vehicle UNION ALL SELECT department FROM wsb.driver',
    'location': 'SELECT location FROM wsb.vehicle',
}


def _sources(user, field):
    """[(group label, SQL with columns label, detail, url, value, _t, _n)] this person may see for this field."""
    if field == 'search':
        out = [('Vehicles', _VEHICLE.format(where=''))]
        if user.is_admin:
            out.append(('Drivers', """SELECT first_name || ' ' || last_name AS label, coalesce(department, '') AS detail,
                                             '/search?kind=drivers&q=' || replace(replace(replace(last_name, '%%', '%%25'), '&', '%%26'), ' ', '%%20') AS url, driver_id::text AS value,
                                             first_name || ' ' || last_name AS _t, 1 AS _n FROM wsb.driver"""))
        out.append(('Maintenance', """SELECT r.maintenance_type || ' · ' || coalesce(nullif(trim(v.name), ''), concat_ws(' ', v.year, v.make, v.model)) AS label,
                                             '' AS detail, '/vehicles/' || v.vehicle_id || '#maintenance' AS url,
                                             r.rule_id::text AS value,
                                             concat_ws(' ', r.maintenance_type, v.name, v.asset_number, v.make, v.model, v.notes) AS _t,
                                             1 AS _n
                                      FROM wsb.maintenance_rule r JOIN wsb.vehicle v USING (vehicle_id)
                                      WHERE r.enabled AND v.active"""))
        out.append(('Documents', """SELECT d.document_type || ' · ' || coalesce(nullif(trim(v.name), ''), concat_ws(' ', v.year, v.make, v.model)) AS label,
                                           coalesce(to_char(d.expiration_date, 'Mon DD, YYYY'), '') AS detail,
                                           '/vehicles/' || v.vehicle_id || '#documents' AS url, d.document_id::text AS value,
                                           concat_ws(' ', d.document_type, v.asset_number, v.make, v.model) AS _t, 1 AS _n
                                    FROM wsb.vehicle_document d JOIN wsb.vehicle v USING (vehicle_id)
                                    WHERE d.access_level = ANY(%(levels)s)"""))
        return out
    if field == 'vehicle' and user.can_edit:
        return [('Vehicles', _VEHICLE.format(where='WHERE v.active'))]
    if field == 'driver' and user.can('trips_fuel'):
        return [('Drivers', """SELECT first_name || ' ' || last_name AS label, '' AS detail, NULL AS url,
                                      driver_id::text AS value, first_name || ' ' || last_name AS _t, 1 AS _n
                               FROM wsb.driver WHERE approved AND active AND email IS NOT NULL""")]
    if field == 'people' and user.is_admin:
        return [('People', """SELECT full_name AS label, coalesce(email, '') AS detail, NULL AS url, full_name AS value,
                                     concat_ws(' ', full_name, email) AS _t, 1 AS _n FROM wsb.app_user""")]
    if field == 'activity' and user.is_admin:
        return [('People', _DISTINCT.format(inner='SELECT full_name FROM wsb.activity_log'))]
    if field in _FREE_TEXT and user.can_edit:
        return [('Used before', _DISTINCT.format(inner=_FREE_TEXT[field]))]
    return []


def _clean(rows):
    return [{k: (r[k] if r[k] is not None else ('' if k != 'url' else None)) for k in ('label', 'detail', 'url', 'value')}
            for r in rows]


def suggest(q, user, field: str, text: str, q_many=None) -> dict:
    """q_many([(sql, args), ...]) runs one query per source at the same time (each round trip costs ~0.1 s)."""
    text = ' '.join((text or '').split())[:100]
    empty = {'groups': [], 'did_you_mean': None}
    sources = _sources(user, field) if user else []
    if len(text) < MIN_CHARS or not sources:
        return empty

    words = text.split()[:5]
    params = {'levels': doc_levels(user), 'text': text.lower(),
              'start': escape_like(text.lower()) + '%', 'word': '% ' + escape_like(text.lower()) + '%',
              **{f'w{i}': f'%{escape_like(w)}%' for i, w in enumerate(words)}}
    match = ' AND '.join(f"_t ILIKE %(w{i})s ESCAPE '\\'" for i in range(len(words)))
    schema = trgm_schema(q)

    # One query per source: its normal matches (_close = 0) and, with pg_trgm, its close matches (_close = 1).
    queries = []
    for _, sql in sources:
        one = f"""(SELECT *, 0 AS _close, 1.0::real AS _sim FROM ({sql}) s WHERE {match}
                   ORDER BY CASE WHEN lower(_t) LIKE %(start)s ESCAPE '\\' THEN 0
                                 WHEN lower(_t) LIKE %(word)s ESCAPE '\\' THEN 1 ELSE 2 END,
                            _n DESC, label LIMIT {PER_GROUP})"""
        if schema:
            one += f""" UNION ALL
                    (SELECT *, 1 AS _close, {schema}.word_similarity(%(text)s, lower(_t)) AS _sim FROM ({sql}) s
                     WHERE NOT ({match}) AND {schema}.word_similarity(%(text)s, lower(_t)) >= {CLOSE}
                     ORDER BY _sim DESC, _n DESC LIMIT 3)"""
        queries.append((one, params))
    results = (q_many or (lambda qs: [q(s, a) for s, a in qs]))(queries)

    groups, total, close = [], 0, []
    for (label, _), found in zip(sources, results):
        rows = [r for r in found if not r['_close']][:max(0, MAX_ITEMS - total)]
        if rows:
            groups.append({'label': label, 'items': _clean(rows)})
            total += len(rows)
        close += [r for r in found if r['_close']]

    if close and total < MAX_ITEMS:
        close.sort(key=lambda r: -r['_sim'])
        groups.append({'label': 'Close matches', 'items': _clean(close[:MAX_ITEMS - total])})

    out = {'groups': groups, 'did_you_mean': None}
    if total == 0 and field == 'search':
        out['did_you_mean'] = did_you_mean(q, user, text)
    if field == 'search' and groups:
        groups[-1]['items'].append({'label': 'See all results', 'detail': '', 'url': None, 'value': text, 'all': True})
    return out


def did_you_mean(q, user, text: str) -> str | None:
    """The closest known make / model / driver name / maintenance type, or None (always None without pg_trgm)."""
    schema = trgm_schema(q)
    if not schema or len((text or '').strip()) < MIN_CHARS:
        return None
    drivers = "UNION SELECT first_name || ' ' || last_name FROM wsb.driver" if user.is_admin else ''
    row = q(f"""SELECT t, greatest({schema}.similarity(lower(t), %(text)s), {schema}.word_similarity(%(text)s, lower(t))) AS s
                FROM (SELECT make AS t FROM wsb.vehicle UNION SELECT model FROM wsb.vehicle
                      UNION SELECT concat_ws(' ', make, model) FROM wsb.vehicle
                      UNION SELECT maintenance_type FROM wsb.maintenance_rule {drivers}) x
                WHERE t IS NOT NULL AND lower(t) <> %(text)s
                ORDER BY s DESC, length(t) LIMIT 1""", {'text': text.lower().strip()}, one=True)
    return row['t'] if row and row['s'] >= CLOSE else None

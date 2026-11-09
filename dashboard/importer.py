"""Spreadsheet import (Admin → Import): read a file, match its columns, check every row, save all or nothing.

The uploaded file is read in memory and never stored. Nothing reaches the database until the
person reviews the rows and clicks Save, and then every row is saved in one transaction.
"""
import csv
import datetime as dt
import io
import re

from common import display_name
from forms import Field, parse

MAX_ROWS = 2000

# What each kind of import fills, in order. aliases = header words that probably mean this field.
TARGETS = {
    'drivers': {
        'label': 'Drivers',
        'fields': [
            (Field('first_name', 'First name', required=True), ['first', 'firstname', 'fname', 'givenname']),
            (Field('last_name', 'Last name', required=True), ['last', 'lastname', 'lname', 'surname', 'familyname']),
            (Field('email', 'Email'), ['email', 'emailaddress', 'fgcuemail', 'mail']),
            (Field('department', 'Department'), ['department', 'dept', 'program', 'unit']),
            (Field('driver_type', 'Type', 'select', options=[(t, t) for t in ('Faculty', 'Staff', 'OPS', 'Other')]),
             ['type', 'drivertype', 'position', 'role', 'classification']),
            (Field('approved', 'Approved to drive', 'bool'), ['approved', 'authorized', 'approvedtodrive', 'status']),
            (Field('license_number', 'License number'), ['license', 'licensenumber', 'licenseno', 'dl', 'dlnumber', 'driverslicense']),
            (Field('state', 'License state'), ['state', 'licensestate', 'dlstate', 'issuingstate']),
            (Field('license_expiration', 'License expires', 'date'), ['expiration', 'expires', 'licenseexpiration', 'dlexpiration', 'expdate', 'expirationdate']),
        ],
    },
    'vehicles': {
        'label': 'Vehicles',
        'fields': [
            (Field('name', 'Name'), ['name', 'description', 'vehicle', 'vehiclename', 'unit']),
            (Field('asset_number', 'Property tag', required=True), ['asset', 'assetnumber', 'assetno', 'propertytag', 'tag', 'property', 'fgcutag', 'inventory']),
            (Field('vehicle_type', 'Type', 'select', required=True,
                   options=[(t, t) for t in ('Boat', 'Car', 'Truck', 'Trailer', 'Golf Cart', 'ATV', 'Other')]), ['type', 'vehicletype', 'category', 'class']),
            (Field('year', 'Year', 'int'), ['year', 'modelyear', 'yr']),
            (Field('make', 'Make'), ['make', 'manufacturer', 'brand', 'mfr']),
            (Field('model', 'Model'), ['model']),
            (Field('vin', 'VIN / hull number'), ['vin', 'hin', 'hull', 'hullnumber', 'serial', 'serialnumber', 'vinhin']),
            (Field('license_plate', 'Plate / registration'), ['plate', 'licenseplate', 'tagnumber', 'registration', 'regnumber', 'flnumber']),
            (Field('department', 'Department'), ['department', 'dept']),
            (Field('location', 'Location'), ['location', 'kept', 'parked', 'site', 'storage']),
            (Field('current_mileage', 'Mileage', 'int'), ['mileage', 'miles', 'odometer', 'currentmileage']),
            (Field('current_hours', 'Engine hours', 'num'), ['hours', 'enginehours']),
            (Field('notes', 'Notes', 'textarea'), ['notes', 'comments', 'remarks']),
        ],
    },
    'fuel': {
        'label': 'Fuel purchases',
        'fields': [
            (Field('asset_number', 'Vehicle (tag or name)', required=True), ['asset', 'assetnumber', 'assetno', 'propertytag', 'tag', 'vehicle', 'vehiclevessel', 'vessel', 'boat', 'vehiclename', 'unit', 'vehiclenumber']),
            (Field('fuel_date', 'Date', 'date', required=True), ['date', 'fueldate', 'transactiondate', 'purchasedate']),
            (Field('gallons', 'Gallons', 'num', required=True), ['gallons', 'gal', 'quantity', 'units', 'qty']),
            (Field('total_cost', 'Total cost', 'num', required=True), ['total', 'cost', 'amount', 'totalcost', 'grossamount', 'netamount', 'price']),
            (Field('mileage', 'Mileage', 'int'), ['mileage', 'odometer', 'miles']),
            (Field('vendor', 'Station / vendor'), ['vendor', 'station', 'merchant', 'merchantname', 'site', 'sitename']),
        ],
    },
    'maintenance': {
        'label': 'Maintenance / repairs',
        'fields': [
            (Field('asset_number', 'Vehicle (tag or name)', required=True), ['asset', 'assetnumber', 'assetno', 'propertytag', 'tag', 'vehicle', 'vehiclevessel', 'vessel', 'boat', 'vehiclename', 'unit', 'vehiclenumber']),
            (Field('service_date', 'Date', 'date', required=True), ['date', 'servicedate', 'datein', 'repairdate']),
            (Field('service_type', 'Service', required=True), ['service', 'servicetype', 'repairitems', 'repairs', 'items', 'type', 'work', 'repair', 'job']),
            (Field('cost', 'Cost', 'num'), ['cost', 'totalcost', 'amount', 'total', 'price', 'invoiceamount']),
            (Field('vendor', 'Vendor'), ['vendor', 'shop', 'company', 'provider']),
            (Field('mileage_at_service', 'Mileage', 'int'), ['mileage', 'odometer', 'miles', 'hours']),
            (Field('description', 'What was done', 'textarea'), ['description', 'details', 'notes', 'workdone', 'comments']),
            (Field('purchaser', 'Purchaser'), ['purchaser', 'purchasedby', 'buyer', 'cardholder']),
            (Field('funding_source', 'Funding source / account'), ['fundingsource', 'fundingsurceaccount', 'fundingsourceaccount', 'funding', 'account', 'fund', 'costcenter']),
            (Field('pcard_workday_no', 'P-Card Workday #'), ['pcardworkday', 'pcardworkdayno', 'pcard', 'workday', 'workdayno', 'pcardnumber']),
        ],
    },
    'schedules': {
        'label': 'Maintenance schedules',
        'fields': [
            (Field('asset_number', 'Vehicle (tag or name)', required=True), ['asset', 'assetnumber', 'assetno', 'propertytag', 'tag', 'vehicle', 'vehiclevessel', 'vessel', 'boat', 'vehiclename', 'unit', 'vehiclenumber']),
            (Field('maintenance_type', 'Service', required=True), ['service', 'maintenancetype', 'maintenance', 'task', 'item', 'type', 'servicetype']),
            (Field('time_interval_months', 'Every (months)', 'int'), ['months', 'everymonths', 'intervalmonths', 'frequencymonths', 'timeinterval', 'monthinterval']),
            (Field('mileage_interval', 'Every (miles or hours)', 'int'), ['miles', 'everymiles', 'mileageinterval', 'intervalmiles', 'hoursinterval', 'everyhours']),
            (Field('last_completed_date', 'Last done', 'date'), ['lastdone', 'lastcompleted', 'lastservice', 'datelastchanged', 'lastchanged', 'lastdate', 'datelastdone']),
            (Field('last_completed_mileage', 'Mileage when last done', 'int'), ['lastmileage', 'mileagelastdone', 'lastcompletedmileage', 'lasthours']),
        ],
    },
    'trips': {
        'label': 'Trips',
        'fields': [
            (Field('asset_number', 'Vehicle (tag or name)', required=True), ['asset', 'assetnumber', 'assetno', 'propertytag', 'tag', 'vehicle', 'vehiclevessel', 'vessel', 'boat', 'vehiclename', 'unit', 'vehiclenumber']),
            (Field('driver_email', 'Driver email', required=True), ['driveremail', 'email', 'driver']),
            (Field('start_datetime', 'Start', 'datetime', required=True), ['start', 'date', 'startdate', 'departure', 'out', 'dateout']),
            (Field('end_datetime', 'End', 'datetime'), ['end', 'enddate', 'return', 'returned', 'datein']),
            (Field('starting_mileage', 'Starting mileage', 'int'), ['startmileage', 'startingmileage', 'odometerout', 'beginmileage', 'mileageout']),
            (Field('ending_mileage', 'Ending mileage', 'int'), ['endmileage', 'endingmileage', 'odometerin', 'mileagein']),
            (Field('destination', 'Destination'), ['destination', 'to', 'where', 'location']),
            (Field('purpose', 'Purpose'), ['purpose', 'reason']),
            (Field('project_program', 'Project / program'), ['project', 'program', 'projectprogram', 'grant']),
        ],
    },
}

HIDDEN = {'license_number'}     # shown masked on the review screen


def fields(target):
    return [f for f, _ in TARGETS[target]['fields']]


def _key(text) -> str:
    return re.sub(r'[^a-z0-9]', '', str(text or '').lower())


def _cell(v) -> str:
    if v is None:
        return ''
    if isinstance(v, dt.datetime):
        return v.strftime('%Y-%m-%dT%H:%M') if (v.hour or v.minute) else v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def read_table(filename: str, data: bytes) -> tuple[list[str], list[list[str]]]:
    """Header row + data rows as text. Raises ValueError with a plain message."""
    name = (filename or '').lower()
    if name.endswith('.csv'):
        text = data.decode('utf-8-sig', errors='replace')
        grid = [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]
    elif name.endswith(('.xlsx', '.xlsm')):
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise ValueError('That file could not be opened as an Excel workbook.')
        ws = wb.worksheets[0]
        grid = [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
    elif name.endswith(('.pdf', '.jpg', '.jpeg', '.png', '.doc', '.docx', '.heic')):
        raise ValueError("That's a document, not a spreadsheet. This page only reads Excel (.xlsx) or CSV files. "
                         "To keep a PDF or a scan, open the vehicle's page and add it under Documents.")
    else:
        raise ValueError('Upload an Excel (.xlsx) or CSV file.')
    grid = [r for r in grid if any(c for c in r)]
    if not grid:
        raise ValueError('The file is empty.')
    # The header is the first row with at least two filled cells (skips a title row above the table).
    start = next((i for i, r in enumerate(grid) if sum(1 for c in r if c) >= 2), 0)
    headers = [h or f'Column {i + 1}' for i, h in enumerate(grid[start])]
    rows = [(r + [''] * len(headers))[:len(headers)] for r in grid[start + 1:]]
    if len(rows) > MAX_ROWS:
        raise ValueError(f'The file has {len(rows):,} rows. Import at most {MAX_ROWS:,} at a time.')
    if not rows:
        raise ValueError('The file has a header row but no data rows.')
    return headers, rows


def guess_mapping(target: str, headers: list[str]) -> dict[str, int | None]:
    """Field name → column index, from header names. Exact alias matches first, then 'contains'."""
    keys = [_key(h) for h in headers]
    used, out = set(), {}
    for f, aliases in TARGETS[target]['fields']:
        names = [_key(f.name), _key(f.label)] + aliases
        hit = next((i for i, k in enumerate(keys) if k in names and i not in used), None)
        if hit is None:
            hit = next((i for i, k in enumerate(keys) if i not in used and k and
                        any(len(a) >= 4 and a in k for a in names)), None)
        out[f.name] = hit
        if hit is not None:
            used.add(hit)
    return out


def apply_mapping(target, mapping, rows) -> list[dict]:
    return [{f.name: (r[mapping[f.name]] if mapping.get(f.name) is not None else '') for f in fields(target)}
            for r in rows]


_BOOL_WORDS = {'on': 'on', 'yes': 'on', 'y': 'on', 'true': 'on', 'x': 'on', '1': 'on', 'approved': 'on', 'active': 'on',
               'authorized': 'on'}


def _normalise(f, raw: str) -> str:
    raw = (raw or '').strip()
    if f.kind == 'bool':
        return _BOOL_WORDS.get(raw.lower(), '')
    if f.kind in ('date', 'datetime') and raw:
        for fmt in ('%m/%d/%Y', '%m/%d/%y', '%m-%d-%Y', '%Y/%m/%d', '%m/%d/%Y %H:%M', '%m/%d/%Y %I:%M %p'):
            try:
                d = dt.datetime.strptime(raw, fmt)
                return d.date().isoformat() if f.kind == 'date' else d.strftime('%Y-%m-%dT%H:%M')
            except ValueError:
                pass
        if f.kind == 'date' and len(raw) > 10 and raw[:10].count('-') == 2:
            return raw[:10]
    if f.kind == 'select' and raw:
        for v, _ in f.options:
            if v.lower() == raw.lower():
                return v
    return raw


class VehicleFinder:
    """Finds a vehicle from what a spreadsheet calls it: a property tag ('6896'), its Name ('Mako'), or
    year make model ('2013 Ford F-150', 'Ford F150'). Spaces, dashes and case don't matter."""

    def __init__(self, q):
        self.rows = q('SELECT vehicle_id, asset_number, name, year, make, model, vehicle_type FROM wsb.vehicle')
        self.by_tag, self.by_name = {}, {}
        for v in self.rows:
            v['label'] = display_name(v)
            if v['asset_number']:
                self.by_tag[_key(v['asset_number'])] = v
            for n in {v['name'], v['label'], f"{v['make'] or ''} {v['model'] or ''}",
                      f"{v['year'] or ''} {v['make'] or ''} {v['model'] or ''}"}:
                if _key(n):
                    self.by_name.setdefault(_key(n), []).append(v)

    def find(self, text):
        """(vehicle row, None) or (None, plain-English problem)."""
        k = _key(text)
        if not k:
            return None, None
        if k in self.by_tag:
            return self.by_tag[k], None
        hits = {v['vehicle_id']: v for v in self.by_name.get(k, [])}
        if len(hits) == 1:
            return next(iter(hits.values())), None
        if len(hits) > 1:
            tags = ', '.join(v['asset_number'] or f"#{v['vehicle_id']}" for v in hits.values())
            return None, f'"{text}" matches {len(hits)} vehicles ({tags}). Use the property tag instead.'
        import difflib
        best = difflib.get_close_matches(k, list(self.by_name) + list(self.by_tag), n=1, cutoff=0.75)
        hint = ''
        if best:
            v = self.by_tag.get(best[0]) or self.by_name[best[0]][0]
            hint = f' Did you mean {v["label"]}' + (f' ({v["asset_number"]})' if v['asset_number'] else '') + '?'
        return None, f'No vehicle called "{text}".{hint}'


def check(q, user, target: str, records: list[dict]) -> list[dict]:
    """Each record → {'raw', 'values', 'errors', 'warnings'}. raw is what the review screen shows."""
    fl = fields(target)
    finder = VehicleFinder(q)
    tags = set(finder.by_tag)
    out, seen = [], set()
    seen_unique = set()
    for rec in records:
        raw = {f.name: _normalise(f, rec.get(f.name, '')) for f in fl}
        if target == 'drivers' and not user.can_see_licenses:
            for k in ('license_number', 'state', 'license_expiration'):
                raw[k] = ''
        values, errors = parse(fl, raw)
        warnings = []
        tag = (values.get('asset_number') or '').lower()
        if target in ('fuel', 'maintenance', 'trips', 'schedules') and tag:
            v, problem = finder.find(values['asset_number'])
            if problem:
                errors.append(problem)
            elif v:
                values['vehicle_id'] = v['vehicle_id']
                if _key(values['asset_number']) != _key(v['asset_number']):
                    warnings.append(f"Matched to {v['label']}" + (f" ({v['asset_number']})" if v['asset_number'] else '') + '.')
        if target == 'vehicles' and _key(tag) in tags:
            errors.append(f"A vehicle with property tag {values['asset_number']} already exists.")
        if target == 'trips' and values.get('driver_email') and not q(
                'SELECT 1 FROM wsb.driver WHERE lower(email) = lower(%s) AND approved AND active', (values['driver_email'],), one=True):
            errors.append(f"{values['driver_email']} is not an approved, active driver.")
        if target == 'drivers':
            if values.get('email') and q('SELECT 1 FROM wsb.driver WHERE lower(email) = lower(%s)', (values['email'],), one=True):
                errors.append(f"A driver with email {values['email']} already exists.")
            elif not values.get('email') and values.get('first_name') and q(
                    'SELECT 1 FROM wsb.driver WHERE lower(first_name) = lower(%s) AND lower(last_name) = lower(%s)',
                    (values['first_name'], values.get('last_name') or ''), one=True):
                warnings.append('A driver with this name already exists.')
        if target == 'fuel' and not errors and q(
                """SELECT 1 FROM wsb.fuel_record f
                   WHERE f.vehicle_id = %s AND f.fuel_date = %s AND f.total_cost = %s""",
                (values.get('vehicle_id'), values['fuel_date'], values['total_cost']), one=True):
            warnings.append('Looks like a duplicate: same vehicle, date and cost is already saved.')
        if target == 'maintenance' and not errors and q(
                """SELECT 1 FROM wsb.maintenance_record m
                   WHERE m.vehicle_id = %s AND m.service_date = %s AND lower(m.service_type) = lower(%s)""",
                (values.get('vehicle_id'), values['service_date'], values['service_type']), one=True):
            warnings.append('Looks like a duplicate: same vehicle, date and service is already saved.')
        if target == 'schedules':
            if not values.get('time_interval_months') and not values.get('mileage_interval'):
                errors.append('Say how often: every N months, every N miles (or hours), or both.')
            for k in ('time_interval_months', 'mileage_interval'):
                if values.get(k) is not None and values[k] <= 0:
                    errors.append('How often must be more than 0.')
            if values.get('vehicle_id') and values.get('maintenance_type') and q(
                    """SELECT 1 FROM wsb.maintenance_rule WHERE vehicle_id = %s AND lower(maintenance_type) = lower(%s)
                       AND enabled""", (values['vehicle_id'], values['maintenance_type']), one=True):
                errors.append(f"This vehicle already has a {values['maintenance_type']} schedule.")
        key = tuple(str(values.get(f.name)) for f in fl)
        if key in seen:
            warnings.append('Same as an earlier row in this file.')
        seen.add(key)
        # Must be unique: a second row with the same tag / email would make the whole save fail.
        unique = (target == 'vehicles' and tag and ('tag', tag)) or                  (target == 'schedules' and values.get('vehicle_id') and values.get('maintenance_type') and
                  ('schedule', values['vehicle_id'], values['maintenance_type'].lower())) or \
                 (target == 'drivers' and values.get('email') and ('email', values['email'].lower()))
        if unique and unique in seen_unique:
            if unique[0] == 'schedule':
                errors.append(f"The {values['maintenance_type']} schedule for this vehicle is in the file twice.")
            else:
                errors.append(f"{'Property tag' if unique[0] == 'tag' else 'Email'} "
                              f"{values.get('asset_number') or values.get('email')} is used twice in this file.")
        if unique:
            seen_unique.add(unique)
        out.append({'raw': raw, 'values': values, 'errors': errors, 'warnings': warnings})
    return out


def mask(value: str) -> str:
    v = (value or '').strip()
    return ('●' * max(0, len(v) - 4) + v[-4:]) if v else ''


VEHICLE_COLS = ['name', 'asset_number', 'vehicle_type', 'year', 'make', 'model', 'vin', 'license_plate',
                'department', 'location', 'current_mileage', 'current_hours', 'notes']


def _save_service(cur, v):
    """One service record. If the row says who paid (purchaser, funding source or P-Card #), it is also saved as
    an invoice with one line, and the service record points at that line, so the cost is counted once."""
    line_id = None
    if v.get('purchaser') or v.get('funding_source') or v.get('pcard_workday_no'):
        cur.execute("""INSERT INTO wsb.invoice (invoice_type, vendor, invoice_date, total_amount, funding_source,
                                                pcard_workday_no, purchaser, notes)
                       VALUES ('Maintenance', %s, %s, %s, %s, %s, %s, 'Imported from a spreadsheet')
                       RETURNING invoice_id""",
                    ((v.get('vendor') or 'Unknown vendor')[:80], v['service_date'], v.get('cost') or 0,
                     (v.get('funding_source') or '')[:80] or None, (v.get('pcard_workday_no') or '')[:40] or None,
                     (v.get('purchaser') or '')[:80] or None))
        inv = cur.fetchone()['invoice_id']
        cur.execute("""INSERT INTO wsb.invoice_line (invoice_id, vehicle_id, line_date, category, description, amount)
                       VALUES (%s, %s, %s, 'Repair', %s, %s) RETURNING line_id""",
                    (inv, v['vehicle_id'], v['service_date'], v['service_type'], v.get('cost') or 0))
        line_id = cur.fetchone()['line_id']
    # Same as wsb.add_maintenance: a record with the same name as a schedule moves that schedule forward.
    cur.execute("""SELECT rule_id FROM wsb.maintenance_rule
                   WHERE vehicle_id = %s AND lower(maintenance_type) = lower(%s) AND enabled ORDER BY rule_id LIMIT 1""",
                (v['vehicle_id'], v['service_type']))
    rule = cur.fetchone()
    cur.execute("""INSERT INTO wsb.maintenance_record (vehicle_id, rule_id, invoice_line_id, service_date, mileage_at_service,
                                                       service_type, cost, vendor, description)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (v['vehicle_id'], rule and rule['rule_id'], line_id, v['service_date'], v.get('mileage_at_service'),
                 v['service_type'][:50], v.get('cost'), (v.get('vendor') or '')[:50] or None, v.get('description')))
    if rule:
        cur.execute("""UPDATE wsb.maintenance_rule SET last_completed_date = greatest(last_completed_date, %s),
                              last_completed_mileage = coalesce(%s, last_completed_mileage)
                       WHERE rule_id = %s""", (v['service_date'], v.get('mileage_at_service'), rule['rule_id']))


def save(conn, user, target: str, rows: list[dict]) -> int:
    """Insert every row in one transaction. Raises (and saves nothing) if any row fails."""
    i = 0
    with conn.cursor() as cur:
        try:
            for i, values in enumerate(rows, 1):
                cur.execute(f'SAVEPOINT r{i}')
                if target == 'fuel':
                    cur.execute("""INSERT INTO wsb.fuel_record (vehicle_id, fuel_date, mileage, gallons, total_cost, vendor)
                                   VALUES (%(vehicle_id)s, %(fuel_date)s, %(mileage)s, %(gallons)s, %(total_cost)s, %(vendor)s)""",
                                values)
                elif target == 'trips':
                    cur.execute("""INSERT INTO wsb.trip (vehicle_id, driver_id, start_datetime, end_datetime, starting_mileage,
                                                       ending_mileage, destination, purpose, project_program)
                                   SELECT %(vehicle_id)s, d.driver_id, %(start_datetime)s, %(end_datetime)s, %(starting_mileage)s,
                                          %(ending_mileage)s, %(destination)s, %(purpose)s, %(project_program)s
                                   FROM wsb.driver d WHERE lower(d.email) = lower(%(driver_email)s) AND d.approved AND d.active""",
                                values)
                    if cur.rowcount != 1:
                        raise ValueError(f"{values['driver_email']} is not an approved, active driver.")
                elif target == 'maintenance':
                    _save_service(cur, values)
                elif target == 'schedules':
                    cur.execute("""INSERT INTO wsb.maintenance_rule (vehicle_id, maintenance_type, mileage_interval,
                                       time_interval_months, last_completed_mileage, last_completed_date)
                                   VALUES (%(vehicle_id)s, %(maintenance_type)s, %(mileage_interval)s, %(time_interval_months)s,
                                           %(last_completed_mileage)s, %(last_completed_date)s)""", values)
                elif target == 'vehicles':
                    v = {k: values.get(k) for k in VEHICLE_COLS}
                    v['status'], v['active'] = 'Available', True
                    cur.execute(f"INSERT INTO wsb.vehicle ({', '.join(v)}) VALUES ({', '.join(['%s'] * len(v))})",
                                list(v.values()))
                elif target == 'drivers':
                    d = {k: values.get(k) for k in ('first_name', 'last_name', 'email', 'department', 'driver_type')}
                    d['approved'], d['active'] = bool(values.get('approved')), True
                    cur.execute(f"INSERT INTO wsb.driver ({', '.join(d)}) VALUES ({', '.join(['%s'] * len(d))}) "
                                'RETURNING driver_id', list(d.values()))
                    did = cur.fetchone()['driver_id']
                    if user.can_see_licenses and values.get('license_number'):
                        cur.execute('INSERT INTO wsb.driver_license (driver_id, license_number, state, expiration_date) '
                                    'VALUES (%s, %s, %s, %s)',
                                    (did, values['license_number'], values.get('state'), values.get('license_expiration')))
            conn.commit()
        except Exception as e:
            conn.rollback()
            e.import_row = i
            raise
    return len(rows)

"""Spreadsheet import (Admin → Import): read a file, match its columns, check every row, save all or nothing.

The uploaded file is read in memory and never stored. Nothing reaches the database until the
person reviews the rows and clicks Save, and then every row is saved in one transaction.
"""
import csv
import datetime as dt
import io
import re

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
            (Field('asset_number', 'Property tag', required=True), ['asset', 'assetnumber', 'propertytag', 'tag', 'vehicle', 'vehiclenumber', 'unit']),
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
            (Field('asset_number', 'Property tag', required=True), ['asset', 'assetnumber', 'propertytag', 'tag', 'vehicle', 'unit']),
            (Field('service_date', 'Date', 'date', required=True), ['date', 'servicedate', 'datein', 'repairdate']),
            (Field('service_type', 'Service', required=True), ['service', 'servicetype', 'type', 'work', 'repair', 'job']),
            (Field('cost', 'Cost', 'num'), ['cost', 'amount', 'total', 'price', 'invoiceamount']),
            (Field('vendor', 'Vendor'), ['vendor', 'shop', 'company', 'provider']),
            (Field('mileage_at_service', 'Mileage', 'int'), ['mileage', 'odometer', 'miles', 'hours']),
            (Field('description', 'What was done', 'textarea'), ['description', 'details', 'notes', 'workdone', 'comments']),
        ],
    },
    'trips': {
        'label': 'Trips',
        'fields': [
            (Field('asset_number', 'Property tag', required=True), ['asset', 'assetnumber', 'propertytag', 'tag', 'vehicle', 'unit']),
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


def check(q, user, target: str, records: list[dict]) -> list[dict]:
    """Each record → {'raw', 'values', 'errors', 'warnings'}. raw is what the review screen shows."""
    fl = fields(target)
    tags = {r['asset_number'].lower() for r in q('SELECT asset_number FROM wsb.vehicle WHERE asset_number IS NOT NULL')}
    out, seen = [], set()
    for rec in records:
        raw = {f.name: _normalise(f, rec.get(f.name, '')) for f in fl}
        if target == 'drivers' and not user.can_see_licenses:
            for k in ('license_number', 'state', 'license_expiration'):
                raw[k] = ''
        values, errors = parse(fl, raw)
        warnings = []
        tag = (values.get('asset_number') or '').lower()
        if target in ('fuel', 'maintenance', 'trips') and tag and tag not in tags:
            errors.append(f"No vehicle has property tag {values['asset_number']}.")
        if target == 'vehicles' and tag and tag in tags:
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
                """SELECT 1 FROM wsb.fuel_record f JOIN wsb.vehicle v USING (vehicle_id)
                   WHERE lower(v.asset_number) = %s AND f.fuel_date = %s AND f.total_cost = %s""",
                (tag, values['fuel_date'], values['total_cost']), one=True):
            warnings.append('Looks like a duplicate: same vehicle, date and cost is already saved.')
        if target == 'maintenance' and not errors and q(
                """SELECT 1 FROM wsb.maintenance_record m JOIN wsb.vehicle v USING (vehicle_id)
                   WHERE lower(v.asset_number) = %s AND m.service_date = %s AND lower(m.service_type) = lower(%s)""",
                (tag, values['service_date'], values['service_type']), one=True):
            warnings.append('Looks like a duplicate: same vehicle, date and service is already saved.')
        key = tuple(str(values.get(f.name)) for f in fl)
        if key in seen:
            warnings.append('Same as an earlier row in this file.')
        seen.add(key)
        out.append({'raw': raw, 'values': values, 'errors': errors, 'warnings': warnings})
    return out


def mask(value: str) -> str:
    v = (value or '').strip()
    return ('●' * max(0, len(v) - 4) + v[-4:]) if v else ''


_SQL = {
    'fuel': """SELECT wsb.add_fuel(p_asset_number => %(asset_number)s, p_fuel_date => %(fuel_date)s,
               p_gallons => %(gallons)s, p_total_cost => %(total_cost)s, p_mileage => %(mileage)s, p_vendor => %(vendor)s)""",
    'maintenance': """SELECT wsb.add_maintenance(p_asset_number => %(asset_number)s, p_service_date => %(service_date)s,
               p_service_type => %(service_type)s, p_cost => %(cost)s, p_vendor => %(vendor)s,
               p_mileage_at_service => %(mileage_at_service)s, p_description => %(description)s)""",
    'trips': """SELECT wsb.add_trip(p_asset_number => %(asset_number)s, p_driver_email => %(driver_email)s,
               p_start_datetime => %(start_datetime)s, p_end_datetime => %(end_datetime)s,
               p_starting_mileage => %(starting_mileage)s, p_ending_mileage => %(ending_mileage)s,
               p_destination => %(destination)s, p_purpose => %(purpose)s, p_project_program => %(project_program)s)""",
}

VEHICLE_COLS = ['name', 'asset_number', 'vehicle_type', 'year', 'make', 'model', 'vin', 'license_plate',
                'department', 'location', 'current_mileage', 'current_hours', 'notes']


def save(conn, user, target: str, rows: list[dict]) -> int:
    """Insert every row in one transaction. Raises (and saves nothing) if any row fails."""
    i = 0
    with conn.cursor() as cur:
        try:
            for i, values in enumerate(rows, 1):
                cur.execute(f'SAVEPOINT r{i}')
                if target in _SQL:
                    cur.execute(_SQL[target], values)
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

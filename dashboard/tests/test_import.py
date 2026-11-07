"""Import a spreadsheet: upload → match → review → save (all or nothing). Files are made in the test, never stored."""
import io
import json
import re

import openpyxl
import pytest

import importer


def _xlsx(rows):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _csv(rows):
    return '\n'.join(','.join(str(c) for c in r) for r in rows).encode()


def _upload(client, target, name, data):
    return client.post('/import', data={'target': target, 'file': (io.BytesIO(data), name)},
                       content_type='multipart/form-data')


def _match_form(html):
    """The hidden fields and the selected column for each field on the match page."""
    form = {k: v for k, v in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', html)}
    form['table'] = form['table'].replace('&#34;', '"').replace('&quot;', '"').replace('&#39;', "'").replace('&amp;', '&')
    for name, body in re.findall(r'<select name="(map_[^"]+)"[^>]*>(.*?)</select>', html, re.S):
        m = re.search(r'<option value="(\d*)" selected', body)
        form[name] = m.group(1) if m else ''
    return form


def _review(client, target, name, data):
    html = _upload(client, target, name, data).get_data(as_text=True)
    return client.post('/import/review', data=_match_form(html))


def _review_form(html):
    form = {k: v.replace('&amp;', '&') for k, v in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', html)}
    form.update({k: v.replace('&amp;', '&') for k, v in re.findall(r'<input name="(c\d+_[a-z_]+)" value="([^"]*)"', html)})
    for k in re.findall(r'<input type="checkbox" name="(keep\d+)" checked', html):
        form[k] = 'on'
    for name, body in re.findall(r'<select name="(c\d+_[a-z_]+)"[^>]*>(.*?)</select>', html, re.S):
        form[name] = 'on' if 'value="on" selected' in body else ''
    return form


# ----- reading and guessing (no database) ------------------------------------------------------
def test_read_xlsx_skips_title_row_and_blank_lines():
    data = _xlsx([['Fleet list 2026'], [], ['Asset #', 'Year', 'Make'], ['T-1', 2019, 'Ford'], [None, None, None]])
    headers, rows = importer.read_table('fleet.xlsx', data)
    assert headers == ['Asset #', 'Year', 'Make'] and rows == [['T-1', '2019', 'Ford']]


def test_read_rejects_other_files_and_empty():
    with pytest.raises(ValueError, match='xlsx'):
        importer.read_table('scan.pdf', b'%PDF')
    with pytest.raises(ValueError, match='empty'):
        importer.read_table('x.csv', b'\n\n')
    with pytest.raises(ValueError, match='could not be opened'):
        importer.read_table('x.xlsx', b'not a workbook')


def test_guess_mapping_from_common_headers():
    m = importer.guess_mapping('drivers', ['Last Name', 'First Name', 'FGCU Email', 'Dept', 'DL #', 'Exp. Date'])
    assert m['last_name'] == 0 and m['first_name'] == 1 and m['email'] == 2 and m['department'] == 3
    assert m['license_expiration'] == 5
    m = importer.guess_mapping('fuel', ['Transaction Date', 'Asset Number', 'Gallons', 'Gross Amount', 'Merchant Name'])
    assert (m['fuel_date'], m['asset_number'], m['gallons'], m['total_cost'], m['vendor']) == (0, 1, 2, 3, 4)


def test_mask():
    assert importer.mask('D1234567') == '●●●●4567' and importer.mask('') == ''


# ----- who can get in -------------------------------------------------------------------------
@pytest.mark.parametrize('who,code', [('demo_tier1', 200), ('demo_tier1_backup', 200), ('demo_editor', 200), ('demo_tier2', 403)])
def test_who_can_open_import(client, sign_in, who, code):
    """Anyone who can enter some data by hand can import it; viewers without switches can't."""
    sign_in(client, who)
    assert client.get('/import').status_code == code


def test_editor_sees_only_what_they_may_enter(client, sign_in, dbq):
    sign_in(client, 'demo_editor')
    html = client.get('/import').get_data(as_text=True)
    assert 'value="maintenance"' in html and 'value="fuel"' not in html and 'value="drivers"' not in html
    r = client.post('/import', data={'target': 'drivers', 'file': (io.BytesIO(b'a,b'), 'x.csv')},
                    content_type='multipart/form-data')
    assert r.status_code == 403
    dbq("""INSERT INTO wsb.app_user_permission (user_id, permission)
           SELECT user_id, 'trips_fuel' FROM wsb.app_user WHERE username = 'demo_editor'""")
    assert 'value="fuel"' in client.get('/import').get_data(as_text=True)


# ----- the whole flow ---------------------------------------------------------------------------
def test_fuel_import_flow_saves_after_review(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    data = _csv([['Date', 'Asset', 'Gallons', 'Amount', 'Merchant'],
                 ['11/01/2026', 'DEMO-T01', '20.5', '$80.10', 'Gas Stop'],
                 ['2026-11-02', 'DEMO-C01', '10', '41.00', 'Gas Stop']])
    before = dbq('SELECT count(*) n FROM wsb.fuel_record')[0]['n']
    r = _review(client, 'fuel', 'wex.csv', data)
    html = r.get_data(as_text=True)
    assert 'data-bad="0"' in html and 'Save 2 rows' in html
    assert dbq('SELECT count(*) n FROM wsb.fuel_record')[0]['n'] == before        # review saves nothing
    form = _review_form(html)
    form['action'] = 'save'
    r = client.post('/import/review', data=form)
    assert r.status_code == 302
    assert dbq('SELECT count(*) n FROM wsb.fuel_record')[0]['n'] == before + 2
    assert dbq("SELECT total_cost FROM wsb.fuel_record WHERE vendor = 'Gas Stop' ORDER BY fuel_date LIMIT 1")[0]['total_cost'] == __import__('decimal').Decimal('80.10')
    log = dbq("SELECT summary FROM wsb.activity_log WHERE kind = 'change' ORDER BY activity_id DESC LIMIT 1")[0]
    assert log['summary'] == 'Imported 2 fuel purchases from wex.csv'


def test_problems_block_saving_until_fixed_or_unticked(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    data = _csv([['Date', 'Asset', 'Gallons', 'Amount'],
                 ['11/01/2026', 'NOPE-99', '20', '80'],          # unknown vehicle
                 ['not a date', 'DEMO-T01', 'abc', '80'],        # bad date and gallons
                 ['11/03/2026', 'DEMO-T01', '12', '50']])
    html = _review(client, 'fuel', 'f.csv', data).get_data(as_text=True)
    assert 'data-bad="2"' in html and 'No vehicle has property tag NOPE-99' in html and 'Gallons must be a number' in html
    before = dbq('SELECT count(*) n FROM wsb.fuel_record')[0]['n']
    form = _review_form(html)
    form['action'] = 'save'
    r = client.post('/import/review', data=form)
    assert r.status_code == 200 and 'have problems' in r.get_data(as_text=True)
    assert dbq('SELECT count(*) n FROM wsb.fuel_record')[0]['n'] == before
    # Fix row 2 in the table, untick row 1, then save.
    form.pop('keep0')
    form['c1_fuel_date'], form['c1_gallons'] = '2026-11-02', '9.5'
    r = client.post('/import/review', data=form)
    assert r.status_code == 302
    assert dbq('SELECT count(*) n FROM wsb.fuel_record')[0]['n'] == before + 2


def test_duplicates_are_flagged(client, sign_in, dbq):
    f = dbq("""SELECT v.asset_number, f.fuel_date, f.total_cost FROM wsb.fuel_record f JOIN wsb.vehicle v USING (vehicle_id)
               WHERE v.asset_number IS NOT NULL LIMIT 1""")[0]
    sign_in(client, 'demo_tier1')
    data = _csv([['Date', 'Asset', 'Gallons', 'Amount'], [f['fuel_date'].isoformat(), f['asset_number'], '5', str(f['total_cost'])],
                 [f['fuel_date'].isoformat(), f['asset_number'], '5', str(f['total_cost'])]])
    html = _review(client, 'fuel', 'f.csv', data).get_data(as_text=True)
    assert 'Looks like a duplicate' in html and 'Same as an earlier row' in html


def test_vehicle_import_rejects_existing_tag(client, sign_in):
    sign_in(client, 'demo_tier1')
    data = _xlsx([['Property Tag', 'Type', 'Year', 'Make', 'Model'], ['DEMO-T01', 'Truck', 2020, 'Ford', 'F-150'],
                  ['NEW-01', 'trailer', 2024, 'Load Rite', 'Single']])
    html = _review(client, 'vehicles', 'v.xlsx', data).get_data(as_text=True)
    assert 'DEMO-T01 already exists' in html and 'value="Trailer"' in html      # 'trailer' matched to the list value


def test_all_or_nothing_when_the_database_refuses_a_row(client, sign_in, dbq, app_module, monkeypatch):
    """A row that passes the checks but fails in the database rolls back every row."""
    sign_in(client, 'demo_tier1')
    data = _csv([['Property Tag', 'Type', 'Make'], ['NEW-A', 'Truck', 'Ford'], ['NEW-B', 'Truck', 'Ford']])
    html = _review(client, 'vehicles', 'v.csv', data).get_data(as_text=True)
    form = _review_form(html)
    form['action'] = 'save'
    form['c1_make'] = 'X' * 200                          # too long for the column: the database refuses row 2
    r = client.post('/import/review', data=form)
    assert r.status_code == 200 and 'Nothing was saved' in r.get_data(as_text=True)
    assert dbq("SELECT count(*) n FROM wsb.vehicle WHERE asset_number IN ('NEW-A', 'NEW-B')")[0]['n'] == 0


def test_driver_license_numbers_are_masked_and_saved_for_top_admin(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    data = _csv([['First Name', 'Last Name', 'Email', 'Approved', 'License Number', 'State', 'Expiration'],
                 ['Pat', 'Import', 'pat.import@example.edu', 'yes', 'P123456789', 'FL', '01/31/2030']])
    html = _review(client, 'drivers', 'd.csv', data).get_data(as_text=True)
    assert '●●●●●●6789' in html and '>P123456789<' not in html
    form = _review_form(html)
    form['action'] = 'save'
    assert client.post('/import/review', data=form).status_code == 302
    d = dbq("""SELECT d.approved, l.license_number, l.expiration_date FROM wsb.driver d
               JOIN wsb.driver_license l USING (driver_id) WHERE d.email = 'pat.import@example.edu'""")[0]
    assert d['approved'] is True and d['license_number'] == 'P123456789' and str(d['expiration_date']) == '2030-01-31'
    log = dbq("SELECT * FROM wsb.activity_log ORDER BY activity_id DESC LIMIT 1")[0]
    assert 'P123456789' not in str(log)


def test_existing_driver_email_is_an_error(client, sign_in):
    sign_in(client, 'demo_tier1')
    data = _csv([['First', 'Last', 'Email'], ['Alex', 'Rivera', 'arivera@example.edu']])
    assert 'already exists' in _review(client, 'drivers', 'd.csv', data).get_data(as_text=True)


def test_trip_needs_an_approved_driver(client, sign_in):
    sign_in(client, 'demo_tier1')
    data = _csv([['Asset', 'Driver Email', 'Start'], ['DEMO-T01', 'nobody@example.edu', '11/01/2026 08:00']])
    assert 'not an approved, active driver' in _review(client, 'trips', 't.csv', data).get_data(as_text=True)


def test_upload_errors_are_messages(client, sign_in):
    sign_in(client, 'demo_tier1')
    r = _upload(client, 'fuel', 'scan.pdf', b'%PDF-1.4')
    assert r.status_code == 200 and 'Upload an Excel' in r.get_data(as_text=True)
    r = client.post('/import', data={'target': 'nope', 'file': (io.BytesIO(b'a,b'), 'x.csv')},
                    content_type='multipart/form-data')
    assert 'Choose what the file holds' in r.get_data(as_text=True)


def test_tampered_review_input_is_a_400_not_a_crash(client, sign_in):
    sign_in(client, 'demo_tier1')
    assert client.post('/import/review', data={'target': 'fuel', 'table': '{not json'}).status_code == 400
    assert client.post('/import/review', data={'target': 'bogus'}).status_code == 400

"""Bugs found 2026-11-06: open redirects, deletes of missing records, bad input on Mark done."""


def test_mark_done_back_cannot_leave_the_site(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    rid = dbq('SELECT rule_id FROM wsb.maintenance_rule ORDER BY rule_id LIMIT 1')[0]['rule_id']
    r = client.post(f'/maintenance/{rid}/done', data={'date': '2026-11-06', 'back': 'https://evil.example.com/'})
    assert r.status_code == 302 and 'evil.example.com' not in r.headers['Location']


def test_doc_delete_back_cannot_leave_the_site(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    did = dbq('SELECT document_id FROM wsb.vehicle_document ORDER BY document_id LIMIT 1')[0]['document_id']
    r = client.post(f'/documents/{did}/delete', data={'back': '//evil.example.com'})
    assert 'evil.example.com' not in r.headers['Location']


def test_mark_done_bad_date_is_a_message_not_a_crash(client, sign_in, dbq):
    sign_in(client, 'demo_tier1')
    rid = dbq('SELECT rule_id FROM wsb.maintenance_rule ORDER BY rule_id LIMIT 1')[0]['rule_id']
    r = client.post(f'/maintenance/{rid}/done', data={'date': 'not-a-date', 'mileage': 'abc'}, follow_redirects=True)
    assert r.status_code == 200 and 'real date' in r.get_data(as_text=True)


def test_deleting_missing_records_is_404(client, sign_in):
    sign_in(client, 'demo_tier1')
    assert client.post('/rules/999999/delete').status_code == 404
    assert client.post('/documents/999999/delete').status_code == 404
    assert client.post('/vehicles/999999/delete').status_code == 404


def test_upload_to_missing_vehicle_is_404(client, sign_in):
    import io
    sign_in(client, 'demo_tier1')
    r = client.post('/vehicles/999999/documents', data={'file': (io.BytesIO(b'x'), 'a.pdf')})
    assert r.status_code == 404


def test_rule_without_type_is_400(client, sign_in):
    sign_in(client, 'demo_tier1')
    assert client.post('/vehicles/1/rules', data={}).status_code == 400


def test_mileage_rule_gets_a_status(app_module):
    import datetime
    r = {'due_date': None, 'mileage_interval': 7500, 'last_completed_mileage': 40000, 'current_mileage': 47400}
    assert app_module.maint_status(r) == 'Due soon' and r['due_mileage'] == 47500
    r = {'due_date': None, 'mileage_interval': 7500, 'last_completed_mileage': 40000, 'current_mileage': 48000}
    assert app_module.maint_status(r) == 'Overdue'
    r = {'due_date': datetime.date.today() + datetime.timedelta(days=200), 'mileage_interval': 7500,
         'last_completed_mileage': 40000, 'current_mileage': 48000}
    assert app_module.maint_status(r) == 'Overdue'     # the worse of the two checks wins
    assert app_module.maint_status({'due_date': None, 'mileage_interval': 7500, 'last_completed_mileage': None,
                                    'current_mileage': 1}) == 'Unknown'


def test_no_none_in_maintenance_intervals(client, sign_in):
    sign_in(client, 'demo_tier2')
    html = client.get('/maintenance?show=all').get_data(as_text=True)
    assert 'None mo' not in html and 'None' not in html.split('<main')[1]

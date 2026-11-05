"""Fixes from the final review."""
import pytest

from search import parse_date_term


@pytest.mark.parametrize('bad', ['/\\evil.com', '//evil.com', 'https://evil.com', '/\t/evil.com', 'evil.com'])
def test_login_next_cannot_leave_the_site(client, bad):
    r = client.post('/login/demo', data={'email': 'campus.staff@example.edu', 'next': bad})
    assert r.status_code == 302 and r.headers['Location'] == '/'


def test_login_next_keeps_local_paths(client):
    r = client.post('/login/demo', data={'email': 'campus.staff@example.edu', 'next': '/search?q=F-250'})
    assert r.headers['Location'] == '/search?q=F-250'


def test_tier2_not_told_hidden_documents_exist(client, sign_in, dbq):
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-T01'")[0]['vehicle_id']
    sign_in(client, 'demo_tier2')
    page = client.get(f'/vehicles/{vid}').get_data(as_text=True)
    assert 'restricted' not in page and 'more document' not in page


def test_delete_vehicle_with_history_keeps_files_and_explains(client, sign_in, dbq, app_module):
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-T01'")[0]['vehicle_id']
    (app_module.UPLOADS / str(vid)).mkdir()
    kept = app_module.UPLOADS / str(vid) / 'abcd1234_reg.pdf'
    kept.write_bytes(b'%PDF')
    dbq("""INSERT INTO wsb.vehicle_document (vehicle_id, document_type, file_location)
           VALUES (%s, 'Registration', %s)""", (vid, f'{vid}/abcd1234_reg.pdf'))
    sign_in(client, 'demo_tier1')
    r = client.post(f'/vehicles/{vid}/delete', follow_redirects=True)
    assert r.status_code == 200
    assert 'Set its status to Retired instead' in r.get_data(as_text=True)
    assert kept.exists()
    assert dbq('SELECT count(*) n FROM wsb.vehicle WHERE vehicle_id = %s', (vid,))[0]['n'] == 1


def test_delete_vehicle_without_history_works(client, sign_in, dbq):
    vid = dbq("INSERT INTO wsb.vehicle (vehicle_type, make) VALUES ('Car', 'Temp') RETURNING vehicle_id")[0]['vehicle_id']
    sign_in(client, 'demo_tier1')
    r = client.post(f'/vehicles/{vid}/delete')
    assert r.status_code == 302
    assert dbq('SELECT count(*) n FROM wsb.vehicle WHERE vehicle_id = %s', (vid,))[0]['n'] == 0


def test_tier1_can_find_and_edit_any_driver(client, sign_in, dbq):
    did = dbq("SELECT driver_id FROM wsb.driver WHERE email = 'cbrooks@example.edu'")[0]['driver_id']
    sign_in(client, 'demo_tier1_backup')
    page = client.get('/search?q=Brooks&kind=drivers').get_data(as_text=True)
    assert 'Drivers · 1' in page and f'/drivers/{did}/edit' in page


def test_tier2_cannot_search_drivers(client, sign_in):
    sign_in(client, 'demo_tier2')
    page = client.get('/search?q=Brooks&kind=drivers').get_data(as_text=True)
    assert 'Drivers ·' not in page and 'kind=drivers' not in page


def test_driver_saved_without_license_access_goes_to_driver_search(client, sign_in):
    sign_in(client, 'demo_tier1_backup')
    r = client.post('/drivers/new', data={'first_name': 'Nia', 'last_name': 'Vale', 'email': 'nvale@example.edu'})
    assert r.status_code == 302 and 'kind=drivers' in r.headers['Location'] and 'Vale' in r.headers['Location']


def test_far_future_dates_do_not_crash(client, sign_in):
    assert parse_date_term('9999-12-31') is None or parse_date_term('9999-12-31')
    sign_in(client, 'demo_tier2')
    assert client.get('/search?q=9999-12-31').status_code == 200
    assert client.get('/search?q=12/31/9999').status_code == 200
    assert client.get('/search?q=December 9999').status_code == 200
    assert client.get('/search?q=x&kind=trips&date_to=9999-12-31').status_code == 200


def test_demo_signin_only_for_demo_users(client, dbq):
    dbq("""INSERT INTO wsb.app_user (username, full_name, email, role_id, can_see_licenses)
           SELECT 'real_manager', 'Real Manager', 'real.manager@fgcu.edu', role_id, TRUE
           FROM wsb.app_role WHERE role_name = 'Admin'""")
    assert 'real.manager@fgcu.edu' not in client.get('/login/demo').get_data(as_text=True)
    assert client.post('/login/demo', data={'email': 'real.manager@fgcu.edu'}).status_code == 403


def test_help_says_tier1_sees_driver_emails(client, sign_in):
    sign_in(client, 'demo_tier2')
    page = client.get('/help').get_data(as_text=True)
    assert '<td>Driver emails</td><td>Yes</td>' in page

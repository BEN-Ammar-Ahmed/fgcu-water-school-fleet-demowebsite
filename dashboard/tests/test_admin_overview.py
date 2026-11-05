"""Admin area: who can get in, and the Overview page."""
import pytest


@pytest.mark.parametrize('who,code', [('demo_tier2', 403), ('demo_editor', 403), ('demo_tier1_backup', 200), ('demo_tier1', 200)])
def test_only_admins_get_in(client, sign_in, who, code):
    sign_in(client, who)
    assert client.get('/admin').status_code == code


def test_signed_out_goes_to_login(client):
    r = client.get('/admin')
    assert r.status_code == 302 and '/login' in r.headers['Location']


def test_admin_link_only_for_admins(client, sign_in):
    sign_in(client, 'demo_editor')
    assert 'href="/admin"' not in client.get('/help').get_data(as_text=True)
    sign_in(client, 'demo_tier1_backup')
    assert 'href="/admin"' in client.get('/help').get_data(as_text=True)


def test_overview_cards_and_numbers(client, sign_in, dbq):
    people = dbq('SELECT count(*) n FROM wsb.app_user WHERE active')[0]['n']
    sign_in(client, 'demo_tier1')
    page = client.get('/admin').get_data(as_text=True)
    for label in ('People with access', 'Signed in now', 'Vehicles', 'Maintenance overdue', 'Trips this month',
                  'Fuel this month', 'Spent this fiscal year', 'Documents expiring'):
        assert label in page, label
    assert f'data-stat="people">{people}<' in page
    assert 'data-stat="vehicles">8<' in page
    assert 'data-stat="overdue">1<' in page


def test_signed_in_now_list(client, sign_in, dbq):
    dbq("UPDATE wsb.app_user SET last_seen = now() - interval '5 minutes', last_page = 'Search: Sea Ark' WHERE username = 'demo_editor'")
    dbq("UPDATE wsb.app_user SET last_seen = now() - interval '20 minutes', last_page = 'Help' WHERE username = 'demo_tier2'")
    sign_in(client, 'demo_tier1')
    page = client.get('/admin').get_data(as_text=True)
    online = page[page.index('id="online"'):]
    online = online[:online.index('</section>')]
    assert 'Demo Boat Captain' in online and 'Search: Sea Ark' in online
    assert 'Demo Campus Staff' not in online


def test_recent_activity_on_overview(client, sign_in, dbq):
    client.post('/login/demo', data={'email': 'campus.staff@example.edu'})
    sign_in(client, 'demo_tier1')
    page = client.get('/admin').get_data(as_text=True)
    assert 'Demo Campus Staff' in page and 'Signed in' in page

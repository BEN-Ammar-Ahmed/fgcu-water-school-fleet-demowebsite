"""Form protection: a form that saves something must carry this session's secret."""
import re

import pytest


@pytest.fixture()
def csrf_on(app_module):
    app_module.app.config['CSRF_ENABLED'] = True
    yield
    app_module.app.config['CSRF_ENABLED'] = False


def _token(html):
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def test_every_saving_form_has_the_token(client, sign_in, csrf_on):
    sign_in(client, 'demo_tier1')
    for path in ('/vehicles/1', '/vehicles/1/edit', '/fuel/new', '/maintenance', '/admin/people', '/'):
        html = client.get(path).get_data(as_text=True)
        assert html.count('method="post"') == html.count('name="csrf_token"'), path


def test_post_without_token_is_refused(client, sign_in, dbq, csrf_on):
    sign_in(client, 'demo_tier1')
    client.get('/')
    rid = dbq('SELECT rule_id FROM wsb.maintenance_rule ORDER BY rule_id LIMIT 1')[0]['rule_id']
    before = dbq('SELECT last_completed_date FROM wsb.maintenance_rule WHERE rule_id = %s', (rid,))[0]
    r = client.post(f'/maintenance/{rid}/done', data={'date': '2026-11-06'})
    assert r.status_code == 400 and 'refresh the page' in r.get_data(as_text=True)
    assert dbq('SELECT last_completed_date FROM wsb.maintenance_rule WHERE rule_id = %s', (rid,))[0] == before


def test_post_with_token_works(client, sign_in, dbq, csrf_on):
    sign_in(client, 'demo_tier1')
    token = _token(client.get('/maintenance').get_data(as_text=True))
    rid = dbq('SELECT rule_id FROM wsb.maintenance_rule ORDER BY rule_id LIMIT 1')[0]['rule_id']
    r = client.post(f'/maintenance/{rid}/done', data={'date': '2026-11-06', 'csrf_token': token})
    assert r.status_code == 302


def test_sign_in_page_works_with_token(client, csrf_on):
    token = _token(client.get('/login').get_data(as_text=True))
    r = client.post('/login', data={'password': 'test-password-1', 'username': 'campus.staff@example.edu', 'csrf_token': token})
    assert r.status_code == 302

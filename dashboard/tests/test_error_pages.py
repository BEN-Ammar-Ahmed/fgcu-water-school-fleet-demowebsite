"""Friendly error pages: 403, 404, 405, 413, 500 and a database outage."""
import psycopg2


def test_404_page(client, sign_in):
    sign_in(client, 'demo_tier2')
    r = client.get('/vehicles/999999')
    assert r.status_code == 404 and 'Not found' in r.get_data(as_text=True)
    r = client.get('/no-such-page')
    assert r.status_code == 404 and 'Error 404' in r.get_data(as_text=True)


def test_403_page(client, sign_in):
    sign_in(client, 'demo_tier2')
    r = client.get('/admin')
    assert r.status_code == 403 and 'Not allowed' in r.get_data(as_text=True)


def test_405_page(client, sign_in):
    sign_in(client, 'demo_tier1')
    r = client.get('/maintenance/1/done')
    assert r.status_code == 405 and 'not allowed here' in r.get_data(as_text=True)


def test_413_page(client, sign_in, app_module):
    sign_in(client, 'demo_tier1')
    app_module.app.config['MAX_CONTENT_LENGTH'] = 10
    try:
        r = client.post('/vehicles/1/documents', data={'file': (__import__('io').BytesIO(b'x' * 100), 'a.pdf')})
    finally:
        app_module.app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024
    assert r.status_code == 413 and '20 MB' in r.get_data(as_text=True)


def test_500_page_hides_details(client, sign_in, app_module, monkeypatch):
    sign_in(client, 'demo_tier1')
    monkeypatch.setitem(app_module.app.config, 'PROPAGATE_EXCEPTIONS', False)
    monkeypatch.setattr(app_module, 'maintenance', lambda: 1 / 0)
    r = client.get('/maintenance')
    html = r.get_data(as_text=True)
    assert r.status_code == 500 and 'Something went wrong' in html and 'ZeroDivisionError' not in html


def test_database_down_page(client, sign_in, app_module, monkeypatch):
    sign_in(client, 'demo_tier1')
    monkeypatch.setattr(app_module, 'DB_URL', 'postgresql://nobody:x@localhost:1/none')
    r = client.get('/help')
    assert r.status_code == 503 and 'Cannot reach the database' in r.get_data(as_text=True)


def test_suggest_errors_are_json(client, sign_in, app_module, monkeypatch):
    sign_in(client, 'demo_tier1')
    client.get('/help')
    monkeypatch.setattr(app_module, 'DB_URL', 'postgresql://nobody:x@localhost:1/none')
    r = client.get('/suggest?field=search&q=ford')
    assert r.status_code == 503 and r.get_json()['groups'] == []

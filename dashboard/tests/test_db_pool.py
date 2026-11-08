"""Connections are kept open and reused between pages (common.Database): opening one to Supabase takes ~1 s."""
import psycopg2

from conftest import TEST_URL


def _backend_pid(client):
    """Which database connection served this page (via a tiny query inside a request)."""
    import app as site
    with client.application.test_request_context():
        pid = site.q('SELECT pg_backend_pid() p', one=True)['p']
        site.DATABASE.release()
    return pid


def test_connection_is_reused_between_pages(app_module, client, sign_in):
    app_module.app.config['DB_POOL'] = True
    try:
        first = _backend_pid(client)
        sign_in(client, 'demo_tier1')
        assert client.get('/help').status_code == 200
        assert _backend_pid(client) == first
    finally:
        app_module.DATABASE.close_all()
        app_module.app.config['DB_POOL'] = False


def test_dropped_connection_is_replaced_without_an_error(app_module, client, sign_in):
    app_module.app.config['DB_POOL'] = True
    try:
        pid = _backend_pid(client)
        with psycopg2.connect(TEST_URL) as c, c.cursor() as cur:       # the database drops it (like an idle timeout)
            cur.execute('SELECT pg_terminate_backend(%s)', (pid,))
        sign_in(client, 'demo_tier1')
        assert client.get('/help').status_code == 200
        assert _backend_pid(client) != pid
    finally:
        app_module.DATABASE.close_all()
        app_module.app.config['DB_POOL'] = False

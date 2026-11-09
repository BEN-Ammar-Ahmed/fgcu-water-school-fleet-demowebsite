"""Test setup: a throwaway PostgreSQL 17 in Docker, never Supabase.

Start it once with:
    docker run -d --name wsb-test-db -e POSTGRES_PASSWORD=test -p 54329:5432 postgres:17

A template database is built from sql_postgres/ (plus the fictional demo data)
once per test run; every test gets a fresh copy of it.
"""
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
import pytest

SERVER = os.environ.get('WSB_TEST_SERVER', 'postgresql://postgres:test@localhost:54329')
TEST_DB = 'wsb_test'
TEMPLATE_DB = 'wsb_template'
TEST_URL = f'{SERVER}/{TEST_DB}'

# Must happen before app is imported, so the Supabase .env is never used.
os.environ['DATABASE_URL'] = TEST_URL

HERE = Path(__file__).resolve().parent
DASHBOARD = HERE.parent
SQL_DIR = DASHBOARD.parent / 'sql_postgres'
sys.path.insert(0, str(DASHBOARD))

# Every test account gets this password (test database only; never in sql_postgres/).
TEST_PASSWORD = 'test-password-1'

SQL_FILES = [
    '01_schema.sql', '02_security.sql', '03_reference_data.sql', 'test_data/03b_demo_data.sql',
    '04_import_staging.sql', '05_procedures.sql', '07_web_access.sql', '08_admin_levels.sql', 'test_data/09_demo_users.sql',
    '10_suggestions.sql',
    '11_vehicle_name.sql',
    '12_tiers.sql',
    '13_reservations.sql',
    '14_passwords.sql',
    '15_public_reservations.sql',
    '16_document_files.sql',
]


def _admin():
    conn = psycopg2.connect(f'{SERVER}/postgres', connect_timeout=10)
    conn.autocommit = True
    return conn


def _drop(cur, name):
    cur.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()', (name,))
    cur.execute(f'DROP DATABASE IF EXISTS {name}')


@pytest.fixture(scope='session', autouse=True)
def template_db():
    conn = _admin()
    with conn.cursor() as cur:
        _drop(cur, TEST_DB)
        _drop(cur, TEMPLATE_DB)
        cur.execute(f'CREATE DATABASE {TEMPLATE_DB}')
    conn.close()
    t = psycopg2.connect(f'{SERVER}/{TEMPLATE_DB}')
    t.autocommit = True
    with t.cursor() as cur:
        for name in SQL_FILES:
            path = SQL_DIR / name
            if path.exists():
                cur.execute(path.read_text(encoding='utf-8'))
        from werkzeug.security import generate_password_hash
        cur.execute("""INSERT INTO wsb.app_user_password (user_id, password_hash, must_change)
                       SELECT user_id, %s, FALSE FROM wsb.app_user""", (generate_password_hash(TEST_PASSWORD),))
    t.close()
    yield


@pytest.fixture()
def app_module(monkeypatch, tmp_path):
    conn = _admin()
    with conn.cursor() as cur:
        _drop(cur, TEST_DB)
        cur.execute(f'CREATE DATABASE {TEST_DB} TEMPLATE {TEMPLATE_DB}')
    conn.close()
    import app as app_mod
    assert 'supabase' not in app_mod.DB_URL
    monkeypatch.setattr(app_mod, 'DB_URL', TEST_URL)
    monkeypatch.setattr(app_mod, 'UPLOADS', tmp_path)
    app_mod.app.config['TESTING'] = True
    app_mod.app.config['CSRF_ENABLED'] = False   # tests/test_csrf.py turns it back on
    app_mod.app.config['DB_POOL'] = False        # each test gets a new database; tests/test_db_pool.py checks the pool
    return app_mod


@pytest.fixture()
def client(app_module):
    return app_module.app.test_client()


@pytest.fixture()
def dbq(app_module):
    def run(sql, args=None):
        conn = psycopg2.connect(TEST_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall() if cur.description else []
        conn.close()
        return rows
    return run


@pytest.fixture()
def sign_in(dbq):
    def do(client, username):
        uid = dbq('SELECT user_id FROM wsb.app_user WHERE username = %s', (username,))[0]['user_id']
        with client.session_transaction() as s:
            s.clear()
            s['user_id'] = uid
    return do


@pytest.fixture()
def reserve(app_module, monkeypatch):
    """Test client for the separate vehicle request site (reserve_app.py), on the same test database."""
    import reserve_app
    monkeypatch.setattr(reserve_app, 'DB_URL', TEST_URL)
    reserve_app.app.config['TESTING'] = True
    reserve_app.app.config['CSRF_ENABLED'] = False
    reserve_app.app.config['DB_POOL'] = False
    reserve_app._recent.clear()
    return reserve_app.app.test_client()

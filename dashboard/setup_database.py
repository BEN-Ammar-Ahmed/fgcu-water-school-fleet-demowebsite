"""Set up a new, empty database for the websites, using only the SQL files in this repository.

    cd dashboard
    python setup_database.py              set up the database named in DATABASE_URL (dashboard/.env)
    python setup_database.py --create-db  local PostgreSQL only: create that database first if it doesn't exist
    python setup_database.py --sample     also load the fictional practice data (never on the real database)
    python setup_database.py --check      also run the security checks (06_security_tests.sql)

It runs the numbered files in ../sql_postgres/ in order (01, 02, 03, 04, 05, 07, 08, 10, ... 15), each one
all-or-nothing, and stops at the first problem. Safe to run again: the files keep the data that's already there.
Next step afterwards: python create_admin.py
"""
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg2

from common import database_url, load_env_file

HERE = Path(__file__).parent
SQL = HERE.parent / 'sql_postgres'
SKIP = {'00_create_database.sql': 'not needed: the database already exists',
        '03c_real_vehicles.sql': 'real fleet data, kept off GitHub',
        '06_security_tests.sql': 'checks only (add --check to run them)'}


def setup_files(sample=False, check=False):
    """[(file, reason to skip or None)] in run order."""
    out = []
    for p in sorted(SQL.glob('[0-9][0-9]*.sql')):
        reason = SKIP.get(p.name)
        if p.name == '06_security_tests.sql' and check:
            reason = None
        out.append((p, reason))
    if sample:   # fictional rows, loaded at the point in the order the tests use
        demo = {p.name: p for p in (SQL / 'test_data').glob('*.sql')}
        order = []
        for p, reason in out:
            order.append((p, reason))
            if p.name.startswith('03_') and '03b_demo_data.sql' in demo:
                order.append((demo['03b_demo_data.sql'], None))
            if p.name.startswith('08_') and '09_demo_users.sql' in demo:
                order.append((demo['09_demo_users.sql'], None))
        out = order
    return out


def create_database(url):
    """Local PostgreSQL: CREATE DATABASE <name> on the same server, if it isn't there yet."""
    parts = urlsplit(url)
    name = parts.path.lstrip('/')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name or ''):
        raise SystemExit(f'Can\'t tell the database name from DATABASE_URL ("{name}").')
    admin = urlunsplit(parts._replace(path='/postgres'))
    conn = psycopg2.connect(admin, connect_timeout=15)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (name,))
        if cur.fetchone():
            print(f'Database {name} already exists.')
        else:
            cur.execute(f'CREATE DATABASE {name}')
            print(f'Created database {name}.')
    conn.close()


def run(url, files, out=print):
    conn = psycopg2.connect(url, connect_timeout=15)
    try:
        for path, reason in files:
            label = path.relative_to(SQL).as_posix()
            if reason:
                out(f'  skip  {label}  ({reason})')
                continue
            try:
                with conn.cursor() as cur:
                    cur.execute(path.read_text(encoding='utf-8'))
                conn.commit()
                out(f'  done  {label}')
            except psycopg2.Error as e:
                conn.rollback()
                out(f'  FAILED  {label}: {str(e).strip().splitlines()[0]}')
                out('Nothing from that file was saved. Fix the problem and run this again.')
                return False
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM wsb.app_user')
            accounts = cur.fetchone()[0]
            cur.execute('SELECT count(*) FROM wsb.vehicle')
            vehicles = cur.fetchone()[0]
        out(f'\nReady. {vehicles} vehicles, {accounts} sign-in accounts.')
        if not accounts:
            out('Next: python create_admin.py   (makes the first Tier 1 account)')
        return True
    finally:
        conn.close()


def main(argv):
    if '-h' in argv or '--help' in argv:
        print(__doc__)
        return 0
    load_env_file(HERE / '.env')
    url = database_url()
    where = 'Supabase' if 'supabase' in url else 'PostgreSQL'
    print(f'Setting up the database on {where}, from {SQL}')
    if '--sample' in argv:
        print('Including the FICTIONAL practice data (--sample). Never use this on the real database.')
    if '--create-db' in argv:
        create_database(url)
    try:
        ok = run(url, setup_files(sample='--sample' in argv, check='--check' in argv))
    except psycopg2.OperationalError as e:
        msg = str(e).strip().splitlines()[0]
        print(f"Can't connect: {msg}")
        if 'does not exist' in msg:
            print('On your own PostgreSQL, add --create-db to create it first.')
        else:
            print('Check DATABASE_URL in dashboard/.env (see .env.example).')
        return 1
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

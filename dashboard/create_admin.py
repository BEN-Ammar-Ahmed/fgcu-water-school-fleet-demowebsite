"""Create a Tier 1 (top admin) account from a terminal: the first account on a new database, or a spare one.

    cd dashboard
    python create_admin.py

It asks for the person's name, email, username and password (typed hidden; saved only as a hash).
Everyone else is then added on the website: Admin -> People.
To reset the password of an account that already exists, use set_password.py instead.
"""
import getpass
import re
import sys

import psycopg2
import psycopg2.extras

import passwords
from common import database_url, load_env_file

EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def create(conn, full_name, email, username, password):
    """Make the account. Returns (user_id, None) or (None, problem)."""
    full_name, email, username = full_name.strip(), email.strip(), username.strip().lower()
    if not full_name:
        return None, 'Enter a name.'
    if not EMAIL.match(email):
        return None, 'Enter a valid email address.'
    if not re.fullmatch(r'[a-z0-9_.-]{3,40}', username):
        return None, 'The username needs 3-40 letters, numbers, dots, dashes or underscores.'
    problems = passwords.problems(password, None, username)
    if problems:
        return None, problems[0]
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute('SELECT username FROM wsb.app_user WHERE lower(username) = %s OR lower(email) = lower(%s)',
                    (username, email))
        if cur.fetchone():
            return None, 'That username or email already has an account. Use set_password.py to reset its password.'
        cur.execute("SELECT role_id FROM wsb.app_role WHERE role_name = 'Top admin'")
        role = cur.fetchone()
        if not role:
            return None, 'The database is not set up yet. Run python setup_database.py first.'
        cur.execute("""INSERT INTO wsb.app_user (username, full_name, email, role_id, can_see_licenses, active)
                       VALUES (%s, %s, %s, %s, TRUE, TRUE) RETURNING user_id""",
                    (username, full_name[:100], email[:100], role['role_id']))
        uid = cur.fetchone()['user_id']
    conn.commit()

    def run(sql, args=()):
        with conn.cursor() as c:
            c.execute(sql, args)
        conn.commit()
    passwords.set_password(run, uid, password, must_change=False)
    return uid, None


def main():
    if '-h' in sys.argv or '--help' in sys.argv:
        print(__doc__)
        return 0
    from pathlib import Path
    load_env_file(Path(__file__).parent / '.env')
    url = database_url()
    try:
        conn = psycopg2.connect(url, connect_timeout=15)
    except psycopg2.OperationalError as e:
        print(f"Can't connect: {str(e).strip().splitlines()[0]}. Check DATABASE_URL in dashboard/.env.")
        return 1
    print(f"New Tier 1 (top admin) account on {'Supabase' if 'supabase' in url else 'PostgreSQL'}.")
    name = input('Full name: ')
    email = input('Email: ')
    suggested = re.sub(r'[^a-z0-9_.-]', '', email.split('@')[0].lower())
    username = input(f'Username [{suggested}]: ') or suggested
    # Typed hidden at a keyboard; read as plain lines when answers are piped in (e.g. from a setup script).
    def ask(prompt):
        if sys.stdin.isatty():
            return getpass.getpass(prompt)
        print(prompt)
        return sys.stdin.readline().rstrip('\r\n')
    pw = ask(f'Password (at least {passwords.MIN_LENGTH} characters): ')
    if pw != ask('Type it again: '):
        print("The two passwords don't match. Nothing was saved.")
        return 1
    uid, problem = create(conn, name, email, username, pw)
    conn.close()
    if problem:
        print(problem + ' Nothing was saved.')
        return 1
    print(f'Done. Sign in at /login as "{username.strip().lower()}" (or {email.strip()}).')
    return 0


if __name__ == '__main__':
    sys.exit(main())

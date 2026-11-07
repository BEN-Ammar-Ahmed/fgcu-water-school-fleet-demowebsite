"""Set a fleet-site password from a terminal (for the very first top admin, or if everyone is locked out).

    cd dashboard
    python set_password.py <username or email>

Uses the same database as the site (DATABASE_URL in dashboard/.env). The password is typed in hidden and
saved only as a hash. It is not temporary: the person keeps it until they change it.
"""
import getpass
import sys

import psycopg2
import psycopg2.extras

import app as site
import passwords


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    conn = psycopg2.connect(site.DB_URL, cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=15)

    def q(sql, args=(), one=False):
        with conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall() if cur.description else []
        return (rows[0] if rows else None) if one else rows

    def run(sql, args=()):
        with conn.cursor() as cur:
            cur.execute(sql, args)
        conn.commit()

    u = passwords.find_user(q, sys.argv[1])
    if not u:
        print(f'No active account with username or email "{sys.argv[1]}" ({site.DB_WHERE}).')
        return 1
    print(f"Setting the password for {u['full_name']} (username: {u['username']}) on {site.DB_WHERE}.")
    new = getpass.getpass('New password: ')
    problems = passwords.problems(new, getpass.getpass('Type it again: '), u['username'])
    if problems:
        print('\n'.join(problems))
        return 1
    passwords.set_password(run, u['user_id'], new, must_change=False)
    print('Saved. Sign in at /login with that username (or email) and password.')
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())

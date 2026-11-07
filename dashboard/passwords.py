"""Username + password sign-in (wsb.app_user_password, 14_passwords.sql).

Passwords are stored only as salted hashes (werkzeug: scrypt). After MAX_TRIES wrong passwords in a row the
account is locked for LOCK_MINUTES. The same message is shown for an unknown username and a wrong password,
so the sign-in page doesn't reveal who has an account.
"""
import datetime as dt

from werkzeug.security import check_password_hash, generate_password_hash

MIN_LENGTH = 8
MAX_TRIES = 5
LOCK_MINUTES = 15
WRONG = 'Wrong username or password.'
_DUMMY = generate_password_hash('not-a-real-password')   # keeps "unknown user" as slow as "wrong password"


def find_user(q, login):
    """Active user by username or email (any case)."""
    login = (login or '').strip()
    if not login:
        return None
    return q("""SELECT u.user_id, u.username, u.full_name, p.password_hash, p.must_change, p.failed_logins,
                       p.locked_until
                FROM wsb.app_user u LEFT JOIN wsb.app_user_password p USING (user_id)
                WHERE u.active AND (lower(u.username) = lower(%s) OR lower(u.email) = lower(%s))
                ORDER BY u.user_id LIMIT 1""", (login, login), one=True)


def check(q, run, login, password):
    """Returns (user row, None) on success, or (None, message for the sign-in page)."""
    u = find_user(q, login)
    if not u or not u['password_hash']:
        check_password_hash(_DUMMY, password or '')
        return None, WRONG
    now = dt.datetime.now(dt.timezone.utc)
    if u['locked_until'] and u['locked_until'] > now:
        mins = max(1, round((u['locked_until'] - now).total_seconds() / 60))
        return None, f'Too many wrong passwords. Try again in {mins} minute{"s" if mins != 1 else ""}.'
    if not check_password_hash(u['password_hash'], password or ''):
        tries = u['failed_logins'] + 1
        if tries >= MAX_TRIES:
            run("""UPDATE wsb.app_user_password SET failed_logins = 0,
                          locked_until = now() + make_interval(mins => %s) WHERE user_id = %s""",
                (LOCK_MINUTES, u['user_id']))
            return None, f'Too many wrong passwords. Try again in {LOCK_MINUTES} minutes.'
        run('UPDATE wsb.app_user_password SET failed_logins = %s WHERE user_id = %s', (tries, u['user_id']))
        return None, WRONG
    run('UPDATE wsb.app_user_password SET failed_logins = 0, locked_until = NULL WHERE user_id = %s', (u['user_id'],))
    return u, None


def problems(new, confirm, username=''):
    """Plain-English reasons a new password can't be used (empty list = fine)."""
    out = []
    if len(new or '') < MIN_LENGTH:
        out.append(f'The new password needs at least {MIN_LENGTH} characters.')
    elif username and new.lower() == username.lower():
        out.append("The password can't be your username.")
    if confirm is not None and new != confirm:
        out.append("The two new passwords don't match.")
    return out


def set_password(run, user_id, password, must_change):
    """Save a new password (hashed). must_change=True for a temporary one set by someone else."""
    run("""INSERT INTO wsb.app_user_password (user_id, password_hash, must_change)
           VALUES (%s, %s, %s)
           ON CONFLICT (user_id) DO UPDATE SET password_hash = EXCLUDED.password_hash,
               must_change = EXCLUDED.must_change, failed_logins = 0, locked_until = NULL, changed_at = now()""",
        (user_id, generate_password_hash(password), must_change))

"""Small things both websites use: the fleet site (app.py) and the vehicle request site (reserve_app.py)."""
import os

VEHICLE_TYPES = ['Boat', 'Car', 'Truck', 'Trailer', 'Golf Cart', 'ATV', 'Other']


def load_env_file(path):
    """Read KEY=value lines from dashboard/.env (kept out of git) into the environment."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def database_url():
    """DATABASE_URL (Supabase: the "Session pooler" string), else the local PostgreSQL."""
    url = os.environ.get('DATABASE_URL', 'dbname=water_school_fleet user=postgres host=localhost')
    if 'supabase' in url and 'sslmode' not in url:
        url += ('&' if '?' in url else '?') + 'sslmode=require'
    return url


def fleet_url():
    """Address of the fleet site, used in emails to approvers. Set FLEET_URL once it has a real address."""
    return os.environ.get('FLEET_URL', 'http://localhost:5000').rstrip('/')


def reserve_url():
    """Address of the vehicle request site, used in links and emails. Set RESERVE_URL once it has a real address."""
    return os.environ.get('RESERVE_URL', 'http://localhost:5001').rstrip('/')


def static_url_for(app):
    """url_for('static') plus ?v=<file's modified time>: browsers may keep the file for a year, and a new
    version gets a new address, so changes still show up right away."""
    import os as _os
    from flask import url_for

    def asset(filename):
        try:
            v = int(_os.path.getmtime(_os.path.join(app.static_folder, filename)))
        except OSError:
            v = 0
        return url_for('static', filename=filename, v=v)
    def inline_asset(filename):
        """A small script's text, to put inside the page: it then runs before the page is first shown
        (no jump when it adds things), with no extra download."""
        from markupsafe import Markup
        with open(_os.path.join(app.static_folder, filename), encoding='utf-8') as f:
            return Markup(f.read().replace('</script', r'<\/script'))
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 365 * 24 * 3600
    app.jinja_env.globals['asset'] = asset
    app.jinja_env.globals['inline_asset'] = inline_asset


def display_name(v):
    """The vehicle's Name (edited on its Edit page), else year make model, e.g. '2013 Ford F150 4x4'."""
    if (v.get('name') or '').strip():
        return v['name'].strip()
    return ' '.join(str(x) for x in (v.get('year'), v.get('make'), v.get('model')) if x) or f"Vehicle #{v['vehicle_id']}"


# ---------------------------------------------------------------------------
# Database connections, shared by both sites.
# Opening a connection to Supabase takes about a second, so connections are kept open and reused
# (a small pool). If the database quietly dropped an idle connection, the first query of a page is
# retried once on a fresh one.
# ---------------------------------------------------------------------------
import threading

import psycopg2
import psycopg2.extras
from flask import g

_BROKEN = (psycopg2.OperationalError, psycopg2.InterfaceError)


class Database:
    def __init__(self, url, pooled=lambda: True, maxconn=5):
        self._url, self._pooled, self.maxconn = url, pooled, maxconn
        self._idle, self._lock = [], threading.Lock()       # [(url, connection)] ready to reuse
        self._url_of = {}                                    # id(connection) -> url it was opened with

    def _connect(self):
        conn = psycopg2.connect(self._url(), cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=10,
                                keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3)
        self._url_of[id(conn)] = self._url()
        return conn

    def _take(self):
        if self._pooled():
            url = self._url()
            with self._lock:
                while self._idle:
                    conn_url, conn = self._idle.pop()
                    if conn_url == url and not conn.closed:
                        return conn
                    self._url_of.pop(id(conn), None)
                    conn.close()
        return self._connect()

    def _give(self, conn, broken=False):
        try:
            if not broken and not conn.closed:
                conn.rollback()                 # end any open read, so the connection is clean for the next page
        except psycopg2.Error:
            broken = True
        url = self._url_of.get(id(conn))
        keep = self._pooled() and not broken and not conn.closed and url == self._url()
        with self._lock:
            if keep and len(self._idle) < self.maxconn:
                self._idle.append((url, conn))
                return
            self._url_of.pop(id(conn), None)
        conn.close()

    def close_all(self):
        with self._lock:
            idle, self._idle = self._idle, []
        for _, conn in idle:
            self._url_of.pop(id(conn), None)
            conn.close()

    # --- per request (Flask's g) ---------------------------------------------------------------
    def conn(self):
        if 'db' not in g:
            g.db, g.db_used = self._take(), False
        return g.db

    def release(self, _exc=None):
        conn = g.pop('db', None)
        if conn is not None:
            self._give(conn)

    def _execute(self, sql, args, write, one_row):
        for attempt in (1, 2):
            conn = self.conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, args)
                    rows = (cur.fetchone() if one_row else cur.fetchall()) if cur.description else None
                if write:
                    conn.commit()
                g.db_used = True
                return rows
            except _BROKEN:
                if g.get('db_used') or attempt == 2:
                    raise
                g.pop('db')                     # a stale connection: throw it away and try once on a new one
                self._give(conn, broken=True)
            except psycopg2.Error:
                if write:
                    conn.rollback()
                raise

    def q(self, sql, args=(), one=False):
        rows = self._execute(sql, args, write=False, one_row=False) or []
        return (rows[0] if rows else None) if one else rows

    def run(self, sql, args=()):
        return self._execute(sql, args, write=True, one_row=True)

    # --- several reads at once, and writes after the page is sent --------------------------------
    def _one_off(self, sql, args, write):
        """Run one statement on its own connection (not the page's). Retries once on a stale connection."""
        for attempt in (1, 2):
            conn = self._take()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, args)
                    rows = cur.fetchall() if cur.description else []
                if write:
                    conn.commit()
                self._give(conn)
                return rows
            except _BROKEN:
                self._give(conn, broken=True)
                if attempt == 2:
                    raise
            except Exception:
                self._give(conn)
                raise

    def q_many(self, queries):
        """[(sql, args), ...] -> [rows, ...]. Each round trip to Supabase takes ~0.1 s, so with the pool on
        the queries run at the same time on separate connections; without it, one after another."""
        if len(queries) < 2 or not self._pooled():
            return [self.q(sql, args) for sql, args in queries]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(queries), self.maxconn)) as ex:
            return list(ex.map(lambda qa: self._one_off(qa[0], qa[1], False), queries))

    def later(self, sql, args=(), on_error=None):
        """A write the page doesn't need to wait for (activity log, last seen). With the pool on it runs in
        the background after the page is sent; without it (tests), right away."""
        if not self._pooled():
            try:
                self.run(sql, args)
            except psycopg2.Error:
                if on_error:
                    on_error()
            return
        if not hasattr(self, '_writer'):
            from concurrent.futures import ThreadPoolExecutor
            self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix='db-later')

        def job():
            try:
                self._one_off(sql, args, True)
            except Exception:                # noqa: BLE001  (never breaks a page)
                if on_error:
                    on_error()
        self._writer.submit(job)


def compress_responses(app):
    """gzip pages, CSS and JS (about 70% smaller) for browsers that accept it."""
    import gzip
    from flask import request

    @app.after_request
    def _gzip(resp):
        if (resp.status_code != 200 or 'gzip' not in request.headers.get('Accept-Encoding', '')
                or 'Content-Encoding' in resp.headers
                or resp.mimetype not in ('text/html', 'text/css', 'application/javascript', 'text/javascript',
                                         'application/json', 'image/svg+xml')):
            return resp
        resp.direct_passthrough = False
        data = resp.get_data()
        if len(data) < 1000:
            return resp
        resp.set_data(gzip.compress(data, 6))
        resp.headers['Content-Encoding'] = 'gzip'
        resp.headers['Content-Length'] = str(len(resp.get_data()))
        resp.vary.add('Accept-Encoding')
        return resp

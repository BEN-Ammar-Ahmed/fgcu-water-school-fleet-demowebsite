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


def display_name(v):
    """The vehicle's Name (edited on its Edit page), else year make model, e.g. '2013 Ford F150 4x4'."""
    if (v.get('name') or '').strip():
        return v['name'].strip()
    return ' '.join(str(x) for x in (v.get('year'), v.get('make'), v.get('model')) if x) or f"Vehicle #{v['vehicle_id']}"

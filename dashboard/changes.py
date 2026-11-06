"""What an edit changed, for the activity log: [{field, old, new}], shown as "Mileage: 41,200 → 42,050"."""
import datetime as dt
from decimal import Decimal, InvalidOperation

# Shown as "changed" with no values, so the log never copies them.
HIDDEN = frozenset({'license_number', 'state', 'license_expiration', 'vin', 'license_plate'})


def _show(v) -> str:
    """One value as people read it. None and '' are both empty."""
    if v is None or v == '':
        return ''
    if isinstance(v, bool):
        return 'Yes' if v else 'No'
    if isinstance(v, dt.datetime):
        return v.strftime('%b %d, %Y %H:%M')
    if isinstance(v, dt.date):
        return v.strftime('%b %d, %Y')
    s = str(v).strip()
    try:
        return _show(dt.date.fromisoformat(s)) if len(s) == 10 and s[4] == '-' else _num(s)
    except ValueError:
        return s


def _num(s: str) -> str:
    try:
        d = Decimal(s.replace(',', ''))
    except InvalidOperation:
        return s
    if not d.is_finite() or s.strip().startswith('0') and len(s.strip()) > 1 and '.' not in s:
        return s   # keep things like tag "0042" as typed
    return f'{d:,.0f}' if d == d.to_integral_value() else f'{d.normalize():,f}'


def diff(before: dict, after: dict, labels: dict, hidden: frozenset = HIDDEN) -> list[dict]:
    """Fields in `after` whose value changed from `before`, in `after`'s order."""
    out = []
    for key, new in after.items():
        old_s, new_s = _show(before.get(key)), _show(new)
        if old_s == new_s:
            continue
        label = labels.get(key, key.replace('_', ' ').capitalize())
        if key in hidden:
            out.append({'field': label, 'old': None, 'new': None, 'hidden': True})
        else:
            out.append({'field': label, 'old': old_s or '(empty)', 'new': new_s or '(empty)'})
    return out


def text(details) -> str:
    """'Status: Active → In shop · VIN: changed'"""
    parts = []
    for d in details or []:
        parts.append(f"{d['field']}: changed" if d.get('hidden') else f"{d['field']}: {d['old']} → {d['new']}")
    return ' · '.join(parts)

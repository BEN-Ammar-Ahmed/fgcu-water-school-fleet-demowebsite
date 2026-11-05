"""Small form helper: one list of fields describes a form; parse() checks and converts what was sent."""
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation


@dataclass
class Field:
    name: str
    label: str
    kind: str = 'text'          # text | int | num | date | datetime | bool | select | textarea
    required: bool = False
    options: list = field(default_factory=list)   # [(value, label)] for select
    help: str = ''
    wide: bool = False


def _convert(f: Field, raw: str):
    if f.kind == 'bool':
        return raw in ('on', 'true', '1', 'yes')
    raw = (raw or '').strip()
    if raw == '':
        return None
    if f.kind == 'int':
        return int(raw.replace(',', ''))
    if f.kind == 'num':
        return Decimal(raw.replace(',', '').replace('$', ''))
    if f.kind == 'date':
        return dt.date.fromisoformat(raw)
    if f.kind == 'datetime':
        return dt.datetime.fromisoformat(raw)
    if f.kind == 'select' and f.options and raw not in {str(v) for v, _ in f.options}:
        raise ValueError
    return raw


_KIND_WORD = {'int': 'a whole number', 'num': 'a number', 'date': 'a date', 'datetime': 'a date and time',
              'select': 'one of the choices'}


def parse(fields: list[Field], form) -> tuple[dict, list[str]]:
    """Returns (values by field name, plain-English error messages)."""
    values, errors = {}, []
    for f in fields:
        try:
            values[f.name] = _convert(f, form.get(f.name, ''))
        except (ValueError, InvalidOperation):
            values[f.name] = form.get(f.name)
            errors.append(f'{f.label} must be {_KIND_WORD.get(f.kind, "valid")}.')
            continue
        if f.required and values[f.name] in (None, ''):
            errors.append(f'{f.label} is required.')
    return values, errors

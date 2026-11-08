"""Who can do what: three tiers (agreed with the client, Nov 2026) plus per-person switches.

Tier          role_name in wsb.app_role   Gets by default
top_admin     'Top admin' (or 'Admin')    everything, incl. driver's licenses and managing people
editor        'Staff'                     maintenance records, check-in/checkout
viewer        'Read-only' (or anything)   view only

A top admin can switch on extra abilities for one person (wsb.app_user_permission, 12_tiers.sql).
Driver's licenses and managing people are never switches: top admins only.
"""
from dataclasses import dataclass, field

LEVELS = ['top_admin', 'editor', 'viewer']
LEVEL_LABELS = {'top_admin': 'Tier 1 · Top admin', 'editor': 'Tier 2 · Editor', 'viewer': 'Tier 3 · Viewer'}
ROLE_FOR_LEVEL = {'top_admin': 'Top admin', 'editor': 'Staff', 'viewer': 'Read-only'}
_LEVEL_FOR_ROLE = {'Top admin': 'top_admin', 'Admin': 'top_admin', 'Staff': 'editor', 'Read-only': 'viewer'}

# Every switch, in the order the People page shows them.
PERMS = {
    'maintenance': 'Maintenance records (log service, mark done, schedules)',
    'checkout': 'Check-in / checkout',
    'trips_fuel': 'Log trips and fuel',
    'vehicles': 'Add / edit vehicles',
    'documents': 'Upload documents',
    'approve': 'Approve reservations',
    'delete': 'Delete records',
}
DEFAULTS = {'top_admin': frozenset(PERMS), 'editor': frozenset({'maintenance', 'checkout'}), 'viewer': frozenset()}
NEVER = {'viewer': frozenset({'delete'})}     # switches a tier can't be given


def switchable(level: str) -> list[str]:
    """Switches a top admin can turn on for someone at this tier (the ones it doesn't already have)."""
    return [p for p in PERMS if p not in DEFAULTS[level] and p not in NEVER.get(level, ())]


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    username: str
    full_name: str
    email: str | None
    level: str
    extras: frozenset = field(default_factory=frozenset)   # switches turned on for this person
    waiting: int = 0      # vehicle requests waiting for a decision (top bar badge; loaded with the user, no extra query)

    @property
    def perms(self) -> frozenset:
        return DEFAULTS[self.level] | (self.extras & frozenset(switchable(self.level)))

    def can(self, perm: str) -> bool:
        return perm in self.perms

    @property
    def is_admin(self) -> bool:          # the Admin area, drivers, all documents
        return self.level == 'top_admin'

    @property
    def can_edit(self) -> bool:          # can add or change anything at all (shows the Add menu, editor dashboard)
        return bool(self.perms & {'maintenance', 'checkout', 'trips_fuel', 'vehicles', 'documents'})

    @property
    def can_delete(self) -> bool:
        return self.can('delete')

    @property
    def can_see_licenses(self) -> bool:
        return self.level == 'top_admin'

    @property
    def can_manage_people(self) -> bool:
        return self.level == 'top_admin'

    @property
    def can_manage_admins(self) -> bool:
        return self.level == 'top_admin'

    @property
    def import_targets(self) -> list[str]:
        """Spreadsheet imports this person may run: the same data they may enter by hand."""
        out = []
        if self.can('vehicles'):
            out.append('vehicles')
        if self.can('trips_fuel'):
            out += ['fuel', 'trips']
        if self.can('maintenance'):
            out.append('maintenance')
        if self.is_admin:
            out.append('drivers')
        return out

    @property
    def tier_label(self) -> str:
        return LEVEL_LABELS[self.level]


def level_for_role(role_name: str) -> str:
    return _LEVEL_FOR_ROLE.get(role_name, 'viewer')


def doc_levels(user: CurrentUser) -> list[str]:
    """Document access levels this person may open."""
    return ['General', 'Staff', 'Admin'] if user.is_admin else ['General', 'Staff']


def assignable_levels(actor: CurrentUser) -> list[str]:
    """Levels this person may give to someone."""
    return list(LEVELS) if actor.can_manage_people else []


def can_change(actor: CurrentUser, target_level: str) -> bool:
    """Whether this person may change someone who is currently at target_level."""
    return target_level in assignable_levels(actor)


_USER_SQL = """SELECT u.user_id, u.username, u.full_name, u.email, r.role_name,
                      ARRAY(SELECT p.permission FROM wsb.app_user_permission p WHERE p.user_id = u.user_id) AS extras,
                      (SELECT count(*) FROM wsb.reservation WHERE status = 'Pending') AS waiting
               FROM wsb.app_user u JOIN wsb.app_role r USING (role_id)
               WHERE u.active AND {where}"""


def _to_user(row) -> CurrentUser | None:
    if not row:
        return None
    return CurrentUser(user_id=row['user_id'], username=row['username'], full_name=row['full_name'],
                       email=row['email'], level=level_for_role(row['role_name']),
                       extras=frozenset(row.get('extras') or ()), waiting=row.get('waiting') or 0)


def load_user(q, user_id: int) -> CurrentUser | None:
    return _to_user(q(_USER_SQL.format(where='u.user_id = %s'), (user_id,), one=True))


def user_for_email(q, email: str) -> CurrentUser | None:
    return _to_user(q(_USER_SQL.format(where='lower(u.email) = lower(%s)'), ((email or '').strip(),), one=True))

"""Access levels (agreed with Ahmed) and every permission rule the site uses.

Level        role_name in wsb.app_role   Confidential  View  Add/edit  Delete  Manage people
top_admin    'Top admin'                 yes           yes   yes       yes     everyone
admin        'Admin'                     no            yes   yes       yes     Tier 2 only
editor       'Staff'                     no            yes   yes       no      no
viewer       'Read-only' (or anything)   no            yes   no        no      no

Confidential data = driver's license records.
"""
from dataclasses import dataclass

LEVELS = ['top_admin', 'admin', 'editor', 'viewer']
LEVEL_LABELS = {'top_admin': 'Top admin', 'admin': 'Admin',
                'editor': 'Tier 2 · can edit', 'viewer': 'Tier 2 · view only'}
ROLE_FOR_LEVEL = {'top_admin': 'Top admin', 'admin': 'Admin', 'editor': 'Staff', 'viewer': 'Read-only'}
_LEVEL_FOR_ROLE = {v: k for k, v in ROLE_FOR_LEVEL.items()}
TIER2 = ('editor', 'viewer')


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    username: str
    full_name: str
    email: str | None
    level: str

    @property
    def is_admin(self) -> bool:
        return self.level in ('top_admin', 'admin')

    @property
    def can_edit(self) -> bool:
        return self.level in ('top_admin', 'admin', 'editor')

    @property
    def can_delete(self) -> bool:
        return self.is_admin

    @property
    def can_see_licenses(self) -> bool:
        return self.level == 'top_admin'

    @property
    def can_manage_people(self) -> bool:
        return self.is_admin

    @property
    def can_manage_admins(self) -> bool:
        return self.level == 'top_admin'

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
    if actor.can_manage_admins:
        return list(LEVELS)
    return list(TIER2) if actor.can_manage_people else []


def can_change(actor: CurrentUser, target_level: str) -> bool:
    """Whether this person may change someone who is currently at target_level."""
    return target_level in assignable_levels(actor)


_USER_SQL = """SELECT u.user_id, u.username, u.full_name, u.email, r.role_name
               FROM wsb.app_user u JOIN wsb.app_role r USING (role_id)
               WHERE u.active AND {where}"""


def _to_user(row) -> CurrentUser | None:
    if not row:
        return None
    return CurrentUser(user_id=row['user_id'], username=row['username'], full_name=row['full_name'],
                       email=row['email'], level=level_for_role(row['role_name']))


def load_user(q, user_id: int) -> CurrentUser | None:
    return _to_user(q(_USER_SQL.format(where='u.user_id = %s'), (user_id,), one=True))


def user_for_email(q, email: str) -> CurrentUser | None:
    return _to_user(q(_USER_SQL.format(where='lower(u.email) = lower(%s)'), ((email or '').strip(),), one=True))

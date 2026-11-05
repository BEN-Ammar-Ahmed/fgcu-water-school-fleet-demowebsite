def test_demo_users_and_license_flag(dbq):
    rows = dbq("""SELECT u.username, r.role_name, u.can_see_licenses, u.active
                  FROM wsb.app_user u JOIN wsb.app_role r USING (role_id)
                  WHERE u.email LIKE '%%@example.edu' AND u.username LIKE 'demo\\_tier%%' OR u.username = 'demo_inactive'
                  ORDER BY u.username""")
    got = {(r['username'], r['role_name'], r['can_see_licenses'], r['active']) for r in rows}
    assert got == {
        ('demo_tier1', 'Top admin', True, True),
        ('demo_tier1_backup', 'Admin', False, True),
        ('demo_tier2', 'Read-only', False, True),
        ('demo_tier2_licenses', 'Read-only', False, True),
        ('demo_inactive', 'Read-only', False, False),
    }

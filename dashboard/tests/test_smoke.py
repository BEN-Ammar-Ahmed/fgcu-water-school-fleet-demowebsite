def test_template_has_demo_data(dbq):
    assert dbq("select count(*) n from wsb.vehicle where asset_number like 'DEMO-%'")[0]['n'] == 8

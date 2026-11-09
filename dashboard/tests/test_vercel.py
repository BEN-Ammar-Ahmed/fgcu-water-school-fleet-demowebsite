"""Running on Vercel: documents kept in the database, and the entry point that picks the site."""
import importlib
import io
import sys


def test_documents_in_database_upload_open_delete(client, sign_in, dbq, app_module, monkeypatch):
    monkeypatch.setenv('DOCUMENTS_IN_DATABASE', '1')
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-T01'")[0]['vehicle_id']
    sign_in(client, 'demo_tier1')
    r = client.post(f'/vehicles/{vid}/documents', content_type='multipart/form-data',
                    data={'file': (io.BytesIO(b'%PDF-demo'), 'reg.pdf'), 'document_type': 'Registration',
                          'access_level': 'General'})
    assert r.status_code == 302
    assert not (app_module.UPLOADS / str(vid)).exists()          # nothing written to disk
    doc = dbq('SELECT document_id, file_location FROM wsb.vehicle_document WHERE vehicle_id = %s '
              'ORDER BY document_id DESC LIMIT 1', (vid,))[0]
    stored = dbq('SELECT content FROM wsb.document_file WHERE file_location = %s', (doc['file_location'],))
    assert bytes(stored[0]['content']) == b'%PDF-demo'

    r = client.get(f"/documents/{doc['document_id']}/file?dl=1")
    assert r.status_code == 200 and r.data == b'%PDF-demo'
    assert 'reg.pdf' in r.headers['Content-Disposition']

    client.post(f"/documents/{doc['document_id']}/delete")
    assert dbq('SELECT count(*) n FROM wsb.document_file WHERE file_location = %s', (doc['file_location'],))[0]['n'] == 0


def test_documents_on_disk_by_default(client, sign_in, dbq, app_module, monkeypatch):
    monkeypatch.delenv('DOCUMENTS_IN_DATABASE', raising=False)
    monkeypatch.delenv('VERCEL', raising=False)
    vid = dbq("SELECT vehicle_id FROM wsb.vehicle WHERE asset_number = 'DEMO-T01'")[0]['vehicle_id']
    sign_in(client, 'demo_tier1')
    client.post(f'/vehicles/{vid}/documents', content_type='multipart/form-data',
                data={'file': (io.BytesIO(b'%PDF'), 'reg.pdf'), 'document_type': 'Registration', 'access_level': 'General'})
    assert any((app_module.UPLOADS / str(vid)).iterdir())
    assert dbq('SELECT count(*) n FROM wsb.document_file')[0]['n'] == 0


def test_vercel_entry_picks_the_site(app_module, monkeypatch):
    import reserve_app
    for site, expected in (('fleet', app_module.app), ('reserve', reserve_app.app)):
        monkeypatch.setenv('SITE', site)
        sys.modules.pop('api.index', None)
        entry = importlib.import_module('api.index')
        assert entry.app is expected

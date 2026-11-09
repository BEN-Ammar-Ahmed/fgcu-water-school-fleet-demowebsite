"""Where uploaded documents are kept: files in dashboard/uploads/ (the default), or rows in wsb.document_file
when DOCUMENTS_IN_DATABASE=1. Vercel has no lasting disk, so there the database is always used.
Each document is named by its file_location, '<vehicle id>/<random>_<name>'."""
import io
import os

from flask import send_file, send_from_directory


def in_database():
    return os.environ.get('DOCUMENTS_IN_DATABASE') == '1' or bool(os.environ.get('VERCEL'))


def save(core, rel, upload):
    """Keep the uploaded file under the name rel."""
    if in_database():
        core.run('INSERT INTO wsb.document_file (file_location, content) VALUES (%s, %s)', (rel, upload.read()))
    else:
        (core.UPLOADS / rel).parent.mkdir(parents=True, exist_ok=True)
        upload.save(core.UPLOADS / rel)


def remove(core, rel):
    if in_database():
        core.run('DELETE FROM wsb.document_file WHERE file_location = %s', (rel,))
    else:
        (core.UPLOADS / rel).unlink(missing_ok=True)


def response(core, rel, as_attachment):
    """The file, ready to send to the browser (404 if it's gone)."""
    folder, fname = rel.split('/', 1)
    if not in_database():
        return send_from_directory(core.UPLOADS / folder, fname, as_attachment=as_attachment)
    row = core.q('SELECT content FROM wsb.document_file WHERE file_location = %s', (rel,), one=True)
    if not row:
        from flask import abort
        abort(404)
    return send_file(io.BytesIO(bytes(row['content'])), download_name=fname, as_attachment=as_attachment)

"""Import a spreadsheet (/import). Reaches the main app's helpers through `core`, like admin.py."""
import psycopg2
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

imp = Blueprint('imp', __name__)
core = None          # the main app module; set by app.py


# ---------------------------------------------------------------------------
# Import a spreadsheet. Anyone may import the data they may enter by hand (CurrentUser.import_targets).
# Upload → match columns → review → save. See importer.py.
# The file is read in memory and never stored; the rows travel between steps inside the form.
# ---------------------------------------------------------------------------
def _allowed_targets():
    u = core.current_user()
    if not u:
        abort(401)
    if not u.import_targets:
        abort(403)
    return u.import_targets


@imp.route('/import', methods=['GET', 'POST'])
def import_upload():
    import json
    import importer
    allowed = _allowed_targets()
    g.page_label = 'Import a spreadsheet'
    target = request.form.get('target', '') or request.args.get('last', '')
    if request.method == 'POST':
        f = request.files.get('file')
        if target not in importer.TARGETS:
            flash('Choose what the file holds.', 'error')
        elif target not in allowed:
            abort(403)
        elif not f or not f.filename:
            flash('Choose a file to upload.', 'error')
        else:
            try:
                headers, rows = importer.read_table(f.filename, f.read())
            except ValueError as e:
                flash(str(e), 'error')
            else:
                return render_template('import_match.html', target=target, t=importer.TARGETS[target],
                                       fields=importer.fields(target), headers=headers, sample=rows[:3],
                                       nrows=len(rows), mapping=importer.guess_mapping(target, headers),
                                       filename=f.filename, table=json.dumps({'headers': headers, 'rows': rows}),
                                       hidden=importer.HIDDEN, mask=importer.mask)
    last = request.args.get('last') if request.args.get('last') in allowed else None
    return render_template('import.html', targets={k: t for k, t in importer.TARGETS.items() if k in allowed}, last=last,
                           target=target)


@imp.route('/import/review', methods=['POST'])
def import_review():
    import json
    import importer
    allowed = _allowed_targets()
    g.page_label = 'Import a spreadsheet'
    me = core.current_user()
    target, filename = request.form.get('target', ''), request.form.get('filename', '')[:200]
    if target not in importer.TARGETS:
        abort(400)
    if target not in allowed:
        abort(403)
    fl = importer.fields(target)
    if 'table' in request.form:          # coming from the match step
        try:
            table = json.loads(request.form['table'])
            rows = table['rows']
        except (ValueError, KeyError, TypeError):
            abort(400)
        mapping = {}
        for f in fl:
            v = request.form.get(f'map_{f.name}', '')
            mapping[f.name] = int(v) if v.isdigit() and int(v) < len(table['headers']) else None
        records = importer.apply_mapping(target, mapping, rows)
        keep = [True] * len(records)
    else:                                # coming back from the review step (edited cells)
        n = min(int(request.form.get('n', '0') or 0), importer.MAX_ROWS)
        records = [{f.name: request.form.get(f'c{i}_{f.name}', '') for f in fl} for i in range(n)]
        keep = [request.form.get(f'keep{i}') == 'on' for i in range(n)]
    checked = importer.check(core.q, me, target, records)
    kept = [c for c, k in zip(checked, keep) if k]
    bad = sum(1 for c in kept if c['errors'])
    if request.form.get('action') == 'save':
        if not kept:
            flash('No rows are ticked, so nothing was saved.', 'error')
        elif bad:
            flash(f'{bad} ticked row{"s have" if bad != 1 else " has"} problems. Fix them or untick them, then save again.', 'error')
        else:
            try:
                n = importer.save(core.db(), me, target, [c['values'] for c in kept])
            except psycopg2.Error as e:
                flash(f"Nothing was saved. Row {getattr(e, 'import_row', '?')} was refused by the database: "
                      f"{core.db_error_message(e)}", 'error')
            else:
                core.log_activity('change', f"Imported {n} {importer.TARGETS[target]['label'].lower()} from {filename or 'a file'}")
                flash(f"Saved {n} row{'s' if n != 1 else ''}.", 'ok')
                return redirect(url_for('imp.import_upload', last=target))   # stay here for the next file
    return render_template('import_review.html', target=target, t=importer.TARGETS[target], fields=fl,
                           rows=checked, keep=keep, filename=filename, bad=bad, nkept=len(kept),
                           hidden=importer.HIDDEN, mask=importer.mask)

// Confirm dialog for deletes and other actions that can't be undone (replaces the browser's plain confirm box).
// Put it on a form or a submit button:
//   data-confirm="Delete this document?"          title (required)
//   data-confirm-body="Registration.pdf on ..."   what exactly will happen
//   data-confirm-button="Delete document"          the red button's label (default "Delete")
// On a phone it shows as a sheet from the bottom. Without JavaScript the action simply goes ahead.
(function () {
  var dlg, title, body, ok, pending;

  function build() {
    dlg = document.createElement('dialog');
    dlg.className = 'confirm-dialog';
    dlg.setAttribute('aria-labelledby', 'confirm-title');
    dlg.innerHTML =
      '<form method="dialog" class="confirm-inner">' +
      '<div class="confirm-icon" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg></div>' +
      '<h2 id="confirm-title"></h2><p class="confirm-body"></p>' +
      '<p class="confirm-note">This can\'t be undone. It\'s recorded in Activity.</p>' +
      '<div class="confirm-actions"><button value="cancel" class="btn">Cancel</button>' +
      '<button value="ok" class="btn btn-danger"></button></div></form>';
    document.body.appendChild(dlg);
    title = dlg.querySelector('h2');
    body = dlg.querySelector('.confirm-body');
    ok = dlg.querySelector('.btn-danger');
    dlg.addEventListener('close', function () {
      var p = pending; pending = null;
      if (dlg.returnValue === 'ok' && p) {
        p.form.dataset.confirmed = '1';
        if (p.button && p.form.requestSubmit) p.form.requestSubmit(p.button); else p.form.submit();
      }
    });
    dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close('cancel'); });   // click outside
  }

  function ask(el, form, button) {
    if (!dlg) build();
    title.textContent = el.dataset.confirm;
    body.textContent = el.dataset.confirmBody || '';
    body.hidden = !el.dataset.confirmBody;
    dlg.querySelector('.confirm-note').hidden = el.dataset.confirmNote === 'none';
    ok.textContent = el.dataset.confirmButton || 'Delete';
    pending = { form: form, button: button };
    dlg.returnValue = '';
    dlg.showModal();
    dlg.querySelector('button[value="cancel"]').focus();
  }

  document.addEventListener('submit', function (e) {
    var form = e.target, button = e.submitter;
    if (form.dataset.confirmed) { delete form.dataset.confirmed; return; }
    var el = (button && button.dataset.confirm) ? button : (form.dataset.confirm ? form : null);
    if (!el || typeof HTMLDialogElement === 'undefined') return;
    e.preventDefault();
    ask(el, form, button);
  });
})();

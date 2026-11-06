// Suggestions while typing. Any <input data-suggest="<field>"> gets a dropdown from /suggest.
// data-suggest-mode: "go" (default) opens the item's page; "fill" puts the text in the box and submits.
(function () {
  var seq = 0;
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function bold(label, text) {
    var i = label.toLowerCase().indexOf(text.toLowerCase());
    if (i < 0 || !text) return esc(label);
    return esc(label.slice(0, i)) + '<b>' + esc(label.slice(i, i + text.length)) + '</b>' + esc(label.slice(i + text.length));
  }

  document.querySelectorAll('input[data-suggest]').forEach(function (input) {
    var id = 'sug-' + (++seq), list = document.createElement('div'), timer, ctrl, items = [], active = -1;
    var mode = input.dataset.suggestMode || 'go';
    list.id = id; list.className = 'suggest'; list.setAttribute('role', 'listbox'); list.hidden = true;
    input.setAttribute('role', 'combobox'); input.setAttribute('aria-controls', id);
    input.setAttribute('aria-expanded', 'false'); input.setAttribute('autocomplete', 'off');
    var holder = input.parentNode; if (getComputedStyle(holder).position === 'static') holder.style.position = 'relative';
    holder.appendChild(list);

    function close() { list.hidden = true; input.setAttribute('aria-expanded', 'false'); active = -1; input.removeAttribute('aria-activedescendant'); }
    function pick(it) {
      var form = input.form;
      if (it.all || (!it.url && mode === 'go')) { if (form) form.requestSubmit ? form.requestSubmit() : form.submit(); return; }
      if (mode === 'go' && it.url) { location.href = it.url; return; }
      input.value = it.value || it.label; close();
      if (form && input.dataset.suggestSubmit !== 'false') form.requestSubmit ? form.requestSubmit() : form.submit();
    }
    function mark() {
      list.querySelectorAll('[role=option]').forEach(function (el, i) { el.classList.toggle('on', i === active); el.setAttribute('aria-selected', i === active); });
      if (active >= 0) input.setAttribute('aria-activedescendant', id + '-' + active); else input.removeAttribute('aria-activedescendant');
    }
    function render(data, text) {
      items = []; var html = '';
      (data.groups || []).forEach(function (g) {
        html += '<div class="suggest-group">' + esc(g.label) + '</div>';
        g.items.forEach(function (it) {
          var n = items.length; items.push(it);
          html += '<div class="suggest-item' + (it.all ? ' all' : '') + '" role="option" id="' + id + '-' + n + '" data-n="' + n + '">' +
                  '<span>' + (it.all ? 'See all results' : bold(it.label, text)) + '</span>' + (it.detail ? '<small>' + esc(it.detail) + '</small>' : '') + '</div>';
        });
      });
      if (data.did_you_mean) {
        var n = items.length; items.push({label: data.did_you_mean, value: data.did_you_mean, fix: true});
        html += '<div class="suggest-item fix" role="option" id="' + id + '-' + n + '" data-n="' + n + '">Did you mean <b>' + esc(data.did_you_mean) + '</b>?</div>';
      }
      if (!items.length) { close(); return; }
      list.innerHTML = html; list.hidden = false; input.setAttribute('aria-expanded', 'true'); active = -1;
    }
    input.addEventListener('input', function () {
      clearTimeout(timer);
      var text = input.value.trim();
      if (text.length < 2) { close(); return; }
      timer = setTimeout(function () {
        if (ctrl) ctrl.abort();
        ctrl = window.AbortController ? new AbortController() : null;
        fetch('/suggest?field=' + encodeURIComponent(input.dataset.suggest) + '&q=' + encodeURIComponent(text), ctrl ? {signal: ctrl.signal} : {})
          .then(function (r) { return r.ok ? r.json() : {groups: []}; })
          .then(function (d) { if (input.value.trim() === text) render(d, text); })
          .catch(function () {});
      }, 200);
    });
    input.addEventListener('keydown', function (e) {
      if (list.hidden) return;
      if (e.key === 'ArrowDown') { active = Math.min(items.length - 1, active + 1); mark(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { active = Math.max(-1, active - 1); mark(); e.preventDefault(); }
      else if (e.key === 'Escape') { close(); e.stopPropagation(); }
      else if (e.key === 'Enter' && active >= 0) {
        e.preventDefault(); var it = items[active];
        if (it.fix) { input.value = it.value; close(); if (input.form) input.form.submit(); } else pick(it);
      }
    });
    list.addEventListener('mousedown', function (e) {
      var el = e.target.closest('[data-n]'); if (!el) return;
      e.preventDefault(); var it = items[+el.dataset.n];
      if (it.fix) { input.value = it.value; close(); if (input.form) input.form.submit(); } else pick(it);
    });
    input.addEventListener('blur', function () { setTimeout(close, 150); });
  });
})();

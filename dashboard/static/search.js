// Expanding search (matches the approved mockup).
// Home: round icon -> click stretches it sideways into the bar; Enter searches; Esc closes.
// Anywhere: "/" opens (home) or focuses the search box.
(function () {
  var body = document.body;
  var box = document.getElementById('searchbox');
  var input = document.getElementById('q') || document.querySelector('.topsearch input[name="q"]');
  var RISE = 'wsb-search-rise';

  function open() {
    if (!body.classList.contains('home') || body.classList.contains('open')) return;
    body.classList.add('open');
    setTimeout(function () { input && input.focus(); }, 300);
  }
  function close() {
    body.classList.remove('open');
    input && input.blur();
  }

  var btn = document.getElementById('search-open');
  if (btn) btn.addEventListener('click', open);
  if (box && body.classList.contains('home')) {
    box.addEventListener('click', open);
    box.addEventListener('submit', function (e) {
      if (!input.value.trim()) { e.preventDefault(); return; }
      try { sessionStorage.setItem(RISE, '1'); } catch (err) {}
    });
    // Category chips on the home page set the kind, then search.
    document.querySelectorAll('.home .chip').forEach(function (chip) {
      chip.addEventListener('click', function (e) {
        e.preventDefault();
        document.querySelectorAll('.home .chip').forEach(function (c) { c.classList.remove('on'); });
        chip.classList.add('on');
        document.getElementById('kind').value = chip.dataset.kind;
        if (input.value.trim()) box.requestSubmit();
        else input.focus();
      });
    });
  }

  document.addEventListener('keydown', function (e) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (e.key === '/' && !typing) {
      e.preventDefault();
      if (body.classList.contains('home')) open(); else if (input) { input.focus(); input.select(); }
    } else if (e.key === 'Escape' && body.classList.contains('open') && !input.value) {
      close();
    }
  });

  // Coming from the home page: the bar slides up from the middle once.
  if (body.classList.contains('searched')) {
    var rise = false;
    try { rise = sessionStorage.getItem(RISE) === '1'; sessionStorage.removeItem(RISE); } catch (err) {}
    if (rise) body.classList.add('rise');
  }
})();

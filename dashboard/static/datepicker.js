// Date range + time picker for a form with two datetime fields named pickup_at and return_at.
// Click a start day, then an end day; pick the times from the list. Writes the same values the plain fields would
// ("2026-11-20T08:00"), so the server doesn't change. Without JavaScript the plain fields are used.
(function () {
  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
                'November', 'December'];
  var DAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
  var LONG = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var TIMES = [];
  for (var h = 6; h <= 20; h++) for (var m = 0; m < 60; m += 30) if (!(h === 20 && m)) TIMES.push(pad(h) + ':' + pad(m));

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function iso(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function parse(v) { var m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)/.exec(v || ''); return m ? { day: m[1] + '-' + m[2] + '-' + m[3], time: m[4] + ':' + m[5] } : null; }
  function dateOf(s) { var p = s.split('-'); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function ampm(t) { var h = +t.slice(0, 2), m = t.slice(3); return (h % 12 || 12) + ':' + m + (h < 12 ? ' AM' : ' PM'); }
  function nice(day, time) {
    if (!day) return 'Choose a day';
    var d = dateOf(day);
    return LONG[d.getDay()] + ', ' + MONTHS[d.getMonth()].slice(0, 3) + ' ' + d.getDate() + (time ? ' · ' + ampm(time) : '');
  }

  function enhance(form) {
    var pick = form.querySelector('input[name="pickup_at"]'), ret = form.querySelector('input[name="return_at"]');
    if (!pick || !ret || pick.dataset.enhanced) return;
    pick.dataset.enhanced = '1';
    var a = parse(pick.value) || {}, b = parse(ret.value) || {};
    var st = { start: a.day || null, end: b.day || a.day || null, tStart: a.time || '08:00', tEnd: b.time || '17:00',
               which: 'start', picking: false };
    var today = iso(new Date());
    var shown = dateOf(st.start || today); shown.setDate(1);

    var box = document.createElement('div');
    box.className = 'dp wide';
    box.innerHTML =
      '<div class="dp-fields">' +
      '<button type="button" class="dp-field" data-w="start"><span class="dp-lbl">Pick up</span><span class="dp-val"></span></button>' +
      '<button type="button" class="dp-field" data-w="end"><span class="dp-lbl">Return</span><span class="dp-val"></span></button></div>' +
      '<div class="dp-panel">' +
      '<div class="dp-cal"><div class="dp-head"><button type="button" class="dp-nav" data-n="-1" aria-label="Previous month">&#8249;</button>' +
      '<b class="dp-month" aria-live="polite"></b><button type="button" class="dp-nav" data-n="1" aria-label="Next month">&#8250;</button></div>' +
      '<div class="dp-grid"></div><p class="dp-hint"></p></div>' +
      '<div class="dp-times"><div class="dp-tabs"><button type="button" data-w="start">Pick-up time</button>' +
      '<button type="button" data-w="end">Return time</button></div><div class="dp-slots" aria-label="Times"></div></div></div>';
    var anchor = pick.closest('label') || pick;
    anchor.parentNode.insertBefore(box, anchor);
    [pick, ret].forEach(function (i) { var l = i.closest('label'); if (l) l.hidden = true; i.type = 'hidden'; });

    function write() {
      pick.value = st.start ? st.start + 'T' + st.tStart : '';
      ret.value = st.end ? st.end + 'T' + st.tEnd : '';
      var v = box.querySelectorAll('.dp-val');
      v[0].textContent = nice(st.start, st.start && st.tStart);
      v[1].textContent = nice(st.end, st.end && st.tEnd);
      box.querySelectorAll('[data-w]').forEach(function (b) { b.classList.toggle('on', b.dataset.w === st.which); });
    }
    function cal() {
      box.querySelector('.dp-month').textContent = MONTHS[shown.getMonth()] + ' ' + shown.getFullYear();
      var g = DAYS.map(function (d) { return '<span class="dp-dow" aria-hidden="true">' + d + '</span>'; }).join('');
      for (var i = 0; i < shown.getDay(); i++) g += '<span></span>';
      var n = new Date(shown.getFullYear(), shown.getMonth() + 1, 0).getDate();
      for (var d = 1; d <= n; d++) {
        var day = iso(new Date(shown.getFullYear(), shown.getMonth(), d)), cls = 'dp-day';
        if (day < today) cls += ' past';
        if (day === st.start || day === st.end) cls += ' end';
        else if (st.start && st.end && day > st.start && day < st.end) cls += ' in';
        if (day === today) cls += ' today';
        g += '<button type="button" class="' + cls + '" data-day="' + day + '"' + (day < today ? ' disabled' : '') +
             ' aria-label="' + nice(day) + '">' + d + '</button>';
      }
      box.querySelector('.dp-grid').innerHTML = g;
      box.querySelector('.dp-hint').textContent = st.picking ? 'Now click the return day.' : 'Click the pick-up day, then the return day.';
    }
    function slots() {
      var cur = st.which === 'start' ? st.tStart : st.tEnd;
      box.querySelector('.dp-slots').innerHTML = TIMES.map(function (t) {
        return '<button type="button" class="dp-slot' + (t === cur ? ' on' : '') + '" aria-pressed="' + (t === cur) +
               '" data-t="' + t + '">' + ampm(t) + '</button>';
      }).join('');
      var list = box.querySelector('.dp-slots'), on = list.querySelector('.dp-slot.on');
      if (on) list.scrollTop = on.offsetTop - list.offsetTop - 60;   // scroll the list only, never the page
    }
    box.addEventListener('click', function (e) {
      var t = e.target.closest('button'); if (!t) return;
      if (t.dataset.n) { shown.setMonth(shown.getMonth() + +t.dataset.n); cal(); return; }
      if (t.dataset.day) {
        var d = t.dataset.day;
        if (!st.picking) { st.start = st.end = d; st.picking = true; st.which = 'start'; }
        else { if (d < st.start) { st.end = st.start; st.start = d; } else st.end = d; st.picking = false; st.which = 'end'; }
        if (st.start === st.end && st.tEnd <= st.tStart) st.tEnd = TIMES[Math.min(TIMES.indexOf(st.tStart) + 2, TIMES.length - 1)];
        cal(); slots(); write(); return;
      }
      if (t.dataset.t) {
        if (st.which === 'start') st.tStart = t.dataset.t; else st.tEnd = t.dataset.t;
        slots(); write(); return;
      }
      if (t.dataset.w) { st.which = t.dataset.w; var d2 = st.which === 'start' ? st.start : st.end;
        if (d2) { shown = dateOf(d2); shown.setDate(1); } cal(); slots(); write(); }
    });
    cal(); slots(); write();
  }

  document.querySelectorAll('form').forEach(enhance);
})();

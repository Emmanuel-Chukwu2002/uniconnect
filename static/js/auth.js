/* Sign-in / sign-up without page reloads (accounts/auth_split.html).
   The left-hand introduction stays put; clicking Sign Up / Sign In (links
   marked data-lp-swap) or sending a sign-up step (forms marked
   data-lp-swap) fetches the next page and swaps just the right-hand panel
   (#lpPanel), updating the address bar so refresh and Back still work.
   Anything that doesn't come back as a sign-in/sign-up panel (for example
   the app after signing in) is opened as a normal page. Without JavaScript
   all of these are ordinary links and forms. */
(function () {
  'use strict';
  var busy = false;

  function panel() { return document.getElementById('lpPanel'); }

  // Show/hide eye on password boxes in a newly swapped panel (app.js does
  // this for the panel the page first loaded with).
  function addPasswordToggles(root) {
    root.querySelectorAll('input[type="password"]').forEach(function (input) {
      if (input.parentNode.classList.contains('password-field-wrapper')) { return; }
      var wrap = document.createElement('div');
      wrap.className = 'password-field-wrapper';
      input.parentNode.insertBefore(wrap, input);
      wrap.appendChild(input);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'password-toggle-btn';
      btn.tabIndex = -1;
      btn.setAttribute('aria-label', 'Show password');
      btn.innerHTML = '<i class="bi bi-eye"></i>';
      wrap.appendChild(btn);
      btn.addEventListener('click', function () {
        var hidden = input.type === 'password';
        input.type = hidden ? 'text' : 'password';
        btn.firstChild.className = hidden ? 'bi bi-eye-slash' : 'bi bi-eye';
        btn.setAttribute('aria-label', hidden ? 'Hide password' : 'Show password');
      });
    });
  }

  function go(url, options) {
    var current = panel();
    if (!current || busy || !window.fetch || !window.DOMParser) { return false; }
    busy = true;
    current.classList.add('is-busy');
    fetch(url, Object.assign({ credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } }, options || {}))
      .then(function (res) {
        return res.text().then(function (html) { return { url: res.url || url, html: html }; });
      })
      .then(function (r) {
        var doc = new DOMParser().parseFromString(r.html, 'text/html');
        var next = doc.getElementById('lpPanel');
        if (!next) { location.assign(r.url); return; }
        if (r.url !== location.href) { history.pushState({ lpPanel: true }, '', r.url); }
        document.title = doc.title;
        current.replaceWith(next);
        next.classList.add('is-entering');
        setTimeout(function () { next.classList.remove('is-entering'); }, 400);
        addPasswordToggles(next);
        if (window.innerWidth < 900 || next.getBoundingClientRect().top < 0) { window.scrollTo(0, 0); }
        var first = next.querySelector('.lp-form input:not([type=hidden]):not([type=checkbox]), .lp-form select');
        if (first && !first.value && window.innerWidth >= 900) { first.focus({ preventScroll: true }); }
      })
      .catch(function () { location.assign(url); })
      .then(function () {
        busy = false;
        var p = panel();
        if (p) { p.classList.remove('is-busy'); }
      });
    return true;
  }

  // The phone welcome screen (login.html, login.css "Welcome screen"):
  // "Log In" slides it away to the sign-in form; "Get Started" slides it
  // away and opens sign-up in place.
  function hideWelcome() {
    var w = document.getElementById('lpWelcome');
    if (!w) { return; }
    w.classList.add('is-gone');
    document.documentElement.classList.remove('lp-welcoming');
    setTimeout(function () { w.remove(); }, 350);
  }
  if (document.getElementById('lpWelcome') && window.matchMedia('(max-width: 600px)').matches) {
    document.documentElement.classList.add('lp-welcoming');
  }

  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return; }
    var w = e.target.closest && e.target.closest('.js-lp-welcome-login, .js-lp-welcome-go');
    if (w) {
      e.preventDefault();
      hideWelcome();
      if (w.classList.contains('js-lp-welcome-go')) { if (!go(w.href)) { location.assign(w.href); } }
      return;
    }
    var a = e.target.closest && e.target.closest('a[data-lp-swap]');
    if (a && a.closest('#lpPanel')) {
      if (go(a.href)) { e.preventDefault(); }
      return;
    }
    // "Remember me" also applies to Google sign-in.
    var g = e.target.closest && e.target.closest('.js-lp-google');
    if (g) {
      var box = document.querySelector('.js-lp-remember');
      g.href = g.href.split('?')[0] + (box && box.checked ? '?remember=1' : '');
    }
  });

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (e.defaultPrevented || !form.matches('form[data-lp-swap]') || !form.closest('#lpPanel')) { return; }
    var data;
    try { data = new FormData(form, e.submitter || null); } catch (err) {
      data = new FormData(form);
      if (e.submitter && e.submitter.name) { data.append(e.submitter.name, e.submitter.value); }
    }
    if (go(form.getAttribute('action') || location.href, { method: 'POST', body: data })) { e.preventDefault(); }
  });
})();

/* Sign-up "Choose your username" step: checks the name as it's typed
   (/register/username/check/, accounts/views.py) and fills it in when an
   idea chip is tapped. Listens on the document, so it works on a step
   swapped in by the code above. */
(function () {
  'use strict';
  var timer = null, seq = 0;
  function show(input, kind, text) {
    var wrap = input.closest('.lp-input'), msg = document.querySelector('.js-signup-username-msg');
    if (wrap) { wrap.classList.toggle('has-error', kind === 'bad'); wrap.classList.toggle('is-ok', kind === 'ok'); }
    if (msg) { msg.textContent = text; msg.classList.toggle('is-bad', kind === 'bad'); msg.classList.toggle('is-ok', kind === 'ok'); }
  }
  function check(input) {
    var v = input.value.replace(/^@+/, '').trim();
    if (input.value !== v) { input.value = v; }
    clearTimeout(timer);
    if (!v) { show(input, '', '4–15 characters: letters, numbers and underscores. You can change it later in Settings.'); return; }
    if (!/^[A-Za-z0-9_]+$/.test(v)) { show(input, 'bad', 'Use only letters, numbers and underscores (_).'); return; }
    if (v.length < 4) { show(input, 'bad', 'Your username must be at least 4 characters.'); return; }
    show(input, '', 'Checking…');
    var mine = ++seq;
    timer = setTimeout(function () {
      fetch('/register/username/check/?u=' + encodeURIComponent(v), { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (d) { if (mine === seq) { show(input, d.ok ? 'ok' : 'bad', d.message); } })
        .catch(function () { if (mine === seq) { show(input, '', ''); } });
    }, 300);
  }
  document.addEventListener('input', function (e) {
    if (e.target.matches && e.target.matches('.js-signup-username')) { check(e.target); }
  });
  document.addEventListener('click', function (e) {
    var chip = e.target.closest && e.target.closest('.js-signup-username-pick');
    if (!chip) { return; }
    var input = document.querySelector('.js-signup-username');
    if (!input) { return; }
    input.value = chip.dataset.name;
    input.focus();
    check(input);
  });
})();

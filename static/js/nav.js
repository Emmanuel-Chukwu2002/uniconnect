/* =====================================================================
   In-place page loading (no full page refresh).

   Inside the app (every page built from feed/base_app.html), clicking a
   link or submitting a form inside the page fetches the next page in the
   background and swaps in only what changes:
     - the middle column (.app-main),
     - which menu item is highlighted, and the unread / cart badges,
     - the tab title, the address bar (so Back / Forward work),
     - page-specific CSS and JS (e.g. bookshop.css / bookshop.js).
   The sidebars, open chats in other tabs, the notification poller and
   everything else stay as they are — nothing reloads.

   It falls back to an ordinary page load when it can't do that safely:
   Messages (its own live chat app), Logout, Admin, files in /media/,
   links opening a new tab, and any page that isn't an app page (login
   screen after a session timeout, error pages, ...).

   For page scripts: code that sets up elements inside the page registers
   with UC.onPage(fn). fn(document, signal) runs once when the page first
   loads and again after every in-place swap; `signal` is aborted when the
   page is left, so listeners added on window/document with { signal }
   are cleaned up automatically.
   Opt a link or form out with data-no-soft.
   ===================================================================== */
(function () {
  'use strict';

  var UC = window.UC = window.UC || {};
  var hooks = [];
  var pageCtrl = makeCtrl();
  var ready = false;

  function makeCtrl() { return 'AbortController' in window ? new AbortController() : { signal: undefined, abort: function () {} }; }
  function runHook(fn) {
    try { fn(document, pageCtrl.signal); } catch (err) { if (window.console) { console.error(err); } }
  }
  // A page's inline code runs each time the page is shown, so the same hook
  // would be registered again on every visit — and then run twice (two
  // listeners: one tap = two likes). The same code is registered once; it
  // has already run for this page in runHooks() before the page's scripts.
  var hookCode = {};
  UC.onPage = function (fn) {
    var key = String(fn);
    if (hookCode[key]) { return; }
    hookCode[key] = true;
    hooks.push(fn);
    if (ready) { runHook(fn); }
  };
  function runHooks() { hooks.slice().forEach(runHook); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { ready = true; runHooks(); });
  } else {
    ready = true;
  }

  // ------------------------------------------------------------------
  // When is in-place loading allowed?
  // ------------------------------------------------------------------
  var SKIP_PATH = /^\/(media|static|admin|logout|messages)(\/|$)/;
  function onAppPage() {
    var shell = document.querySelector('.app-shell');
    return !!(shell && document.querySelector('.app-main') && !shell.classList.contains('wa-page'));
  }
  function allowedUrl(u) {
    return u.origin === location.origin && !SKIP_PATH.test(u.pathname) && !/\.[a-z0-9]{2,5}$/i.test(u.pathname);
  }
  function linkUrl(a) {
    if (!a || a.hasAttribute('download') || a.closest('[data-no-soft]')) { return null; }
    var target = a.getAttribute('target');
    if (target && target !== '_self') { return null; }
    var href = a.getAttribute('href');
    if (!href || href.charAt(0) === '#' || /^[a-z][a-z0-9+.-]*:/i.test(href) && !/^https?:/i.test(href)) { return null; }
    var u;
    try { u = new URL(a.href, location.href); } catch (e) { return null; }
    return allowedUrl(u) ? u : null;
  }

  // ------------------------------------------------------------------
  // A thin progress bar while a page is on its way
  // ------------------------------------------------------------------
  var bar = null, barTimer = null;
  function barEl() {
    if (bar) { return bar; }
    var style = document.createElement('style');
    style.textContent =
      '.uc-progress{position:fixed;top:0;left:0;height:3px;width:0;z-index:3000;pointer-events:none;' +
      'background:var(--accent,#1d72f3);box-shadow:0 0 8px var(--accent,#1d72f3);opacity:1;' +
      'transition:width .25s ease,opacity .3s ease .1s;}';
    document.head.appendChild(style);
    bar = document.createElement('div');
    bar.className = 'uc-progress';
    document.body.appendChild(bar);
    return bar;
  }
  function progressStart() {
    clearTimeout(barTimer);
    barTimer = setTimeout(function () {
      var b = barEl();
      b.style.transition = 'none'; b.style.opacity = '1'; b.style.width = '0';
      void b.offsetWidth;
      b.style.transition = '';
      b.style.width = '70%';
    }, 120);
  }
  function progressDone() {
    clearTimeout(barTimer);
    if (!bar || bar.style.width === '0px' || bar.style.width === '0') { return; }
    bar.style.width = '100%';
    bar.style.opacity = '0';
    setTimeout(function () { if (bar) { bar.style.transition = 'none'; bar.style.width = '0'; } }, 450);
  }

  // ------------------------------------------------------------------
  // Scroll position (the middle column scrolls on wide screens, the
  // whole page on phones), remembered per history entry for Back.
  // ------------------------------------------------------------------
  function mainEl() { return document.querySelector('.app-main'); }
  function readScroll() {
    var m = mainEl();
    return { main: m ? m.scrollTop : 0, page: window.scrollY || 0 };
  }
  function writeScroll(s) {
    // Straight to the saved place, not animated (smooth scrolling is on everywhere: restyle.css).
    var m = mainEl(), root = document.documentElement;
    if (m) { m.style.scrollBehavior = 'auto'; m.scrollTop = s.main || 0; m.style.scrollBehavior = ''; }
    root.style.scrollBehavior = 'auto'; window.scrollTo(0, s.page || 0); root.style.scrollBehavior = '';
  }
  function rememberScroll() {
    try { history.replaceState({ uc: 1, scroll: readScroll() }, '', location.href); } catch (e) {}
  }
  if ('scrollRestoration' in history) { history.scrollRestoration = 'manual'; }
  // Keep the current entry's scroll up to date, so Back lands where you were.
  var scrollTimer = null;
  window.addEventListener('scroll', function () {
    if (!onAppPage()) { return; }
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(rememberScroll, 150);
  }, { capture: true, passive: true });

  // ------------------------------------------------------------------
  // Fetching (with a short-lived cache filled by hovering menu links)
  // ------------------------------------------------------------------
  var cache = {};
  var CACHE_MS = 10000;
  function fetchPage(url, signal) {
    return fetch(url, { credentials: 'same-origin', headers: { 'X-UC-Nav': '1' }, signal: signal })
      .then(function (r) {
        var type = r.headers.get('content-type') || '';
        if (type.indexOf('text/html') === -1) { var err = new Error('not html'); err.fallback = true; throw err; }
        return r.text().then(function (html) { return { html: html, url: r.url || url, status: r.status }; });
      });
  }
  function getPage(url, signal) {
    var hit = cache[url];
    delete cache[url];
    if (hit && Date.now() - hit.t < CACHE_MS) { return hit.p; }
    return fetchPage(url, signal);
  }
  var HOVER_LINKS = '.app-sidebar nav a, .app-mobile-drawer-nav a, .quicklinks-card a, .app-mobile-bottomnav a, .bs-tabs a';
  var hoverTimer = null;
  function warm(a) {
    if (!onAppPage() || !a.matches(HOVER_LINKS)) { return; }
    var u = linkUrl(a);
    // Notifications are marked read just by opening the page — never load it early.
    if (!u || /^\/notifications/.test(u.pathname) || u.href === location.href) { return; }
    var key = u.href;
    if (cache[key] && Date.now() - cache[key].t < CACHE_MS) { return; }
    var p = fetchPage(key);
    p.catch(function () { delete cache[key]; });
    cache[key] = { t: Date.now(), p: p };
  }
  document.addEventListener('mouseover', function (e) {
    var a = e.target.closest && e.target.closest('a[href]');
    clearTimeout(hoverTimer);
    if (a) { hoverTimer = setTimeout(function () { warm(a); }, 90); }
  }, { passive: true });
  document.addEventListener('touchstart', function (e) {
    var a = e.target.closest && e.target.closest('a[href]');
    if (a) { warm(a); }
  }, { passive: true });

  // ------------------------------------------------------------------
  // Visiting a page
  // ------------------------------------------------------------------
  var inflight = null;

  function visit(url, opts) {
    opts = opts || {};
    if (inflight) { inflight.abort(); }
    var ctrl = inflight = makeCtrl();
    if (!opts.restore) { rememberScroll(); }
    progressStart();
    var closing = overlaysClosed();

    var req = opts.method === 'POST'
      ? fetch(url, { method: 'POST', body: opts.body, credentials: 'same-origin', headers: { 'X-UC-Nav': '1' }, signal: ctrl.signal })
          .then(function (r) {
            var type = r.headers.get('content-type') || '';
            if (type.indexOf('text/html') === -1) { var err = new Error('not html'); err.posted = true; err.url = r.url; throw err; }
            return r.text().then(function (html) { return { html: html, url: r.url || url, status: r.status, redirected: r.redirected }; });
          })
      : getPage(url, ctrl.signal);

    return req.then(function (res) {
      return closing.then(function () { return res; });
    }).then(function (res) {
      if (ctrl !== inflight) { return; }
      inflight = null;
      var doc = new DOMParser().parseFromString(res.html, 'text/html');
      var shell = doc.querySelector('.app-shell');
      var finalUrl = new URL(res.url, location.href);
      var wanted = new URL(url, location.href);
      if (wanted.hash && !finalUrl.hash && finalUrl.pathname === wanted.pathname) { finalUrl.hash = wanted.hash; }

      // UniConnect was updated (its main scripts or styles changed): load
      // the page normally once, so this tab picks up the new versions.
      var updated = coreAssetsChanged(doc);
      if (updated || !shell || !doc.querySelector('.app-main') || shell.classList.contains('wa-page') || !allowedUrl(finalUrl)) {
        // Not an app page: show it the ordinary way.
        if (opts.method === 'POST' && !res.redirected) {
          // The form was already sent and answered with a page of its own —
          // show that answer rather than sending the form again.
          try { history.pushState(null, '', finalUrl.href); } catch (e) {}
          document.open(); document.write(res.html); document.close();
        } else {
          // (After a form, the page it sent us to — e.g. Messages — opens normally.)
          location.assign(finalUrl.href);
        }
        return;
      }
      return swap(doc, finalUrl.href, opts);
    }).catch(function (err) {
      document.querySelectorAll('.uc-region-loading').forEach(function (el) { el.classList.remove('uc-region-loading'); });
      if (err && err.name === 'AbortError') { return; }
      progressDone();
      if (ctrl === inflight) { inflight = null; }
      if (opts.method === 'POST') {
        if (err && err.posted && err.url) { location.assign(err.url); return; }
        if (typeof window.showToast === 'function') { window.showToast("Couldn't reach UniConnect. Please try again.", 'error'); }
        return;
      }
      location.assign(url);
    });
  }

  // The scripts every page shares (outside #ucPageScripts) and the shared
  // stylesheets: if the next page lists a different version, we're stale.
  function coreAssets(d) {
    var list = [];
    Array.prototype.forEach.call(d.querySelectorAll('script[src]'), function (s) {
      if (!s.closest('#ucPageScripts') && !s.closest('.app-main')) { list.push(new URL(s.getAttribute('src'), location.href).href); }
    });
    return list;
  }
  var coreNow = null;
  function coreAssetsChanged(doc) {
    if (!coreNow) { coreNow = coreAssets(document).filter(function (h) { return h.indexOf(location.origin + '/static/') === 0; }); }
    var next = coreAssets(doc).filter(function (h) { return h.indexOf(location.origin + '/static/') === 0; });
    return next.some(function (h) { return coreNow.indexOf(h) === -1; });
  }

  function stylesheetHrefs(d) {
    return Array.prototype.map.call(d.querySelectorAll('head link[rel="stylesheet"]'), function (l) {
      return new URL(l.getAttribute('href'), location.href).href;
    });
  }
  function loadStyles(doc) {
    var have = stylesheetHrefs(document);
    var waits = stylesheetHrefs(doc).filter(function (h) { return have.indexOf(h) === -1; }).map(function (href) {
      return new Promise(function (resolve) {
        var link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = href;
        link.onload = link.onerror = function () { resolve(); };
        document.head.appendChild(link);
        setTimeout(resolve, 3000);
      });
    });
    return Promise.all(waits);
  }
  function dropOldStyles(doc) {
    var keep = stylesheetHrefs(doc);
    Array.prototype.forEach.call(document.querySelectorAll('head link[rel="stylesheet"]'), function (l) {
      if (keep.indexOf(new URL(l.getAttribute('href'), location.href).href) === -1) { l.remove(); }
    });
  }

  // Menu highlight + badges, without touching the sidebar's own elements
  // (other code keeps references to them).
  function pairUp(sel, doc) {
    var shellNow = document.querySelector('.app-shell');
    var shellNew = doc.querySelector('.app-shell');
    function list(root) {
      return Array.prototype.filter.call(root.querySelectorAll(sel), function (el) { return !el.closest('.app-main'); });
    }
    var a = list(shellNow), b = list(shellNew);
    return a.length === b.length ? a.map(function (el, i) { return [el, b[i]]; }) : [];
  }
  function syncChrome(doc) {
    pairUp('a.app-nav-link, a.app-mobile-bottomnav-link', doc).forEach(function (p) {
      p[0].className = p[1].className;
      var iNow = p[0].querySelectorAll('i.bi'), iNew = p[1].querySelectorAll('i.bi');
      for (var i = 0; i < Math.min(iNow.length, iNew.length); i++) { iNow[i].className = iNew[i].className; }
    });
    pairUp('.js-notif-badge, .js-chat-sidebar-badge, .js-notif-dot', doc).forEach(function (p) {
      p[0].hidden = p[1].hasAttribute('hidden');
      if (!p[0].children.length) { p[0].textContent = p[1].textContent; }
      if (p[1].hasAttribute('aria-label')) { p[0].setAttribute('aria-label', p[1].getAttribute('aria-label')); }
    });
    // Home's Upcoming card in the right sidebar: shown on Home only, so copy
    // the slot (empty on other pages). Its View All is handled by a document
    // click listener, so plain copying is enough.
    pairUp('.js-upcoming-slot', doc).forEach(function (p) { p[0].innerHTML = p[1].innerHTML; });
    // The quicklinks (cart count) carry no behaviour of their own: just copy them.
    pairUp('.quicklinks-card', doc).forEach(function (p) { p[0].innerHTML = p[1].innerHTML; });
    // The bottom bar's "+" and its menu: highlight and cart badge/dot.
    pairUp('.app-mobile-bottomnav-more-btn, .app-mobile-bottomnav-more-menu a', doc).forEach(function (p) {
      p[0].className = p[1].className;
      p[0].innerHTML = p[1].innerHTML;
    });
    var cartNow = document.querySelector('.app-mobile-bottomnav a[href*="marketplace"]');
    var cartNew = doc.querySelector('.app-mobile-bottomnav a[href*="marketplace"]');
    if (cartNow && cartNew) { cartNow.innerHTML = cartNew.innerHTML; }
  }

  function closeOverlays() {
    ['appDrawer', 'appDrawerBackdrop', 'bottomNavMoreMenu'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) { el.classList.remove('open'); }
    });
    var pop = document.getElementById('notifPopup');
    if (pop) { pop.hidden = true; }
    if (window.UniMediaViewer && typeof window.UniMediaViewer.close === 'function') {
      try { window.UniMediaViewer.close(); } catch (e) {}
    }
    if (window.bootstrap && window.bootstrap.Modal) {
      document.querySelectorAll('.modal.show').forEach(function (m) {
        try { window.bootstrap.Modal.getOrCreateInstance(m).hide(); } catch (e) {}
      });
    }
    document.body.style.overflow = '';
  }
  // Start closing pop-ups as soon as a page is requested, and let them
  // finish (some animate a photo back into its post) before the swap.
  function overlaysClosed() {
    closeOverlays();
    return new Promise(function (resolve) {
      var t0 = Date.now();
      (function check() {
        if (!document.querySelector('.modal.show, .modal.fade.show') || Date.now() - t0 > 1200) { resolve(); return; }
        setTimeout(check, 40);
      })();
    });
  }

  // A pop-up that lived in the old page is gone now, so Bootstrap never
  // finishes closing it: clear what it leaves on <body> (dark backdrop,
  // scroll lock) unless another pop-up is still open.
  function tidyModals() {
    if (document.querySelector('.modal.show')) { return; }
    document.querySelectorAll('.modal-backdrop').forEach(function (b) { b.remove(); });
    document.body.classList.remove('modal-open');
    document.body.style.removeProperty('padding-right');
    document.body.style.removeProperty('overflow');
  }

  function showMessages(doc) {
    if (typeof window.showToast !== 'function') { return; }
    doc.querySelectorAll('#toastStack .toast-message').forEach(function (t) {
      var m = /toast-(\w+)/.exec(t.className.replace('toast-message', ''));
      var span = t.querySelector('span');
      window.showToast(span ? span.textContent.trim() : t.textContent.trim(), m ? m[1] : 'info');
    });
    // Class reminders made while loading this page (courses/reminders.py).
    var pops = doc.querySelectorAll('#toastStack .class-reminder-pop');
    if (pops.length) {
      var stack = document.getElementById('toastStack');
      if (!stack) { stack = document.createElement('div'); stack.className = 'toast-stack'; stack.id = 'toastStack'; document.body.appendChild(stack); }
      pops.forEach(function (p) { stack.appendChild(document.importNode(p, true)); });
    }
  }

  // Page scripts: files load once per visit to the app; inline code runs
  // every time its page is shown.
  var loadedSrc = {};
  function noteLoadedScripts() {
    // Everything the browser loaded itself (including page scripts below this file).
    Array.prototype.forEach.call(document.scripts, function (s) { if (s.src) { loadedSrc[s.src] = true; } });
  }
  function scriptHolder() {
    var h = document.getElementById('ucPageScripts');
    if (!h) { h = document.createElement('div'); h.id = 'ucPageScripts'; document.body.appendChild(h); }
    return h;
  }
  function isCode(s) {
    var t = (s.getAttribute('type') || '').trim().toLowerCase();
    return !t || t === 'text/javascript' || t === 'application/javascript' || t === 'module';
  }
  function collectScripts(doc) {
    return Array.prototype.filter.call(doc.querySelectorAll('.app-main script, #ucPageScripts script'), isCode)
      .map(function (s) {
        return s.hasAttribute('src')
          ? { src: new URL(s.getAttribute('src'), location.href).href }
          : { code: s.textContent };
      });
  }
  function runScripts(list) {
    noteLoadedScripts();
    var holder = scriptHolder();
    return list.reduce(function (chain, item) {
      return chain.then(function () {
        if (item.src) {
          if (loadedSrc[item.src]) { return; }
          return new Promise(function (resolve) {
            var el = document.createElement('script');
            el.src = item.src;
            el.onload = el.onerror = function () { loadedSrc[item.src] = true; resolve(); };
            holder.appendChild(el);
          });
        }
        var el = document.createElement('script');
        el.textContent = item.code;
        holder.appendChild(el);
        el.remove();
      });
    }, Promise.resolve());
  }

  // Part-of-page swaps (e.g. the profile tabs): data-soft-swap on a link or
  // one of its parents lists the parts to replace. Each part is matched by
  // position (the profile has a desktop and a phone copy of each).
  function regionPairs(doc, selectors) {
    var main = mainEl(), newMain = doc.querySelector('.app-main');
    var pairs = [];
    var okay = selectors.split(',').every(function (sel) {
      sel = sel.trim();
      var a = main.querySelectorAll(sel), b = newMain.querySelectorAll(sel);
      if (!a.length || a.length !== b.length) { return false; }
      for (var i = 0; i < a.length; i++) { pairs.push([a[i], b[i]]); }
      return true;
    });
    return okay ? pairs : null;
  }
  var regionStyle = document.createElement('style');
  regionStyle.textContent =
    // Dimming only starts if loading takes a moment (delay), so quick
    // switches don't flicker at all.
    '.uc-region-loading{opacity:.5;transition:opacity .2s ease .12s;pointer-events:none;}' +
    '@media (prefers-reduced-motion:reduce){.uc-region-loading{transition:none;}}';
  document.head.appendChild(regionStyle);

  function swapRegions(doc, url, pairs, opts) {
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    pairs.forEach(function (p) {
      p[1].querySelectorAll('script').forEach(function (s) { if (isCode(s)) { s.remove(); } });
      // The new list starts exactly as faded as the old one was at this
      // moment and brightens from there — one continuous fade, no flash.
      var from = parseFloat(getComputedStyle(p[0]).opacity);
      if (isNaN(from)) { from = 1; }
      var fresh = document.adoptNode(p[1]);
      p[0].replaceWith(fresh);
      if (reduce || from >= 0.99) { return; }
      fresh.style.opacity = String(from);
      void fresh.offsetWidth;
      fresh.style.transition = 'opacity .22s cubic-bezier(.2,.7,.3,1)';
      fresh.style.opacity = '1';
      setTimeout(function () { fresh.style.removeProperty('opacity'); fresh.style.removeProperty('transition'); }, 300);
    });
    document.title = doc.title;
    try { history.pushState({ uc: 1, scroll: opts.keepScroll || readScroll() }, '', url); } catch (e) {}
    if (opts.keepScroll) { writeScroll(opts.keepScroll); }
    showMessages(doc);
    progressDone();
    document.dispatchEvent(new CustomEvent('uc:page', { detail: { url: url, partial: true } }));
  }

  function swap(doc, url, opts) {
    if (opts.regions) {
      var pairs = regionPairs(doc, opts.regions);
      if (pairs) { swapRegions(doc, url, pairs, opts); return Promise.resolve(); }
      // The page changed shape — swap the whole middle column instead.
    }
    var scripts = collectScripts(doc);
    return loadStyles(doc).then(function () {
      function apply() {
        closeOverlays();
        pageCtrl.abort();
        pageCtrl = makeCtrl();

        var shell = document.querySelector('.app-shell');
        var main = mainEl();
        var newShell = doc.querySelector('.app-shell');
        var newMain = doc.querySelector('.app-main');
        shell.className = newShell.className;
        main.className = newMain.className;
        // Scripts inside the new content run below, not as they're inserted.
        newMain.querySelectorAll('script').forEach(function (s) { if (isCode(s)) { s.remove(); } });
        main.replaceChildren.apply(main, Array.prototype.slice.call(newMain.childNodes).map(function (n) { return document.adoptNode(n); }));

        syncChrome(doc);
        document.title = doc.title;

        var state = { uc: 1, scroll: { main: 0, page: 0 } };
        if (opts.restore) {
          try { history.replaceState({ uc: 1, scroll: opts.restore }, '', url); } catch (e) {}
        } else if (url === location.href || opts.replace) {
          try { history.replaceState(state, '', url); } catch (e) {}
        } else {
          try { history.pushState(state, '', url); } catch (e) {}
        }

        if (opts.restore) {
          writeScroll(opts.restore);
        } else if (opts.keepScroll) {
          writeScroll(opts.keepScroll);
        } else {
          writeScroll({ main: 0, page: 0 });
          var hash = new URL(url).hash;
          var target = hash && document.getElementById(decodeURIComponent(hash.slice(1)));
          if (target) { target.scrollIntoView(); }
        }

        showMessages(doc);
        dropOldStyles(doc);
        tidyModals();
      }

      var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      var done;
      if (document.startViewTransition && !reduce) {
        var vt = document.startViewTransition(apply);
        done = vt.updateCallbackDone;
      } else {
        apply();
        done = Promise.resolve();
      }
      return done.then(function () {
        // Existing page code first, then files/inline code the new page brings
        // (a newly loaded file sets itself up when it registers).
        runHooks();
        return runScripts(scripts);
      }).then(function () {
        progressDone();
        document.dispatchEvent(new CustomEvent('uc:page', { detail: { url: url } }));
      });
    });
  }

  // ------------------------------------------------------------------
  // Clicks, form submits, Back / Forward
  // ------------------------------------------------------------------
  // Listening on window (the last stop) means any handler that already
  // took care of a click/submit (preventDefault) is left alone.
  window.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return; }
    if (!onAppPage()) { return; }
    var a = e.target.closest && e.target.closest('a[href]');
    var u = linkUrl(a);
    if (!u) { return; }
    if (u.pathname === location.pathname && u.search === location.search && u.hash) { return; } // same-page anchor
    e.preventDefault();
    var group = a.closest('[data-soft-swap]');
    if (group) {
      // Swap just part of the page (tabs): highlight the tab now, dim the list while it loads.
      var href = a.getAttribute('href');
      document.querySelectorAll('[data-soft-swap] a[href]').forEach(function (t) { t.classList.toggle('active', t.getAttribute('href') === href); });
      var sels = group.getAttribute('data-soft-swap');
      sels.split(',').forEach(function (sel) {
        document.querySelectorAll('.app-main ' + sel.trim()).forEach(function (el) { if (!el.matches('[data-soft-swap]')) { el.classList.add('uc-region-loading'); } });
      });
      visit(u.href, { regions: sels, keepScroll: readScroll() });
      return;
    }
    visit(u.href);
  });

  window.addEventListener('submit', function (e) {
    if (e.defaultPrevented || !onAppPage()) { return; }
    var form = e.target;
    if (!(form instanceof HTMLFormElement) || !form.closest('.app-main') || form.closest('[data-no-soft]')) { return; }
    var sub = e.submitter || null;
    var target = (sub && sub.getAttribute('formtarget')) || form.getAttribute('target');
    if (target && target !== '_self') { return; }
    var method = ((sub && sub.getAttribute('formmethod')) || form.getAttribute('method') || 'get').toLowerCase();
    if (method !== 'get' && method !== 'post') { return; }
    var action = new URL((sub && sub.getAttribute('formaction')) || form.getAttribute('action') || location.href, location.href);
    if (!allowedUrl(action)) { return; }
    e.preventDefault();
    var data;
    try { data = new FormData(form, sub); } catch (err) {
      data = new FormData(form);
      if (sub && sub.name) { data.append(sub.name, sub.value); }
    }
    if (method === 'get') {
      var params = new URLSearchParams();
      data.forEach(function (v, k) { if (typeof v === 'string') { params.append(k, v); } });
      action.search = params.toString();
      action.hash = '';
      visit(action.href);
    } else {
      visit(action.href, { method: 'POST', body: data });
    }
  });

  window.addEventListener('popstate', function (e) {
    if (!onAppPage()) { location.reload(); return; }
    var s = e.state && e.state.scroll;
    visit(location.href, { restore: s || { main: 0, page: 0 } });
  });

  UC.navigate = function (url) {
    var u = new URL(url, location.href);
    if (onAppPage() && allowedUrl(u)) { visit(u.href); } else { location.assign(u.href); }
  };
  UC.reload = function () {
    if (onAppPage() && allowedUrl(new URL(location.href))) { visit(location.href, { replace: true, keepScroll: readScroll() }); }
    else { location.reload(); }
  };

  if (onAppPage()) { rememberScroll(); }
})();

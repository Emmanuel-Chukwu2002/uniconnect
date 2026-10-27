/* =====================================================================
   UniConnect Messages — shared helpers (window.WA)
   Loaded first; every other chat/*.js file uses these.
   ===================================================================== */
(function () {
  'use strict';
  var WA = window.WA = window.WA || {};
  var meEl = document.getElementById('waMe');
  WA.me = meEl ? JSON.parse(meEl.textContent) : null;

  // ---------------- tiny event bus ----------------
  var handlers = {};
  WA.on = function (type, fn) { (handlers[type] = handlers[type] || []).push(fn); };
  WA.emit = function (type, data) {
    (handlers[type] || []).forEach(function (fn) {
      try { fn(data); } catch (err) { if (window.console) console.error('[WA]', type, err); }
    });
  };

  // ---------------- HTTP ----------------
  WA.csrf = function () {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  };
  WA.post = function (url, data) {
    var body = data instanceof FormData ? data : new URLSearchParams(data || {});
    return fetch(url, {
      method: 'POST', body: body, credentials: 'same-origin',
      headers: { 'X-CSRFToken': WA.csrf(), 'X-Requested-With': 'XMLHttpRequest' },
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (json) {
        if (!r.ok) { throw new Error(json.error || 'Something went wrong.'); }
        return json;
      });
    });
  };
  WA.getJSON = function (url) {
    return fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { if (!r.ok) { throw new Error('Request failed'); } return r.json(); });
  };
  WA.toast = function (text, tag) {
    if (typeof window.showToast === 'function') { window.showToast(text, tag || 'success'); }
  };

  // ---------------- DOM ----------------
  WA.el = function (tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  };
  WA.icon = function (name, cls) { return WA.el('i', 'bi ' + name + (cls ? ' ' + cls : '')); };

  /** Text with links made clickable — built from text nodes, never innerHTML,
   *  so nothing anyone types can run as HTML. */
  WA.richText = function (text) {
    var frag = document.createDocumentFragment();
    var re = /\bhttps?:\/\/[^\s<>"']+/gi;
    var last = 0, m;
    text = text || '';
    while ((m = re.exec(text))) {
      if (m.index > last) { frag.appendChild(document.createTextNode(text.slice(last, m.index))); }
      var url = m[0].replace(/[.,!?)]+$/, '');
      var a = WA.el('a', 'wa-link', url);
      a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
      frag.appendChild(a);
      last = m.index + url.length;
      re.lastIndex = last;
    }
    if (last < text.length) { frag.appendChild(document.createTextNode(text.slice(last))); }
    return frag;
  };

  WA.avatar = function (p, size) {
    var a = WA.el('span', 'wa-avatar');
    a.style.setProperty('--size', (size || 40) + 'px');
    if (p && p.photo) { a.style.backgroundImage = 'url("' + p.photo.replace(/"/g, '%22') + '")'; }
    else {
      a.style.backgroundColor = (p && p.colour) || '#8696a0';
      a.textContent = (p && p.initials) || '?';
    }
    return a;
  };

  // ---------------- time ----------------
  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function sameDay(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
  function dayDiff(d) {
    var a = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    var now = new Date(), b = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.round((b - a) / 86400000);
  }
  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  var DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

  WA.clock = function (d) {
    var h = d.getHours(), ap = h >= 12 ? 'pm' : 'am';
    h = h % 12 || 12;
    return h + ':' + pad(d.getMinutes()) + ' ' + ap;
  };
  WA.shortDate = function (d) { return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + '/' + d.getFullYear(); };
  WA.dayLabel = function (d) {
    var diff = dayDiff(d);
    if (diff === 0) { return 'Today'; }
    if (diff === 1) { return 'Yesterday'; }
    if (diff < 7) { return DAYS[d.getDay()]; }
    return d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear();
  };
  WA.sameDay = sameDay;

  WA.formatTime = function (iso, format) {
    if (!iso) { return ''; }
    var d = new Date(iso);
    if (isNaN(d)) { return ''; }
    var diff = dayDiff(d);
    switch (format) {
      case 'clock': return WA.clock(d);
      case 'list':
        if (diff === 0) { return WA.clock(d); }
        if (diff === 1) { return 'Yesterday'; }
        return WA.shortDate(d);
      case 'ago': {
        var mins = Math.round((Date.now() - d) / 60000);
        if (mins < 1) { return 'Just now'; }
        if (mins < 60) { return mins + (mins === 1 ? ' minute ago' : ' minutes ago'); }
        return (diff === 0 ? 'Today, ' : 'Yesterday, ') + WA.clock(d);
      }
      case 'call':
        if (diff === 0) { return 'Today, ' + WA.clock(d); }
        if (diff === 1) { return 'Yesterday, ' + WA.clock(d); }
        return d.getDate() + ' ' + MONTHS[d.getMonth()] + ', ' + WA.clock(d);
      case 'lastseen':
        if (diff === 0) { return 'last seen today at ' + WA.clock(d); }
        if (diff === 1) { return 'last seen yesterday at ' + WA.clock(d); }
        return 'last seen ' + WA.shortDate(d);
      default: return WA.clock(d);
    }
  };
  /** Re-format every <time class="js-wa-time" data-ts data-format> in the
   *  viewer's own time zone. */
  WA.refreshTimes = function (root) {
    (root || document).querySelectorAll('.js-wa-time[data-ts]').forEach(function (t) {
      var text = WA.formatTime(t.getAttribute('data-ts'), t.getAttribute('data-format') || 'list');
      if (text) { t.textContent = text; }
    });
  };

  WA.formatBytes = function (n) {
    if (!n) { return ''; }
    if (n < 1024) { return n + ' B'; }
    if (n < 1048576) { return Math.round(n / 1024) + ' kB'; }
    return (n / 1048576).toFixed(1) + ' MB';
  };
  WA.formatDuration = function (s) {
    s = Math.max(0, Math.round(s || 0));
    return Math.floor(s / 60) + ':' + pad(s % 60);
  };

  // ---------------- a short, original notification tone ----------------
  var audioCtx = null;
  WA.beep = function () {
    var app = document.getElementById('waApp');
    if (!app || app.getAttribute('data-sounds') !== '1') { return; }
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      var o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.type = 'sine'; o.frequency.value = 880;
      g.gain.setValueAtTime(0.0001, audioCtx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.12, audioCtx.currentTime + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.25);
      o.connect(g); g.connect(audioCtx.destination);
      o.start(); o.stop(audioCtx.currentTime + 0.26);
    } catch (e) { /* no audio available */ }
  };

  WA.uid = function () { return 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8); };
  WA.isWide = function () { return window.matchMedia('(min-width: 769px)').matches; };
  WA.currentConversation = function () {
    var app = document.getElementById('waApp');
    return app ? parseInt(app.getAttribute('data-conversation') || '0', 10) || null : null;
  };

  document.addEventListener('DOMContentLoaded', function () { WA.refreshTimes(); });
  if (document.readyState !== 'loading') { WA.refreshTimes(); }
})();

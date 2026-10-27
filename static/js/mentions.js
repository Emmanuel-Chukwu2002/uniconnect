/* ---------------------------------------------------------------
   @mention suggestions. Typing "@" (and then a few letters) in a post,
   quote, comment or reply box shows up to 6 classmates
   (/people/mention/?q=, feed/people.py mention_search). Pick one with a
   tap, or with the arrow keys and Enter/Tab, and "@username " goes into
   the box. Esc closes the list. Styles: restyle.css ("@mentions").
   Works on boxes added later too (comment threads, soft navigation),
   because it listens on the whole document.

   Group chats (chat/mentions.py): a box inside [data-mention-url] asks
   that address instead, so only people in the chat are listed. Direct
   chats have no @ list. UCChatMentions.decorate() shows "@username" in a
   chat message as "@Their Name" (highlighted more when it's you).
   --------------------------------------------------------------- */
(function () {
  'use strict';
  var BOXES = '.compose-textarea, .js-quote-text, .js-comment-composer-input, .comment-reply-input, .comment-edit-textarea, .js-sg-body, .js-gc-input, .js-wa-input';
  var CHAT_BOXES = '.js-gc-input, .js-wa-input';
  var TOKEN = /(^|[^\w@])@([\w.\-]{0,30})$/;   // "@" at the start or after a space/punctuation, then the name so far

  var list = null, field = null, items = [], active = 0, start = -1, timer = null, lastQ = null, req = 0;
  var cache = {};

  function el() {
    if (list) { return list; }
    list = document.createElement('div');
    list.className = 'mention-list';
    list.setAttribute('role', 'listbox');
    list.hidden = true;
    document.body.appendChild(list);
    // mousedown (not click) so the box doesn't lose focus first
    list.addEventListener('mousedown', function (e) {
      var row = e.target.closest('.mention-item');
      if (!row) { return; }
      e.preventDefault();
      pick(+row.dataset.i);
    });
    return list;
  }

  function close() {
    if (list) { list.hidden = true; }
    field = null; items = []; start = -1; lastQ = null;
  }

  function place() {
    var r = field.getBoundingClientRect();
    var w = Math.min(Math.max(r.width, 260), 360, window.innerWidth - 16);
    var left = Math.min(Math.max(8, r.left), window.innerWidth - w - 8);
    list.style.width = w + 'px';
    list.style.left = left + 'px';
    var below = window.innerHeight - r.bottom;
    var h = list.offsetHeight || 260;
    if (below < h + 12 && r.top > below) {
      list.style.top = Math.max(8, r.top - h - 6) + 'px';
    } else {
      list.style.top = (r.bottom + 6) + 'px';
    }
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; });
  }

  function render() {
    var box = el();
    if (!items.length) { box.hidden = true; return; }
    box.innerHTML = items.map(function (p, i) {
      var ava = p.photo ? '<span class="mention-ava" style="background-image:url(\'' + esc(p.photo) + '\')"></span>'
                        : '<span class="mention-ava"><i class="bi bi-person-fill"></i></span>';
      return '<div class="mention-item' + (i === active ? ' is-on' : '') + '" role="option" aria-selected="' + (i === active) + '" data-i="' + i + '">' +
        ava + '<span class="mention-text"><b>' + esc(p.name) + (p.verified ? ' <i class="bi bi-patch-check-fill"></i>' : '') + '</b>' +
        '<small>@' + esc(p.username) + (p.detail ? ' · ' + esc(p.detail) : '') + '</small></span></div>';
    }).join('');
    box.hidden = false;
    place();
  }

  function source(box) {
    var holder = box.closest('[data-mention-url]');
    if (holder) { return holder.getAttribute('data-mention-url'); }
    return box.matches(CHAT_BOXES) ? '' : '/people/mention/';     // direct chats: no @ list
  }

  function lookup(q) {
    var url = source(field);
    if (!url) { close(); return; }
    var key = url + '|' + q;
    if (cache[key]) { items = cache[key]; active = 0; render(); return; }
    var mine = ++req;
    fetch(url + '?q=' + encodeURIComponent(q), { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { people: [] }; })
      .then(function (data) {
        cache[key] = data.people || [];
        if (mine !== req || !field) { return; }     // a newer search is on its way, or the list was closed
        items = cache[key]; active = 0; render();
      })
      .catch(function () {});
  }

  function check(box) {
    var caret = box.selectionStart;
    if (caret == null || caret !== box.selectionEnd) { close(); return; }
    var m = TOKEN.exec(box.value.slice(0, caret));
    if (!m) { close(); return; }
    field = box;
    start = caret - m[2].length - 1;          // where the "@" is
    var q = m[2];
    if (q === lastQ && list && !list.hidden) { return; }
    lastQ = q;
    clearTimeout(timer);
    timer = setTimeout(function () { lookup(q); }, q ? 150 : 0);
  }

  function pick(i) {
    var p = items[i];
    if (!p || !field) { return; }
    var box = field, caret = box.selectionStart, value = box.value;
    var insert = '@' + p.username + ' ';
    box.value = value.slice(0, start) + insert + value.slice(caret).replace(/^\s/, '');
    var pos = start + insert.length;
    box.setSelectionRange(pos, pos);
    close();
    box.focus();
    box.dispatchEvent(new Event('input', { bubbles: true }));   // counters, Post button, auto-grow
  }

  document.addEventListener('input', function (e) {
    if (e.target.matches && e.target.matches(BOXES)) { check(e.target); }
  });
  document.addEventListener('click', function (e) {
    if (e.target.matches && e.target.matches(BOXES)) { check(e.target); return; }
    if (list && !list.contains(e.target)) { close(); }
  });
  document.addEventListener('focusout', function (e) {
    if (field && e.target === field) { setTimeout(function () { if (document.activeElement !== field) { close(); } }, 150); }
  });
  // Capture phase: runs before the boxes' own Enter handlers (e.g. Enter
  // sends a reply), so Enter picks the person while the list is open.
  document.addEventListener('keydown', function (e) {
    if (!field || e.target !== field || !list || list.hidden || !items.length) { return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      active = (active + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
      render();
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault(); e.stopPropagation();
      pick(active);
    } else if (e.key === 'Escape') {
      e.preventDefault(); e.stopPropagation();
      close();
    }
  }, true);
  window.addEventListener('resize', function () { if (field && list && !list.hidden) { place(); } });

  // ---------- @mentions shown in chat messages ----------
  // Turns "@username" in the text nodes of `node` into a link "@Name".
  function decorate(node, mentions, meId) {
    if (!node || !mentions || !mentions.length) { return; }
    var by = {};
    mentions.forEach(function (m) { by[m.username.toLowerCase()] = m; });
    var re = /(^|[^\w@])@([\w.\-]+)/g;
    var walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, null);
    var texts = [];
    while (walker.nextNode()) { if (!walker.currentNode.parentNode.closest('a')) { texts.push(walker.currentNode); } }
    texts.forEach(function (t) {
      var s = t.nodeValue, last = 0, m, frag = null;
      re.lastIndex = 0;
      while ((m = re.exec(s))) {
        var name = m[2].replace(/\.+$/, ''), p = by[name.toLowerCase()];
        if (!p) { continue; }
        frag = frag || document.createDocumentFragment();
        var at = m.index + m[1].length;
        frag.appendChild(document.createTextNode(s.slice(last, at)));
        var a = document.createElement('a');
        a.className = 'cm-mention' + (p.id === meId ? ' is-me' : '');
        a.href = p.url; a.textContent = '@' + p.name;
        a.title = '@' + p.username;
        frag.appendChild(a);
        last = at + 1 + name.length;
      }
      if (frag) { frag.appendChild(document.createTextNode(s.slice(last))); t.parentNode.replaceChild(frag, t); }
    });
  }
  function mentionsMe(msg, meId) { return !!(msg && msg.mentions && msg.mentions.some(function (m) { return m.id === meId; })); }
  window.UCChatMentions = { decorate: decorate, mentionsMe: mentionsMe };
  document.addEventListener('scroll', function () { if (field && list && !list.hidden) { place(); } }, true);
  document.addEventListener('uc:page', close);
})();

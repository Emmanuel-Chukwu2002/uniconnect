/* =====================================================================
   UniConnect Messages — the chat list (Chats tab)

   - search box and filter chips (All / Unread / Favourites / Groups)
   - keeps every row live from WebSocket events: last message preview,
     time, ticks, unread badge, "typing…", online dot, order
   - the green unread badges (bottom nav / rail / UniConnect sidebar)
   - acknowledges delivery of incoming messages (grey double tick)
   ===================================================================== */
(function () {
  'use strict';
  var WA = window.WA;
  if (!WA || !document.getElementById('waApp')) { return; }

  var filter = 'all';
  function initialFilter() {
    var on = document.querySelector('#waListPane .js-wa-chip.is-active');
    filter = on ? on.getAttribute('data-filter') : 'all';
  }
  initialFilter();
  var typingTimers = {};

  function rowsBox() { return document.querySelector('#waListPane .js-wa-rows'); }
  function rowFor(id) { return document.querySelector('#waListPane .js-wa-row[data-conversation="' + id + '"]'); }
  function isArchivedList() { var b = rowsBox(); return !!(b && b.hasAttribute('data-archived-list')); }

  // ---------------- search + chips ----------------
  // Like WhatsApp: typing in the search box filters your chats here and
  // asks the server for people you haven't messaged yet (Contacts) and
  // messages containing the words (Messages, chat/views.py search).
  var searchTimer = null, searchSeq = 0, serverCount = 0;

  function searchText() { return ((document.querySelector('#waListPane .js-wa-search') || {}).value || '').trim(); }

  function applyFilter() {
    var box = rowsBox();
    if (!box) { return; }
    var q = searchText().toLowerCase();
    var searching = !!q;
    var shown = 0;
    box.querySelectorAll('.js-wa-row').forEach(function (row) {
      var ok = true;
      var isRequest = row.getAttribute('data-request') === '1';   // message requests (chat/requests.py)
      if (!searching) {
        if (filter === 'requests') { ok = isRequest; }
        else if (isRequest) { ok = false; }
        else if (filter === 'unread') { ok = row.classList.contains('is-unread'); }
        else if (filter === 'favourite') { ok = row.getAttribute('data-favourite') === '1'; }
        else if (filter === 'group') { ok = row.getAttribute('data-group') === '1'; }
      } else {
        var text = row.getAttribute('data-name') + ' ' + ((row.querySelector('.wa-preview-text') || {}).textContent || '');
        ok = q.split(/\s+/).every(function (w) { return text.toLowerCase().indexOf(w) > -1; });
      }
      row.hidden = !ok;
      if (ok) { shown++; }
    });
    // While searching, the chips and Archived step aside and the list gets headings.
    var pane = document.getElementById('waListPane');
    pane.classList.toggle('is-searching', searching);
    var heading = pane.querySelector('.js-wa-chats-heading');
    if (heading) { heading.hidden = !searching || !shown; }
    var results = pane.querySelector('.js-wa-search-results');
    if (results && !searching) { results.hidden = true; results.innerHTML = ''; serverCount = 0; }

    var empty = pane.querySelector('.js-wa-empty');
    if (empty) {
      empty.hidden = shown > 0 || (searching && serverCount > 0) || (searching && searchTimer !== null);
      var t = empty.querySelector('.js-wa-empty-text');
      if (t && (box.children.length || searching)) {
        t.textContent = searching ? 'No chats or messages found for “' + searchText() + '”.'
          : filter === 'requests' ? 'No message requests. When someone you don\'t follow messages you, it waits here until you accept it.'
          : filter === 'unread' ? 'No unread chats.' : filter === 'favourite' ? 'No favourites yet. Open a chat, tap ⋮ and choose "Add to favourites".' : filter === 'group' ? 'No groups yet.' : 'No chats yet.';
      }
    }
  }

  function searchServer() {
    var q = searchText();
    var results = document.querySelector('#waListPane .js-wa-search-results');
    if (!results) { return; }
    clearTimeout(searchTimer);
    if (!q) { searchTimer = null; applyFilter(); return; }
    var seq = ++searchSeq;
    searchTimer = setTimeout(function () {
      WA.getJSON('/messages/search/?q=' + encodeURIComponent(q)).then(function (res) {
        if (seq !== searchSeq || searchText() !== q) { return; }
        searchTimer = null;
        serverCount = res.count || 0;
        results.innerHTML = res.html || '';
        results.hidden = !serverCount;
        WA.refreshTimes(results);
        applyFilter();
      }).catch(function () { searchTimer = null; applyFilter(); });
    }, 220);
  }

  document.addEventListener('input', function (e) {
    if (e.target.matches('#waListPane .js-wa-search')) { applyFilter(); searchServer(); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && e.target.matches('#waListPane .js-wa-search') && e.target.value) {
      e.target.value = ''; applyFilter(); searchServer();
    }
  });
  document.addEventListener('click', function (e) {
    var contact = e.target.closest('#waListPane .js-wa-search-contact');
    if (contact) {
      WA.post('/messages/start/' + contact.getAttribute('data-user-id') + '/', {})
        .then(function (res) { WA.navigate(res.url); })
        .catch(function (err) { WA.toast(err.message, 'error'); });
      return;
    }
    var req = e.target.closest('.js-wa-request');
    if (req) {
      // Accept / Delete on a message request (chat/views.py chat_action).
      var bar = req.closest('.js-wa-request-bar'), id = bar.getAttribute('data-conversation'), action = req.getAttribute('data-action');
      bar.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
      WA.post('/messages/c/' + id + '/action/', { action: action }).then(function () {
        var r = rowFor(id);
        if (action === 'accept_request') {
          bar.remove();
          if (r) { r.setAttribute('data-request', '0'); }
          WA.toast('Accepted — it\'s in your chats now.');
        } else {
          if (r) { r.remove(); }
          WA.toast('Message request deleted.');
          WA.navigate('/messages/?filter=requests');
        }
        refreshUnreadChip(); applyFilter();
      }).catch(function (err) {
        bar.querySelectorAll('button').forEach(function (b) { b.disabled = false; });
        WA.toast(err.message, 'error');
      });
      return;
    }
    var chip = e.target.closest('#waListPane .js-wa-chip');
    if (!chip) { return; }
    filter = chip.getAttribute('data-filter');
    document.querySelectorAll('#waListPane .js-wa-chip').forEach(function (c) { c.classList.toggle('is-active', c === chip); });
    applyFilter();
  });

  // ---------------- open conversation highlight ----------------
  function markActive() {
    var current = WA.currentConversation();
    document.querySelectorAll('#waListPane .js-wa-row').forEach(function (row) {
      row.classList.toggle('is-active', parseInt(row.getAttribute('data-conversation'), 10) === current);
    });
  }

  // ---------------- badges ----------------
  function setUnreadTotal(n) {
    n = Math.max(0, n || 0);
    document.querySelectorAll('.js-wa-chats-badge').forEach(function (b) { b.textContent = n; b.hidden = n === 0; });
    document.querySelectorAll('.js-chat-sidebar-badge').forEach(function (b) { b.textContent = n > 99 ? '99+' : n; b.hidden = n === 0; });
  }
  function refreshUnreadChip() {
    var chip = document.querySelector('#waListPane .js-wa-unread-chip');
    if (!chip) { return; }
    var n = document.querySelectorAll('#waListPane .js-wa-row.is-unread:not([data-request="1"])').length;
    chip.textContent = n ? n : '';
    var rc = document.querySelector('#waListPane .js-wa-requests-chip');
    if (rc) { var r = document.querySelectorAll('#waListPane .js-wa-row[data-request="1"]').length; rc.textContent = r ? r : ''; }
  }
  function setRowUnread(row, count, marked) {
    var badge = row.querySelector('.js-wa-unread');
    var on = count > 0 || marked;
    row.classList.toggle('is-unread', on);
    badge.hidden = !on;
    badge.textContent = count > 0 ? count : '';
    badge.setAttribute('data-count', count);
    refreshUnreadChip();
  }

  // ---------------- previews ----------------
  function previewFor(msg) {
    var mine = msg.sender && msg.sender.id === WA.me.id;
    var group = document.querySelector('#waListPane .js-wa-row[data-conversation="' + msg.conversation + '"][data-group="1"]');
    var wrap = WA.el('span', 'wa-preview-content');
    if (mine && msg.kind !== 'system') {
      var tick = WA.icon(msg.status === 'sent' ? 'bi-check2' : 'bi-check2-all', 'wa-tick wa-tick-' + msg.status);
      tick.setAttribute('data-message-status', '');
      wrap.appendChild(tick);
    }
    if (group && !mine && msg.sender && msg.kind !== 'system') {
      wrap.appendChild(WA.el('span', 'wa-preview-prefix', '~ ' + (msg.sender.name.split(' ')[0]) + ': '));
    }
    var icon = '', text = msg.content;
    if (msg.is_deleted) { icon = 'bi-slash-circle'; text = mine ? 'You deleted this message' : 'This message was deleted'; }
    else if (msg.kind === 'image') { icon = 'bi-camera-fill'; text = msg.content || 'Photo'; }
    else if (msg.kind === 'file') { icon = 'bi-file-earmark-fill'; text = (msg.attachment && msg.attachment.name) || 'Document'; }
    else if (msg.kind === 'audio') { icon = 'bi-mic-fill'; text = 'Voice message (' + WA.formatDuration(msg.duration) + ')'; }
    if (icon) { wrap.appendChild(WA.icon(icon, 'wa-preview-icon')); }
    wrap.appendChild(WA.el('span', 'wa-preview-text', (text || '').replace(/\s+/g, ' ').slice(0, 120)));
    return wrap;
  }

  function moveToTop(row) {
    var box = rowsBox();
    if (!box) { return; }
    if (row.getAttribute('data-pinned') === '1') { box.insertBefore(row, box.firstChild); return; }
    var firstUnpinned = Array.prototype.find.call(box.querySelectorAll('.js-wa-row'), function (r) {
      return r !== row && r.getAttribute('data-pinned') !== '1';
    });
    box.insertBefore(row, firstUnpinned || null);
  }

  function fetchRow(convId, then) {
    WA.getJSON('/messages/row/' + convId + '/').then(function (data) {
      var box = rowsBox();
      if (!box || rowFor(convId)) { return; }
      if (!!data.archived !== isArchivedList()) { return; }
      var tmp = document.createElement('div');
      tmp.innerHTML = data.html.trim();
      var row = tmp.firstElementChild;
      moveToTopNew(box, row);
      WA.refreshTimes(row);
      markActive(); refreshUnreadChip(); applyFilter();
      if (then) { then(row); }
    }).catch(function () {});
  }
  function moveToTopNew(box, row) {
    box.appendChild(row);
    moveToTop(row);
  }

  // ---------------- live events ----------------
  WA.on('message', function (e) {
    var msg = e.message;
    var mine = msg.sender && msg.sender.id === WA.me.id;
    var open = WA.currentConversation() === msg.conversation;
    var visible = open && document.visibilityState === 'visible';
    var row = rowFor(msg.conversation);

    if (!mine && !visible) {
      // Got it (grey double tick for the sender); conversation.js marks it read if it's open.
      WA.socket.send({ type: 'delivered', conversation: msg.conversation });
      if (!row || (!rowMuted(row) && row.getAttribute('data-request') !== '1')) { WA.beep(); }
    }
    if (!row) { if (rowsBox()) { fetchRow(msg.conversation); } return; }

    var preview = row.querySelector('.js-wa-preview');
    var old = preview.querySelector('.wa-preview-content');
    preview.replaceChild(previewFor(msg), old);
    preview.classList.remove('is-typing');
    row.setAttribute('data-last-id', msg.id);
    var time = row.querySelector('.js-wa-time');
    time.setAttribute('data-ts', msg.created_at);
    time.textContent = WA.formatTime(msg.created_at, 'list');
    var at = row.querySelector('.js-wa-flag-mention');
    if (at && !mine && !visible && window.UCChatMentions && UCChatMentions.mentionsMe(msg, WA.me.id)) { at.hidden = false; }
    if (!mine && !visible && msg.kind !== 'system') {
      var badge = row.querySelector('.js-wa-unread');
      setRowUnread(row, (parseInt(badge.getAttribute('data-count'), 10) || 0) + 1, false);
    }
    if (mine) { setRowUnread(row, 0, false); }
    moveToTop(row);
    applyFilter();
  });

  WA.on('receipt', function (e) {
    var row = rowFor(e.conversation);
    if (!row) { return; }
    var lastId = parseInt(row.getAttribute('data-last-id'), 10);
    e.items.forEach(function (item) {
      if (item[0] !== lastId) { return; }
      var tick = row.querySelector('[data-message-status]');
      if (tick) { tick.className = 'bi bi-check2-all wa-tick wa-tick-' + item[1]; }
    });
  });

  // The chat's last message was edited: show its new words.
  WA.on('edited', function (e) {
    var row = rowFor(e.conversation);
    if (!row || parseInt(row.getAttribute('data-last-id'), 10) !== e.message.id) { return; }
    var preview = row.querySelector('.js-wa-preview');
    preview.replaceChild(previewFor(e.message), preview.querySelector('.wa-preview-content'));
  });

  WA.on('deleted', function (e) {
    var row = rowFor(e.conversation);
    if (!row || parseInt(row.getAttribute('data-last-id'), 10) !== e.message) { return; }
    var t = row.querySelector('.wa-preview-text');
    if (t) { t.textContent = 'This message was deleted'; }
  });

  WA.on('typing', function (e) {
    if (e.user === WA.me.id) { return; }
    var row = rowFor(e.conversation);
    if (!row) { return; }
    var preview = row.querySelector('.js-wa-preview');
    var label = preview.querySelector('.wa-typing-text');
    label.textContent = row.getAttribute('data-group') === '1' ? e.name + ' is typing…' : 'typing…';
    clearTimeout(typingTimers[e.conversation]);
    preview.classList.toggle('is-typing', e.state);
    if (e.state) { typingTimers[e.conversation] = setTimeout(function () { preview.classList.remove('is-typing'); }, 5000); }
  });

  WA.on('presence', function (e) {
    document.querySelectorAll('#waListPane .js-wa-row[data-user="' + e.user + '"] .wa-online-dot').forEach(function (dot) {
      dot.hidden = !e.online;
    });
  });

  WA.on('unread', function (e) {
    setUnreadTotal(e.unread_chats);
    if (e.conversation) {
      var row = rowFor(e.conversation);
      // Read in this or another tab: clear that row's badge.
      if (row && e.read) { setRowUnread(row, 0, false); }
    }
  });
  WA.on('hello', function (e) { setUnreadTotal(e.unread_chats); });

  WA.on('conversation_added', function (e) { if (rowsBox() && !rowFor(e.conversation)) { fetchRow(e.conversation); } });

  // Chat settings changed from the conversation menu.
  // Muted for a while: once the time is up the chat counts again (the
  // server unmutes it too, next time it's asked — chat/services.py).
  function rowMuted(row) {
    if (row.getAttribute('data-muted') !== '1') { return false; }
    var until = row.getAttribute('data-muted-until');
    if (until && new Date(until) <= new Date()) {
      row.setAttribute('data-muted', '0'); row.removeAttribute('data-muted-until');
      row.querySelector('.js-wa-flag-muted').hidden = true;
      row.querySelector('.js-wa-unread').classList.remove('is-muted');
      return false;
    }
    return true;
  }
  setInterval(function () { document.querySelectorAll('#waListPane .js-wa-row[data-muted-until]').forEach(rowMuted); }, 60000);

  WA.on('chat:action', function (e) {
    var row = rowFor(e.conversation);
    if (!row) { return; }
    var a = e.action;
    if (a === 'pin' || a === 'unpin') {
      row.setAttribute('data-pinned', a === 'pin' ? '1' : '0');
      row.querySelector('.js-wa-flag-pinned').hidden = a !== 'pin';
      if (a === 'pin') { moveToTop(row); }
    } else if (a === 'favourite' || a === 'unfavourite') {
      row.setAttribute('data-favourite', a === 'favourite' ? '1' : '0');
    } else if (a === 'mute' || a === 'unmute') {
      row.setAttribute('data-muted', a === 'mute' ? '1' : '0');
      if (a === 'mute' && e.muted_until) { row.setAttribute('data-muted-until', e.muted_until); } else { row.removeAttribute('data-muted-until'); }
      row.querySelector('.js-wa-flag-muted').hidden = a !== 'mute';
      row.querySelector('.js-wa-flag-muted').title = window.UCMute ? UCMute.label(e.muted_until) : 'Muted';
      row.querySelector('.js-wa-unread').classList.toggle('is-muted', a === 'mute');
    } else if (a === 'mark_unread') {
      setRowUnread(row, parseInt(row.querySelector('.js-wa-unread').getAttribute('data-count'), 10) || 0, true);
    } else if (a === 'archive' || a === 'unarchive') {
      row.remove();
    }
    applyFilter();
  });

  // Opening a chat clears its badge straight away.
  WA.on('conversation:open', function (e) {
    var row = rowFor(e.conversation);
    if (row) { setRowUnread(row, 0, false); var at = row.querySelector('.js-wa-flag-mention'); if (at) { at.hidden = true; } }
    markActive();
  });

  function init() { markActive(); refreshUnreadChip(); applyFilter(); }
  WA.on('page', function (e) {
    if (!e.keepList) { initialFilter(); }
    init();
  });
  init();
})();

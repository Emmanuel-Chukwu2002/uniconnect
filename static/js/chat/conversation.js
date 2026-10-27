/* =====================================================================
   UniConnect Messages — an open conversation

   Draws messages (history from #waConvData, then live ones from the
   WebSocket with the same function), date separators, ticks,
   reactions, "typing…", online / last seen, older-message loading,
   in-chat search, the message menu (react, copy, delete) and the
   chat menu (pin, favourite, mute, archive, mark unread, wallpaper).
   Exposes WA.conv for composer.js.
   ===================================================================== */
(function () {
  'use strict';
  var WA = window.WA;
  if (!WA || !document.getElementById('waApp')) { return; }

  var QUICK_REACTIONS = ['👍', '❤️', '😂', '😮', '😢', '🙏'];
  var state = null;   // the open conversation, or null

  function q(sel) { return state && state.root.querySelector(sel); }

  // ------------------------------------------------------------------
  // Rendering one message
  // ------------------------------------------------------------------
  function tickIcon(status) {
    if (status === 'pending') { return WA.icon('bi-clock', 'wa-tick wa-tick-pending'); }
    return WA.icon(status === 'sent' ? 'bi-check2' : 'bi-check2-all', 'wa-tick wa-tick-' + status);
  }

  function renderReactions(holder, reactions) {
    holder.innerHTML = '';
    holder.hidden = !reactions || !reactions.length;
    (reactions || []).forEach(function (r) {
      var chip = WA.el('button', 'wa-reaction js-wa-reaction' + (r.users.indexOf(WA.me.id) > -1 ? ' is-mine' : ''));
      chip.type = 'button';
      chip.setAttribute('data-emoji', r.emoji);
      chip.title = r.users.map(function (id) {
        if (id === WA.me.id) { return 'You'; }
        var m = state && state.data.members[id];
        return m ? m.name : 'Someone';
      }).join(', ');
      chip.appendChild(document.createTextNode(r.emoji));
      if (r.count > 1) { chip.appendChild(WA.el('span', 'wa-reaction-count', r.count)); }
      holder.appendChild(chip);
    });
  }

  function audioPlayer(msg) {
    var box = WA.el('div', 'wa-audio');
    var audio = new Audio();
    audio.preload = 'metadata';
    audio.src = msg.attachment.url;
    var btn = WA.el('button', 'wa-audio-play'); btn.type = 'button'; btn.setAttribute('aria-label', 'Play voice message');
    btn.appendChild(WA.icon('bi-play-fill'));
    var bar = WA.el('div', 'wa-audio-bar'), fill = WA.el('span', 'wa-audio-fill');
    bar.appendChild(fill);
    var time = WA.el('span', 'wa-audio-time', WA.formatDuration(msg.duration));
    btn.addEventListener('click', function () {
      if (audio.paused) {
        document.querySelectorAll('.wa-audio.is-playing').forEach(function (other) { if (other !== box && other._audio) { other._audio.pause(); } });
        audio.play().catch(function () { WA.toast("Couldn't play this voice message.", 'error'); });
      } else { audio.pause(); }
    });
    audio.addEventListener('play', function () { box.classList.add('is-playing'); btn.firstChild.className = 'bi bi-pause-fill'; });
    audio.addEventListener('pause', function () { box.classList.remove('is-playing'); btn.firstChild.className = 'bi bi-play-fill'; });
    audio.addEventListener('ended', function () { fill.style.width = '0%'; time.textContent = WA.formatDuration(msg.duration); });
    audio.addEventListener('timeupdate', function () {
      var total = isFinite(audio.duration) ? audio.duration : msg.duration;
      if (total) { fill.style.width = Math.min(100, audio.currentTime / total * 100) + '%'; }
      time.textContent = WA.formatDuration(audio.currentTime);
    });
    bar.addEventListener('click', function (e) {
      var total = isFinite(audio.duration) ? audio.duration : msg.duration;
      var rect = bar.getBoundingClientRect();
      if (total) { audio.currentTime = total * Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)); }
    });
    box._audio = audio;
    box.appendChild(btn); box.appendChild(bar); box.appendChild(time);
    if (msg.sender) { box.appendChild(WA.avatar(msg.sender, 34)); }
    return box;
  }

  function renderMessage(msg) {
    var mine = msg.sender && msg.sender.id === WA.me.id;
    if (msg.kind === 'system') {
      var sys = WA.el('div', 'wa-msg is-system');
      sys.setAttribute('data-id', msg.id);
      sys.setAttribute('data-ts', msg.created_at);
      sys.appendChild(WA.el('span', 'wa-system-pill', msg.content));
      return sys;
    }
    var wrap = WA.el('div', 'wa-msg ' + (mine ? 'is-out' : 'is-in'));
    wrap.setAttribute('data-id', msg.id || '');
    wrap.setAttribute('data-ts', msg.created_at);
    wrap.setAttribute('data-sender', msg.sender ? msg.sender.id : '');
    if (msg.client_id) { wrap.setAttribute('data-client-id', msg.client_id); }

    var bubble = WA.el('div', 'wa-bubble');
    if (state && state.data.is_group && !mine && msg.sender) {
      var name = WA.el('span', 'wa-sender', msg.sender.name);
      name.style.color = msg.sender.name_colour;
      bubble.appendChild(name);
    }
    var body = WA.el('div', 'wa-bubble-body');
    if (msg.is_deleted) {
      wrap.classList.add('is-deleted');
      var del = WA.el('span', 'wa-text wa-deleted');
      del.appendChild(WA.icon('bi-slash-circle'));
      del.appendChild(document.createTextNode(mine ? ' You deleted this message' : ' This message was deleted'));
      body.appendChild(del);
    } else {
      if (msg.forwarded) {
        var fwd = WA.el('span', 'wa-forwarded'); fwd.appendChild(WA.icon('bi-forward-fill')); fwd.appendChild(document.createTextNode(' Forwarded'));
        body.appendChild(fwd);
      }
      if (msg.reply_to) {
        // The message it replies to, as a quote; tapping it jumps there.
        var quote = WA.el('button', 'wa-quote js-wa-quote');
        quote.type = 'button';
        quote.setAttribute('data-jump', msg.reply_to.id);
        quote.appendChild(WA.el('b', '', msg.reply_to.sender === WA.me.id ? 'You' : msg.reply_to.name));
        quote.appendChild(WA.el('span', '', msg.reply_to.text));
        body.appendChild(quote);
      }
      if (msg.kind === 'image' && msg.attachment) {
        var link = WA.el('a', 'wa-media');
        link.href = msg.attachment.url; link.target = '_blank'; link.rel = 'noopener';
        var img = WA.el('img'); img.src = msg.attachment.url; img.alt = 'Photo'; img.loading = 'lazy';
        img.addEventListener('load', function () { if (state && state.stickToBottom) { scrollToBottom(); } });
        link.appendChild(img);
        body.appendChild(link);
      } else if (msg.kind === 'video' && msg.attachment) {
        var vid = WA.el('video', 'wa-video');
        vid.src = msg.attachment.url; vid.controls = true; vid.preload = 'metadata'; vid.playsInline = true;
        body.appendChild(vid);
      } else if (msg.kind === 'file' && msg.attachment) {
        var doc = WA.el('a', 'wa-doc');
        doc.href = msg.attachment.url; doc.target = '_blank'; doc.rel = 'noopener'; doc.download = msg.attachment.name;
        doc.appendChild(WA.icon('bi-file-earmark-text-fill', 'wa-doc-icon'));
        var info = WA.el('span', 'wa-doc-info');
        info.appendChild(WA.el('span', 'wa-doc-name', msg.attachment.name));
        var ext = (msg.attachment.name.split('.').pop() || '').toUpperCase();
        info.appendChild(WA.el('span', 'wa-doc-size', [WA.formatBytes(msg.attachment.size), ext].filter(Boolean).join(' · ')));
        doc.appendChild(info);
        body.appendChild(doc);
      } else if (msg.kind === 'audio' && msg.attachment) {
        body.appendChild(audioPlayer(msg));
      }
      if (msg.kind === 'poll' && msg.poll && window.UCPoll) {
        wrap.classList.add('has-poll');
        body.appendChild(UCPoll.card(msg, WA.me.id));        // static/js/chat-polls.js
      } else if (msg.content) {
        var text = WA.el('span', 'wa-text');
        text.appendChild(WA.richText(msg.content));
        if (window.UCChatMentions) { UCChatMentions.decorate(text, msg.mentions, WA.me.id); }   // @mentions
        body.appendChild(text);
      }
    }
    var meta = WA.el('span', 'wa-meta');
    var pinMark = WA.icon('bi-pin-angle-fill'); pinMark.className += ' wa-pinmark'; pinMark.title = 'Pinned';
    meta.appendChild(pinMark);
    var starMark = WA.icon('bi-star-fill'); starMark.className += ' wa-starmark'; starMark.title = 'Starred';
    meta.appendChild(starMark);
    if (msg.edited && !msg.is_deleted) { meta.appendChild(WA.el('span', 'wa-edited', 'Edited')); }
    meta.appendChild(WA.el('time', '', WA.formatTime(msg.created_at, 'clock')));
    if (mine && !msg.is_deleted) { var t = tickIcon(msg.status); t.setAttribute('data-tick', ''); meta.appendChild(t); }
    body.appendChild(meta);
    bubble.appendChild(body);

    if (!msg.is_deleted && msg.id) {
      var menuBtn = WA.el('button', 'wa-msg-menu-btn js-wa-msg-menu');
      menuBtn.type = 'button'; menuBtn.setAttribute('aria-label', 'Message options');
      menuBtn.appendChild(WA.icon('bi-chevron-down'));
      bubble.appendChild(menuBtn);
    }
    wrap.appendChild(bubble);
    if (state && msg.sender && (state.data.is_group || !mine)) {
      // Group chats show who sent each message (private chats: the other person's photo on their messages): their photo beside the bubble (CSS shows it on the last of a run).
      var face = WA.el('span', 'wa-msg-avatar');
      face.setAttribute('data-user', msg.sender.id);
      face.appendChild(WA.avatar(msg.sender, 40));
      var dot = WA.el('span', 'wa-online-dot'); dot.title = 'Online';
      var known = state.data.members && state.data.members[msg.sender.id];
      dot.hidden = !(known && known.online);
      face.appendChild(dot);
      wrap.appendChild(face);
    }
    var reactions = WA.el('div', 'wa-reactions');
    renderReactions(reactions, msg.reactions);
    wrap.appendChild(reactions);
    wrap._msg = msg;
    if (window.UCPins && state && msg.id) { wrap.classList.toggle('is-pinned', UCPins.isPinned(state.id, msg.id)); }
    if (state && msg.id && state.starred && state.starred[msg.id]) { wrap.classList.add('is-starred'); }
    return wrap;
  }

  // ------------------------------------------------------------------
  // Placing messages: date separators + grouping
  // ------------------------------------------------------------------
  function dayDivider(iso) {
    var d = WA.el('div', 'wa-day');
    d.setAttribute('data-day', new Date(iso).toDateString());
    d.appendChild(WA.el('span', '', WA.dayLabel(new Date(iso))));
    return d;
  }

  /** Re-applies is-first (tail + sender name) and day dividers to the
   *  whole list. Cheap enough for a page of messages. */
  function relayout() {
    var list = q('.js-wa-message-list');
    if (!list) { return; }
    list.querySelectorAll('.wa-day').forEach(function (d) { d.remove(); });
    var prev = null;
    list.querySelectorAll('.wa-msg').forEach(function (el) {
      var ts = new Date(el.getAttribute('data-ts'));
      if (!prev || !WA.sameDay(new Date(prev.getAttribute('data-ts')), ts)) {
        list.insertBefore(dayDivider(el.getAttribute('data-ts')), el);
      }
      var first = !prev || prev.classList.contains('is-system') || el.classList.contains('is-system') ||
        prev.getAttribute('data-sender') !== el.getAttribute('data-sender') ||
        !WA.sameDay(new Date(prev.getAttribute('data-ts')), ts) ||
        (ts - new Date(prev.getAttribute('data-ts'))) > 10 * 60000;
      el.classList.toggle('is-first', first);
      var name = el.querySelector('.wa-sender');
      if (name) { name.hidden = !first; }
      prev = el;
    });
    // is-last: the final message of a run (group chats show the sender's photo and the time there).
    var all = list.querySelectorAll('.wa-msg');
    all.forEach(function (el, i) {
      var next = all[i + 1], last = true;
      if (next && !next.classList.contains('is-system') && !el.classList.contains('is-system')) {
        last = next.getAttribute('data-sender') !== el.getAttribute('data-sender') ||
          !WA.sameDay(new Date(el.getAttribute('data-ts')), new Date(next.getAttribute('data-ts'))) ||
          (new Date(next.getAttribute('data-ts')) - new Date(el.getAttribute('data-ts'))) > 10 * 60000;
      }
      el.classList.toggle('is-last', last);
    });
  }

  function nearBottom() {
    var box = q('.js-wa-messages');
    return !box || box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  }
  // Smooth scrolling is on everywhere (restyle.css); opening a chat or loading
  // older messages should land in place at once instead.
  function jump(box, top) { box.style.scrollBehavior = 'auto'; box.scrollTop = top; box.style.scrollBehavior = ''; }
  function scrollToBottom(smooth) {
    var box = q('.js-wa-messages');
    if (!box) { return; }
    if (smooth) { box.scrollTo({ top: box.scrollHeight, behavior: 'smooth' }); } else { jump(box, box.scrollHeight); }
  }

  function append(msg) {
    var list = q('.js-wa-message-list');
    var el = renderMessage(msg);
    list.appendChild(el);
    if (msg.id) { state.byId[msg.id] = el; }
    relayout();
    return el;
  }

  // ------------------------------------------------------------------
  // Reading, header status
  // ------------------------------------------------------------------
  function markRead() {
    if (!state || document.visibilityState !== 'visible') { return; }
    WA.socket.send({ type: 'read', conversation: state.id });
    WA.emit('conversation:open', { conversation: state.id });
  }

  function setStatus(text, isTyping) {
    var el = q('.js-wa-conv-status');
    if (!el) { return; }
    el.textContent = text;
    el.classList.toggle('is-typing', !!isTyping);
  }
  // The green dot on the header photo of a private chat: on while they're online.
  function headDot() {
    var dot = q('.js-wa-head-dot');
    if (dot) { dot.hidden = !(state && !state.data.is_group && state.presence && state.presence.online); }
  }
  function statusDefault() {
    if (!state) { return; }
    headDot();
    var el = q('.js-wa-conv-status');
    var p = state.presence;
    if (!state.data.is_group && !state.data.is_self && p) {
      if (p.online) { return setStatus('online'); }
      if (p.last_seen) { return setStatus(WA.formatTime(p.last_seen, 'lastseen')); }
    }
    setStatus(el ? el.getAttribute('data-default') : '');
  }

  // ------------------------------------------------------------------
  // Opening / closing
  // ------------------------------------------------------------------
  function open() {
    close();
    var dataEl = document.getElementById('waConvData');
    var root = document.querySelector('#waMainPane .js-wa-conv');
    if (!dataEl || !root) { return; }
    var data = JSON.parse(dataEl.textContent);
    state = {
      id: data.id, data: data, root: root, byId: {}, hasMore: data.has_more, loadingOlder: false,
      presence: data.presence, typingTimer: null, stickToBottom: true, newBelow: 0,
    };
    if (window.UCPins) { UCPins.set(data.id, data.pins, data.can_pin); }
    state.starred = {};
    (data.starred || []).forEach(function (id) { state.starred[id] = true; });
    var list = q('.js-wa-message-list');
    var firstUnread = null;
    data.messages.forEach(function (m) {
      var el = append(m);
      if (!firstUnread && data.unread_from && m.sender && m.sender.id !== WA.me.id && m.kind !== 'system' &&
          new Date(m.created_at) > new Date(data.unread_from)) { firstUnread = el; }
    });
    if (firstUnread) {
      var count = list.querySelectorAll('.wa-msg').length - Array.prototype.indexOf.call(list.querySelectorAll('.wa-msg'), firstUnread);
      var divider = WA.el('div', 'wa-unread-divider');
      divider.appendChild(WA.el('span', '', count + ' unread message' + (count === 1 ? '' : 's')));
      list.insertBefore(divider, firstUnread);
    }
    statusDefault();
    var box = q('.js-wa-messages');
    if (firstUnread) { jump(box, Math.max(0, firstUnread.offsetTop - 80)); } else { scrollToBottom(); }
    box.addEventListener('scroll', onScroll, { passive: true });
    refreshPins();
    WA.emit('conversation:ready', { conversation: state.id, root: root, data: data });
    markRead();
    // Opened from a search result (?m=<message id>): scroll to that message.
    var target = parseInt(new URLSearchParams(location.search).get('m'), 10);
    if (target) { jumpTo(target, 0); }
  }

  // Finds a message (loading older ones if needed), scrolls it into the
  // middle of the chat and briefly highlights it.
  function jumpTo(id, tries) {
    if (!state) { return; }
    var el = state.byId[id] || q('.wa-msg[data-id="' + id + '"]');
    if (el) {
      el.scrollIntoView({ block: 'center' });
      el.classList.add('is-found');
      setTimeout(function () { el.classList.remove('is-found'); }, 2600);
      return;
    }
    if (state.hasMore && !state.loadingOlder && tries < 30) {
      var p = loadOlder();
      if (p && p.then) { p.then(function () { jumpTo(id, tries + 1); }); }
    }
  }

  function close() {
    if (!state) { return; }
    closeMenu();
    WA.emit('conversation:closed', { conversation: state.id });
    state = null;
  }

  // ------------------------------------------------------------------
  // Scrolling: older messages + "new messages" button
  // ------------------------------------------------------------------
  function onScroll() {
    if (!state) { return; }
    var box = q('.js-wa-messages');
    state.stickToBottom = nearBottom();
    var down = q('.js-wa-scroll-down');
    if (down) { down.hidden = state.stickToBottom; }
    if (state.stickToBottom) { state.newBelow = 0; updateNewBelow(); }
    if (box.scrollTop < 80 && state.hasMore && !state.loadingOlder) { loadOlder(); }
  }
  function updateNewBelow() {
    var c = q('.js-wa-scroll-down-count');
    if (c) { c.hidden = !state.newBelow; c.textContent = state.newBelow; }
  }

  function loadOlder() {
    var list = q('.js-wa-message-list');
    var first = list.querySelector('.wa-msg[data-id]');
    if (!first) { return Promise.resolve(); }
    state.loadingOlder = true;
    var spinner = q('.js-wa-load-older');
    spinner.hidden = false;
    var convId = state.id;
    return WA.getJSON('/messages/c/' + convId + '/history/?before=' + first.getAttribute('data-id')).then(function (res) {
      if (!state || state.id !== convId) { return; }
      (res.starred || []).forEach(function (id) { state.starred[id] = true; });
      var box = q('.js-wa-messages');
      var before = box.scrollHeight;
      var frag = document.createDocumentFragment();
      res.messages.forEach(function (m) { var el = renderMessage(m); state.byId[m.id] = el; frag.appendChild(el); });
      list.insertBefore(frag, list.firstChild);
      relayout();
      jump(box, box.scrollTop + box.scrollHeight - before);   // older messages added above: stay put
      state.hasMore = res.has_more;
    }).catch(function () {}).then(function () {
      if (state) { state.loadingOlder = false; spinner.hidden = true; }
    });
  }

  // ------------------------------------------------------------------
  // Live events
  // ------------------------------------------------------------------
  WA.on('message', function (e) {
    var msg = e.message;
    if (!state || msg.conversation !== state.id) { return; }
    var mine = msg.sender && msg.sender.id === WA.me.id;
    var stick = nearBottom() || mine;
    var pending = msg.client_id && state.root.querySelector('.wa-msg[data-client-id="' + msg.client_id + '"]');
    if (pending) {
      var el = renderMessage(msg);
      pending.replaceWith(el);
      state.byId[msg.id] = el;
      relayout();
    } else if (!state.byId[msg.id]) {
      append(msg);
    }
    if (!mine) {
      clearTimeout(state.typingTimer);
      statusDefault();
      var divider = q('.wa-unread-divider');
      if (divider && stick) { divider.remove(); }
    }
    if (stick) { scrollToBottom(true); }
    else if (!mine) { state.newBelow++; updateNewBelow(); var down = q('.js-wa-scroll-down'); if (down) { down.hidden = false; } }
    if (!mine) {
      if (document.visibilityState === 'visible') { markRead(); }
      else { WA.socket.send({ type: 'delivered', conversation: state.id }); }
    }
  });

  WA.on('receipt', function (e) {
    if (!state || e.conversation !== state.id) { return; }
    var order = { pending: 0, sent: 1, delivered: 2, read: 3 };
    e.items.forEach(function (item) {
      var el = state.byId[item[0]];
      if (!el || !el._msg) { return; }
      if (order[item[1]] <= order[el._msg.status]) { return; }
      el._msg.status = item[1];
      var tick = el.querySelector('[data-tick]');
      if (tick) { var t = tickIcon(item[1]); t.setAttribute('data-tick', ''); tick.replaceWith(t); }
    });
  });

  WA.on('typing', function (e) {
    if (!state || e.conversation !== state.id || e.user === WA.me.id) { return; }
    clearTimeout(state.typingTimer);
    if (!e.state) { return statusDefault(); }
    setStatus(state.data.is_group ? e.name + ' is typing…' : 'typing…', true);
    state.typingTimer = setTimeout(statusDefault, 5000);
  });

  WA.on('presence', function (e) {
    if (state && state.data.is_group) {
      // Someone in this group came online / went offline: update the dot on their photo.
      var known = state.data.members && state.data.members[e.user];
      if (known) { known.online = !!e.online; }
      document.querySelectorAll('.wa-msg-avatar[data-user="' + e.user + '"] .wa-online-dot').forEach(function (d) { d.hidden = !e.online; });
    }
    if (!state || !state.data.other || state.data.other.id !== e.user) { return; }
    state.presence = { online: e.online, last_seen: e.last_seen };
    headDot();
    if (!q('.js-wa-conv-status.is-typing')) { statusDefault(); }
  });

  WA.on('reaction', function (e) {
    if (!state || e.conversation !== state.id) { return; }
    var el = state.byId[e.message];
    if (!el) { return; }
    el._msg.reactions = e.reactions;
    renderReactions(el.querySelector('.wa-reactions'), e.reactions);
  });

  // Pinned messages (static/js/chat-pins.js): the bar under the header,
  // and a pin on each pinned message.
  function refreshPins() {
    if (!state || !window.UCPins) { return; }
    UCPins.render(q('.js-wa-pins'), state.id, function (id) { jumpTo(id, 0); });
    state.root.querySelectorAll('.wa-msg[data-id]').forEach(function (m) {
      var id = parseInt(m.getAttribute('data-id'), 10);
      m.classList.toggle('is-pinned', !!id && UCPins.isPinned(state.id, id));
    });
  }
  WA.on('pins', function (e) {
    if (!window.UCPins) { return; }
    UCPins.set(e.conversation, e.pins);
    if (state && e.conversation === state.id) { refreshPins(); }
  });
  document.addEventListener('uc:pins', function (e) { if (state && e.detail.conversation === state.id) { refreshPins(); } });

  WA.on('poll', function (e) {
    if (state && e.conversation === state.id && state.byId[e.message]) { state.byId[e.message]._msg.poll = e.poll; }
    if (window.UCPoll) { UCPoll.update(e.message, e.poll); }
  });

  // A message was edited (here or by its sender elsewhere): draw it again.
  WA.on('edited', function (e) {
    if (!state || e.conversation !== state.id) { return; }
    var el = state.byId[e.message.id];
    if (!el) { return; }
    var fresh = renderMessage(e.message);
    el.replaceWith(fresh);
    state.byId[e.message.id] = fresh;
    relayout();
  });

  WA.on('deleted', function (e) {
    if (!state || e.conversation !== state.id) { return; }
    var el = state.byId[e.message];
    if (!el) { return; }
    var msg = el._msg;
    msg.is_deleted = true; msg.content = ''; msg.attachment = null; msg.reactions = [];
    var fresh = renderMessage(msg);
    el.replaceWith(fresh);
    state.byId[e.message] = fresh;
    relayout();
  });

  // Back from another tab / reconnected: catch up on read receipts.
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') { markRead(); } });
  WA.on('open', function () { if (state) { markRead(); } });

  // ------------------------------------------------------------------
  // For composer.js: optimistic "sending" bubbles
  // ------------------------------------------------------------------
  WA.conv = {
    id: function () { return state ? state.id : null; },
    data: function () { return state ? state.data : null; },
    addPending: function (msg) {
      if (!state) { return null; }
      var el = append(msg);
      scrollToBottom(true);
      return el;
    },
    failPending: function (clientId, text) {
      var el = state && state.root.querySelector('.wa-msg[data-client-id="' + clientId + '"]');
      if (!el) { return; }
      el.classList.add('is-failed');
      var meta = el.querySelector('.wa-meta');
      if (meta) { meta.appendChild(WA.el('span', 'wa-failed', text || 'Not sent')); }
    },
    scrollToBottom: scrollToBottom,
  };

  // ------------------------------------------------------------------
  // Message menu: quick reactions, copy, delete
  // ------------------------------------------------------------------
  var pop = null;
  function closeMenu() { if (pop) { pop.remove(); pop = null; } }

  function openMenu(msgEl, anchor) {
    closeMenu();
    var msg = msgEl._msg;
    if (!msg || !msg.id || msg.is_deleted) { return; }
    pop = WA.el('div', 'wa-msg-pop');
    var row = WA.el('div', 'wa-quick-reactions');
    QUICK_REACTIONS.forEach(function (emoji) {
      var b = WA.el('button', 'wa-quick-reaction', emoji);
      b.type = 'button';
      var mineEmoji = (msg.reactions || []).some(function (r) { return r.emoji === emoji && r.users.indexOf(WA.me.id) > -1; });
      if (mineEmoji) { b.classList.add('is-mine'); }
      b.addEventListener('click', function () { WA.socket.send({ type: 'react', message: msg.id, emoji: emoji }); closeMenu(); });
      row.appendChild(b);
    });
    pop.appendChild(row);
    var actions = WA.el('div', 'wa-pop-actions');
    function action(label, icon, fn) {
      var b = WA.el('button', 'wa-pop-action'); b.type = 'button';
      b.appendChild(WA.icon(icon)); b.appendChild(document.createTextNode(' ' + label));
      b.addEventListener('click', function () { closeMenu(); fn(); });
      actions.appendChild(b);
    }
    action('Reply', 'bi-reply', function () { if (WA.setReply) { WA.setReply(msg); } });
    // Star: yours to find later in Messages → Starred.
    var isStar = !!(state.starred && state.starred[msg.id]);
    action(isStar ? 'Unstar' : 'Star', isStar ? 'bi-star-fill' : 'bi-star', function () {
      WA.post('/messages/m/' + msg.id + '/star/', { star: isStar ? '0' : '1' }).then(function (res) {
        if (!state) { return; }
        if (res.starred) { state.starred[msg.id] = true; } else { delete state.starred[msg.id]; }
        if (msgEl) { msgEl.classList.toggle('is-starred', !!res.starred); }
        WA.toast(res.starred ? 'Starred' : 'Unstarred');
      }).catch(function (err) { WA.toast(err.message, 'error'); });
    });
    if (window.UCForward) { action('Forward', 'bi-forward', function () { UCForward.open(msg); }); }
    if (msg.content) {
      action('Copy', 'bi-copy', function () {
        (navigator.clipboard ? navigator.clipboard.writeText(msg.content) : Promise.reject()).then(
          function () { WA.toast('Message copied.'); }, function () { WA.toast("Couldn't copy.", 'error'); });
      });
    }
    if (msg.attachment) { action('Open', 'bi-box-arrow-up-right', function () { window.open(msg.attachment.url, '_blank', 'noopener'); }); }
    if (window.UCPins && UCPins.canPin(state.id)) {
      var on = UCPins.isPinned(state.id, msg.id), cid = state.id;
      action(on ? 'Unpin' : 'Pin', on ? 'bi-pin-angle-fill' : 'bi-pin-angle', function () {
        UCPins.toggle(cid, msg.id).then(function () { WA.toast(on ? 'Message unpinned' : 'Message pinned'); })
          .catch(function (err) { WA.toast(err.message, 'error'); });
      });
    }
    // Your own message, for 15 minutes after sending (chat/editing.py).
    if (msg.sender && msg.sender.id === WA.me.id && ['text', 'image', 'video', 'file'].indexOf(msg.kind) > -1 &&
        Date.now() - new Date(msg.created_at) <= 15 * 60000 && WA.startEdit) {
      action('Edit', 'bi-pencil', function () { WA.startEdit(msg); });
    }
    if (msg.sender && msg.sender.id === WA.me.id) {
      action('Delete for everyone', 'bi-trash', function () { WA.socket.send({ type: 'delete', message: msg.id }); });
    }
    pop.appendChild(actions);
    document.body.appendChild(pop);
    var r = (anchor || msgEl.querySelector('.wa-bubble')).getBoundingClientRect();
    var w = pop.offsetWidth, h = pop.offsetHeight;
    var left = msgEl.classList.contains('is-out') ? r.right - w : r.left;
    left = Math.max(8, Math.min(window.innerWidth - w - 8, left));
    var top = r.bottom + 6 + h > window.innerHeight ? r.top - h - 6 : r.bottom + 6;
    pop.style.left = left + 'px';
    pop.style.top = Math.max(8, top) + 'px';
  }

  document.addEventListener('click', function (e) {
    if (pop && !pop.contains(e.target) && !e.target.closest('.js-wa-msg-menu')) { closeMenu(); }
    if (!state) { return; }
    var menuBtn = e.target.closest('.js-wa-msg-menu');
    if (menuBtn && state.root.contains(menuBtn)) { e.preventDefault(); openMenu(menuBtn.closest('.wa-msg'), menuBtn); return; }
    var quoteBtn = e.target.closest('.js-wa-quote');
    if (quoteBtn && state.root.contains(quoteBtn)) { jumpTo(parseInt(quoteBtn.getAttribute('data-jump'), 10), 0); return; }
    var chip = e.target.closest('.js-wa-reaction');
    if (chip && state.root.contains(chip)) {
      var id = parseInt(chip.closest('.wa-msg').getAttribute('data-id'), 10);
      WA.socket.send({ type: 'react', message: id, emoji: chip.getAttribute('data-emoji') });
    }
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { closeMenu(); } });
  // Right-click / long-press opens the same menu.
  document.addEventListener('contextmenu', function (e) {
    var bubble = state && e.target.closest('.js-wa-conv .wa-bubble');
    if (!bubble || e.target.closest('a')) { return; }
    e.preventDefault();
    openMenu(bubble.closest('.wa-msg'), bubble);
  });
  var pressTimer = null;
  document.addEventListener('touchstart', function (e) {
    var bubble = state && e.target.closest('.js-wa-conv .wa-bubble');
    if (!bubble) { return; }
    pressTimer = setTimeout(function () { openMenu(bubble.closest('.wa-msg'), bubble); }, 450);
  }, { passive: true });
  ['touchend', 'touchmove', 'touchcancel'].forEach(function (t) {
    document.addEventListener(t, function () { clearTimeout(pressTimer); }, { passive: true });
  });

  // ------------------------------------------------------------------
  // Header: chat menu, info panel, search, scroll-down
  // ------------------------------------------------------------------
  document.addEventListener('click', function (e) {
    if (!state) { return; }
    var t = e.target;

    var actionBtn = t.closest('.js-wa-chat-action');
    if (actionBtn && state.root.contains(actionBtn)) {
      var single = actionBtn.hasAttribute('data-single');
      var on = actionBtn.getAttribute('data-state') === '1';
      var action = single ? actionBtn.getAttribute('data-on') : (on ? actionBtn.getAttribute('data-off') : actionBtn.getAttribute('data-on'));
      var convId = state.id;
      // Muting asks for how long first (static/js/mute-picker.js).
      var ask = action === 'mute' && window.UCMute ? UCMute.pick(q('.wa-conv-name') ? q('.wa-conv-name').textContent.trim() : '') : Promise.resolve(null);
      ask.then(function (length) {
        if (action === 'mute' && window.UCMute && !length) { return; }     // cancelled
        var fields = { action: action };
        if (length) { fields['for'] = length; }
        return WA.post('/messages/c/' + convId + '/action/', fields).then(function (res) { done(res); });
      }).catch(function (err) { WA.toast(err.message, 'error'); });
      function done(res) {
        if (!single) {
          actionBtn.setAttribute('data-state', on ? '0' : '1');
          actionBtn.textContent = on ? actionBtn.getAttribute('data-label-on') : actionBtn.getAttribute('data-label-off');
        }
        if (action === 'mute' || action === 'unmute') { state.data.muted = action === 'mute'; state.data.muted_until = res.muted_until || null; }
        if (action === 'mute' && res.muted_until) {
          var note = document.createElement('small'); note.className = 'wa-menu-note';
          note.textContent = ' (muted until ' + UCMute.when(res.muted_until) + ')';
          actionBtn.appendChild(note);
        }
        WA.emit('chat:action', { conversation: convId, action: action, muted_until: res.muted_until || null });
        var labels = { pin: 'Chat pinned', unpin: 'Chat unpinned', favourite: 'Added to favourites', unfavourite: 'Removed from favourites',
          mute: res.muted_until ? UCMute.label(res.muted_until) : 'Muted — until you unmute it', unmute: 'Notifications unmuted', archive: 'Chat archived', unarchive: 'Chat unarchived', mark_unread: 'Marked as unread' };
        WA.toast(labels[action] || 'Done');
        // Archiving / unarchiving / marking unread closes the chat, like WhatsApp.
        if (action === 'archive' || action === 'unarchive') { WA.navigate('/messages/'); }
        if (action === 'mark_unread') { WA.navigate(state && state.data.archived ? '/messages/archived/' : '/messages/'); }
      }
      return;
    }

    if (t.closest('.js-wa-open-info') && state.root.contains(t)) {
      var panel = q('.js-wa-info-panel');
      panel.hidden = false;
      panel.innerHTML = '<div class="wa-info-loading"><span class="spinner-border spinner-border-sm"></span></div>';
      requestAnimationFrame(function () { panel.classList.add('is-open'); });
      fetch('/messages/c/' + state.id + '/info/', { credentials: 'same-origin' }).then(function (r) { return r.text(); })
        .then(function (html) { if (state) { panel.innerHTML = html; } });
      return;
    }
    if (t.closest('.js-wa-close-info')) {
      var p = q('.js-wa-info-panel');
      p.classList.remove('is-open');
      setTimeout(function () { p.hidden = true; }, 200);
      return;
    }

    if (t.closest('.js-wa-search-toggle') && state.root.contains(t)) {
      var bar = q('.js-wa-conv-search');
      bar.hidden = !bar.hidden;
      if (!bar.hidden) { q('.js-wa-conv-search-input').focus(); } else { searchMessages(''); }
      return;
    }
    if (t.closest('.js-wa-scroll-down')) { scrollToBottom(true); return; }
    if (t.closest('.js-wa-wallpaper') && state.root.contains(t)) {
      var app = document.getElementById('waApp');
      var next = app.classList.contains('wa-wallpaper-doodle') ? 'plain' : 'doodle';
      WA.post('/messages/you/settings/', { field: 'wallpaper', value: next }).then(function () {
        app.classList.remove('wa-wallpaper-doodle', 'wa-wallpaper-plain');
        app.classList.add('wa-wallpaper-' + next);
      }).catch(function (err) { WA.toast(err.message, 'error'); });
    }
  });

  // In-chat search: highlights matches and jumps between them.
  var matches = [], matchIdx = -1;
  function searchMessages(term) {
    if (!state) { return; }
    term = (term || '').trim().toLowerCase();
    state.root.querySelectorAll('.wa-msg.is-match, .wa-msg.is-current-match').forEach(function (el) { el.classList.remove('is-match', 'is-current-match'); });
    matches = [];
    if (term) {
      state.root.querySelectorAll('.wa-msg').forEach(function (el) {
        if (el._msg && (el._msg.content || '').toLowerCase().indexOf(term) > -1) { matches.push(el); el.classList.add('is-match'); }
      });
    }
    matchIdx = matches.length - 1;
    var count = q('.js-wa-conv-search-count');
    if (count) { count.textContent = term ? (matches.length ? matches.length + ' found' : 'No results') : ''; }
    showMatch();
  }
  function showMatch() {
    if (matchIdx < 0 || !matches[matchIdx]) { return; }
    matches.forEach(function (m) { m.classList.remove('is-current-match'); });
    matches[matchIdx].classList.add('is-current-match');
    matches[matchIdx].scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
  document.addEventListener('input', function (e) {
    if (e.target.matches('.js-wa-conv-search-input')) { searchMessages(e.target.value); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.target.matches('.js-wa-conv-search-input') && e.key === 'Enter' && matches.length) {
      e.preventDefault();
      matchIdx = (matchIdx - 1 + matches.length) % matches.length;  // older match each time
      showMatch();
    }
  });

  // ------------------------------------------------------------------
  WA.on('page:leave', close);
  WA.on('page', open);
  open();
})();

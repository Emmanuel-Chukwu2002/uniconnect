/* =====================================================================
   A group's Chat tab (templates/studygroups/detail.html, ?tab=chat).

   It IS the group's chat in Messages, shown on the group's page:
     history     GET  /messages/c/<id>/history/        (older: ?before=<id>)
     live        WebSocket /ws/chat/  (the same one Messages uses)
                 send: message (with reply_to), react, delete, typing, read
                 get:  message, reaction, deleted, typing, receipt
     files       POST /messages/c/<id>/upload/          photos and documents
     seen by     GET  /groups/<g>/chat/seen/            when each member last read it
     search      GET  /groups/<g>/chat/search/?q=

   Everything typed by people is put on the page as text (never as HTML).
   ===================================================================== */
(function () {
  'use strict';

  var QUICK = ['👍', '❤️', '😂', '😮', '🙏', '🎉'];
  var EMOJI = ('😀 😃 😄 😁 😆 😅 😂 🤣 😊 😇 🙂 😉 😍 🥰 😘 😋 😎 🤩 🥳 😏 😌 😴 🤔 🤗 🤭 😐 🙄 😬 😮 😲 😳 🥺 😢 😭 😤 😡 🤯 😱 😩 ' +
    '👍 👎 👏 🙌 🙏 🤝 👋 ✌️ 🤞 👌 💪 👀 🫶 ❤️ 💙 💯 🔥 ✨ 🎉 🎓 📚 📝 ✅ ❌ ⚡ ⭐ 💡 📌 📎 ☕ 🍕 ⚽ 🏆').split(' ');
  var GROUP_GAP = 5 * 60 * 1000;   // messages from one person within 5 minutes sit together

  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ''; }
  function toast(t, k) { if (window.showToast) { window.showToast(t, k); } }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) { e.className = cls; } if (text != null) { e.textContent = text; } return e; }
  function icon(name) { return el('i', 'bi ' + name); }
  function uid() { return 'g' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7); }
  function bytes(n) { if (!n) { return ''; } if (n < 1024) { return n + ' B'; } if (n < 1048576) { return (n / 1024).toFixed(0) + ' KB'; } return (n / 1048576).toFixed(1) + ' MB'; }
  function clock(iso) { return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); }
  function dayLabel(iso) {
    var d = new Date(iso), today = new Date(), y = new Date(); y.setDate(today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) { return 'Today'; }
    if (d.toDateString() === y.toDateString()) { return 'Yesterday'; }
    return d.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long', year: d.getFullYear() === today.getFullYear() ? undefined : 'numeric' });
  }
  // Text with links made clickable — built from text nodes, so nothing typed becomes HTML.
  function richText(text) {
    var frag = document.createDocumentFragment(), re = /https?:\/\/[^\s<>"']+/g, last = 0, m;
    while ((m = re.exec(text))) {
      var url = m[0].replace(/[.,;:!?)\]]+$/, '');
      frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      var a = el('a', 'gc-link', url); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer nofollow';
      frag.appendChild(a);
      last = m.index + url.length;
      re.lastIndex = last;
    }
    frag.appendChild(document.createTextNode(text.slice(last)));
    return frag;
  }
  // "📝 Title\nhttps://…/groups/<id>/?tab=posts#p<post>" (studygroups/views.py post_share_chat)
  function sharedPost(text) {
    var m = /(?:^|\n)📝 (.+)\n(https?:\/\/\S+\/groups\/\d+\/\?tab=posts#p\d+)\s*$/.exec(text);
    if (!m) { return null; }
    return { title: m[1], url: m[2].replace(/^https?:\/\/[^/]+/, ''), note: text.slice(0, m.index).trim() };
  }
  function fileIcon(name) {
    var ext = (name.split('.').pop() || '').toLowerCase();
    if (ext === 'pdf') { return ['bi-file-earmark-pdf-fill', 'is-pdf']; }
    if (['doc', 'docx'].indexOf(ext) > -1) { return ['bi-file-earmark-word-fill', 'is-doc']; }
    if (['ppt', 'pptx'].indexOf(ext) > -1) { return ['bi-file-earmark-slides-fill', 'is-ppt']; }
    if (['xls', 'xlsx', 'csv'].indexOf(ext) > -1) { return ['bi-file-earmark-spreadsheet-fill', 'is-xls']; }
    if (['zip', 'rar', '7z'].indexOf(ext) > -1) { return ['bi-file-earmark-zip-fill', 'is-zip']; }
    return ['bi-file-earmark-text-fill', 'is-file'];
  }
  function avatar(person) {
    // Initials on the person's colour underneath; their photo (if any) covers them.
    var a = el('span', 'gc-avatar is-initials', person ? person.initials : '');
    if (person) { a.style.backgroundColor = person.colour; }
    if (person && person.photo) { a.style.backgroundImage = 'url("' + person.photo.replace(/"/g, '%22') + '")'; a.style.color = 'transparent'; }
    return a;
  }

  function start(root, signal) {
    var cfgEl = document.getElementById('gcConfig');
    if (!root || !cfgEl) { return; }
    var cfg = JSON.parse(cfgEl.textContent);
    var me = cfg.me, conv = cfg.conversation;
    var list = root.querySelector('.js-gc-list'), input = root.querySelector('.js-gc-input');
    var starred = {};          // your starred message ids (Messages > Starred)
    var byId = {}, oldest = null, hasMore = false, loadingOlder = false, replyTo = null, reads = {};
    var ws = null, retry = 0, closed = false, typingSent = 0, typingStop = null, typers = {};

    // ---------------- drawing a message ----------------
    function render(msg) {
      if (msg.kind === 'system') {
        var sys = el('div', 'gc-msg is-system'); sys.dataset.id = msg.id; sys.dataset.ts = msg.created_at;
        sys.appendChild(el('span', 'gc-system', msg.content));
        return sys;
      }
      var mine = msg.sender && msg.sender.id === me.id;
      var row = el('div', 'gc-msg' + (mine ? ' is-mine' : ''));
      row.dataset.id = msg.id || ''; row.dataset.ts = msg.created_at; row.dataset.sender = msg.sender ? msg.sender.id : '';
      if (msg.client_id) { row.dataset.client = msg.client_id; }
      row.appendChild(avatar(msg.sender));
      var main = el('div', 'gc-main');
      var head = el('div', 'gc-head');
      head.appendChild(el('b', 'gc-name', msg.sender ? msg.sender.name : ''));
      head.appendChild(el('span', 'gc-time', '· ' + clock(msg.created_at)));
      if (msg.edited && !msg.is_deleted) { head.appendChild(el('span', 'gc-edited', '· edited')); }
      var role = msg.sender && cfg.roles[String(msg.sender.id)];
      if (role) { head.appendChild(el('span', 'gc-role', role)); }
      var pm = el('span', 'gc-pinmark'); pm.title = 'Pinned'; pm.appendChild(icon('bi-pin-angle-fill')); head.appendChild(pm);
      var sm = el('span', 'gc-starmark'); sm.title = 'Starred'; sm.appendChild(icon('bi-star-fill')); head.appendChild(sm);
      if (msg.id && starred[msg.id]) { row.classList.add('is-starred'); }
      main.appendChild(head);

      var bubble = el('div', 'gc-bubble');
      if (msg.is_deleted) {
        bubble.classList.add('is-deleted');
        bubble.appendChild(icon('bi-slash-circle'));
        bubble.appendChild(document.createTextNode(mine ? ' You deleted this message' : ' This message was deleted'));
      } else {
        if (msg.forwarded) { var fw = el('span', 'gc-forwarded'); fw.appendChild(icon('bi-forward-fill')); fw.appendChild(document.createTextNode(' Forwarded')); bubble.appendChild(fw); }
        if (msg.reply_to) {
          var q = el('button', 'gc-quote js-gc-jump'); q.type = 'button'; q.dataset.jump = msg.reply_to.id;
          q.appendChild(el('b', '', msg.reply_to.sender === me.id ? 'You' : msg.reply_to.name));
          q.appendChild(el('span', '', msg.reply_to.text));
          bubble.appendChild(q);
        }
        if (msg.attachment && msg.kind === 'video') {
          var v = el('video', 'gc-video'); v.src = msg.attachment.url; v.controls = true; v.preload = 'metadata'; v.playsInline = true;
          bubble.appendChild(v);
        } else if (msg.attachment && msg.kind === 'image') {
          var ph = el('a', 'gc-photo'); ph.href = msg.attachment.url; ph.target = '_blank'; ph.rel = 'noopener';
          var img = el('img'); img.src = msg.attachment.url; img.alt = 'Photo from ' + (msg.sender ? msg.sender.name : 'someone'); img.loading = 'lazy';
          img.addEventListener('load', function () { if (atBottom) { toBottom(); } });
          ph.appendChild(img); bubble.appendChild(ph);
        } else if (msg.attachment) {
          var fi = fileIcon(msg.attachment.name);
          var doc = el('a', 'gc-file'); doc.href = msg.attachment.url; doc.target = '_blank'; doc.rel = 'noopener'; doc.download = msg.attachment.name;
          var ic = el('span', 'gc-file-ico ' + fi[1]); ic.appendChild(icon(fi[0])); doc.appendChild(ic);
          var info = el('span', 'gc-file-info');
          info.appendChild(el('b', '', msg.attachment.name));
          var ext = (msg.attachment.name.split('.').pop() || '').toUpperCase();
          info.appendChild(el('small', '', [bytes(msg.attachment.size), ext].filter(Boolean).join(' · ')));
          doc.appendChild(info); bubble.appendChild(doc);
        }
        var shared = msg.kind !== 'poll' && msg.content && sharedPost(msg.content);
        if (msg.kind === 'poll' && msg.poll && window.UCPoll) {
          bubble.classList.add('has-poll');
          bubble.appendChild(UCPoll.card(msg, me.id));       // static/js/chat-polls.js
        } else if (shared) {
          // A post shared into the chat (Posts > Share to chat): a card that opens it.
          if (shared.note) { var sn = el('div', 'gc-text'); sn.appendChild(richText(shared.note)); bubble.appendChild(sn); }
          var card = el('a', 'gc-postcard'); card.href = shared.url;
          var ci = el('span', 'gc-postcard-ico'); ci.appendChild(icon('bi-file-text')); card.appendChild(ci);
          var cb = el('span', 'gc-postcard-body');
          cb.appendChild(el('small', '', 'Post in this group'));
          cb.appendChild(el('b', '', shared.title));
          cb.appendChild(el('span', 'gc-postcard-cta', 'Open the post and its comments →'));
          card.appendChild(cb);
          bubble.appendChild(card);
        } else if (msg.content) {
          var t = el('div', 'gc-text'); t.appendChild(richText(msg.content)); bubble.appendChild(t);
          if (window.UCChatMentions) { UCChatMentions.decorate(t, msg.mentions, me.id); }   // @mentions
        }
        if (window.UCChatMentions && UCChatMentions.mentionsMe(msg, me.id)) { row.classList.add('mentions-me'); }
        if (msg.status === 'pending') { bubble.appendChild(el('span', 'gc-pending', 'Sending…')); }
        if (msg.status === 'failed') { bubble.appendChild(el('span', 'gc-pending is-failed', msg.error || 'Not sent')); }
      }
      main.appendChild(bubble);

      var foot = el('div', 'gc-foot');
      var reacts = el('span', 'gc-reacts');
      (msg.reactions || []).forEach(function (r) {
        var chip = el('button', 'gc-react js-gc-react' + (r.users.indexOf(me.id) > -1 ? ' is-mine' : ''));
        chip.type = 'button'; chip.dataset.emoji = r.emoji;
        chip.setAttribute('aria-label', r.emoji + ' ' + r.count + (r.users.indexOf(me.id) > -1 ? ' — tap to remove yours' : ' — tap to add yours'));
        chip.appendChild(el('span', '', r.emoji)); chip.appendChild(el('b', '', String(r.count)));
        reacts.appendChild(chip);
      });
      foot.appendChild(reacts);
      if (msg.id && !msg.is_deleted) {
        var add = el('button', 'gc-act js-gc-quick'); add.type = 'button'; add.setAttribute('aria-label', 'React'); add.appendChild(icon('bi-emoji-smile'));
        var rep = el('button', 'gc-act js-gc-replybtn'); rep.type = 'button'; rep.setAttribute('aria-label', 'Reply'); rep.appendChild(icon('bi-reply'));
        foot.appendChild(add); foot.appendChild(rep);
        var st = el('button', 'gc-act js-gc-star' + (starred[msg.id] ? ' is-on' : '')); st.type = 'button';
        st.setAttribute('aria-label', starred[msg.id] ? 'Unstar' : 'Star — find it later in Messages → Starred'); st.title = starred[msg.id] ? 'Unstar' : 'Star';
        st.appendChild(icon(starred[msg.id] ? 'bi-star-fill' : 'bi-star')); foot.appendChild(st);
        if (window.UCForward && msg.kind !== 'system') {
          var fwd = el('button', 'gc-act js-gc-forward'); fwd.type = 'button'; fwd.setAttribute('aria-label', 'Forward to another chat'); fwd.title = 'Forward';
          fwd.appendChild(icon('bi-forward')); foot.appendChild(fwd);
        }
        if (cfg.posts && msg.content && msg.kind !== 'system' && msg.kind !== 'poll' && !sharedPost(msg.content)) {
          // Useful answer? Keep it: start a post with this message's text.
          var mk = el('a', 'gc-act'); mk.href = '?tab=posts&from_msg=' + msg.id + '#sgComposer';
          mk.setAttribute('aria-label', 'Make a post from this message'); mk.title = 'Make a post from this (so people can find it later)';
          mk.appendChild(icon('bi-journal-plus'));
          foot.appendChild(mk);
        }
        if (window.UCPins && UCPins.canPin(conv)) {
          var pin = el('button', 'gc-act js-gc-pin'); pin.type = 'button'; pin.appendChild(icon('bi-pin-angle'));
          foot.appendChild(pin);
        }
        if (mine && canEdit(msg)) {
          var ed = el('button', 'gc-act js-gc-edit'); ed.type = 'button'; ed.setAttribute('aria-label', 'Edit this message'); ed.title = 'Edit (for 15 minutes after sending)';
          ed.appendChild(icon('bi-pencil')); foot.appendChild(ed);
        }
        if (mine) { var del = el('button', 'gc-act js-gc-delete'); del.type = 'button'; del.setAttribute('aria-label', 'Delete for everyone'); del.appendChild(icon('bi-trash3')); foot.appendChild(del); }
      }
      if (mine && msg.id && !msg.is_deleted) { foot.appendChild(el('span', 'gc-seen js-gc-seen')); }
      main.appendChild(foot);
      row.appendChild(main);
      row._msg = msg;
      markPin(row);
      return row;
    }

    // ---------------- pinned messages (static/js/chat-pins.js) ----------------
    var pinBar = root.querySelector('.js-gc-pins');
    function markPin(row) {
      if (!window.UCPins || !row._msg || !row._msg.id) { return; }
      var on = UCPins.isPinned(conv, row._msg.id);
      row.classList.toggle('is-pinned', on);
      var b = row.querySelector('.js-gc-pin');
      if (b) {
        b.querySelector('i').className = 'bi ' + (on ? 'bi-pin-angle-fill' : 'bi-pin-angle');
        b.setAttribute('aria-label', on ? 'Unpin this message' : 'Pin this message to the top of the chat');
        b.title = on ? 'Unpin' : 'Pin to the top of the chat';
        b.classList.toggle('is-on', on);
      }
    }
    function refreshPins() {
      if (!window.UCPins) { return; }
      UCPins.render(pinBar, conv, function (id) { jumpTo(id); });
      list.querySelectorAll('.gc-msg[data-id]').forEach(markPin);
    }
    document.addEventListener('uc:pins', function (e) { if (e.detail.conversation === conv) { refreshPins(); } }, { signal: signal });

    // Day separators, and messages from the same person grouped together.
    function relayout() {
      list.querySelectorAll('.gc-day').forEach(function (d) { d.remove(); });
      var prev = null, prevDay = '';
      list.querySelectorAll('.gc-msg').forEach(function (m) {
        var ts = m.dataset.ts, day = new Date(ts).toDateString();
        if (day !== prevDay) { var d = el('div', 'gc-day'); d.appendChild(el('span', '', dayLabel(ts))); list.insertBefore(d, m); prevDay = day; prev = null; }
        var cont = prev && !m.classList.contains('is-system') && !prev.classList.contains('is-system') && prev.dataset.sender === m.dataset.sender &&
          (new Date(ts) - new Date(prev.dataset.ts)) < GROUP_GAP;
        m.classList.toggle('is-cont', !!cont);
        prev = m;
      });
      updateSeen();
    }

    var atBottom = true;
    function toBottom() { list.scrollTop = list.scrollHeight; }
    list.addEventListener('scroll', function () {
      atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
      if (list.scrollTop < 60) { loadOlder(); }
      if (atBottom) { markRead(); }
    }, { signal: signal });

    function add(msg) {
      if (msg.client_id) {
        var pend = list.querySelector('.gc-msg[data-client="' + msg.client_id + '"]');
        if (pend) { var fresh = render(msg); pend.replaceWith(fresh); if (msg.id) { byId[msg.id] = fresh; } relayout(); return; }
      }
      if (msg.id && byId[msg.id]) { return; }
      var wasBottom = atBottom || (msg.sender && msg.sender.id === me.id);
      var node = render(msg);
      list.appendChild(node);
      if (msg.id) { byId[msg.id] = node; }
      relayout();
      if (wasBottom) { toBottom(); markRead(); }
      else if (msg.sender && msg.sender.id !== me.id) { showNewBelow(); }
    }
    var newBelow = null;
    function showNewBelow() {
      if (!newBelow) {
        newBelow = el('button', 'gc-newbelow', 'New messages ↓'); newBelow.type = 'button';
        newBelow.addEventListener('click', function () { toBottom(); newBelow.hidden = true; markRead(); });
        root.insertBefore(newBelow, root.querySelector('.js-gc-composer'));
      }
      newBelow.hidden = false;
    }

    // ---------------- history ----------------
    function getJSON(url) {
      return fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' }, signal: signal })
        .then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.json(); });
    }
    function loadFirst() {
      return getJSON('/messages/c/' + conv + '/history/').then(function (res) {
        if (window.UCPins) { UCPins.set(conv, res.pins, res.can_pin); }
        (res.starred || []).forEach(function (id) { starred[id] = true; });
        list.innerHTML = '';
        if (!res.messages.length) {
          var empty = el('div', 'gc-empty');
          empty.appendChild(icon('bi-chat-dots'));
          empty.appendChild(el('b', '', 'No messages yet'));
          empty.appendChild(el('span', '', 'Say hello, share lecture notes or ask a question — everyone in the group sees it straight away.'));
          list.appendChild(empty);
        }
        res.messages.forEach(function (m) { var n = render(m); list.appendChild(n); if (m.id) { byId[m.id] = n; } });
        oldest = res.messages.length ? res.messages[0].id : null; hasMore = res.has_more;
        relayout(); toBottom(); markRead(); refreshSeen(); refreshPins();
        if (location.hash === '#search') { openSearch(); }
        // Opened from a notification (?m=<message id>, e.g. you were @mentioned): go to it.
        var target = parseInt(new URLSearchParams(location.search).get('m'), 10);
        if (target) { jumpTo(target); }
      }).catch(function (e) { if (e.name !== 'AbortError') { list.innerHTML = ''; list.appendChild(el('div', 'gc-empty', 'Could not load the chat. Refresh the page to try again.')); } });
    }
    function loadOlder() {
      if (!hasMore || loadingOlder || !oldest) { return Promise.resolve(); }
      loadingOlder = true;
      var h = list.scrollHeight;
      return getJSON('/messages/c/' + conv + '/history/?before=' + oldest).then(function (res) {
        (res.starred || []).forEach(function (id) { starred[id] = true; });
        var frag = document.createDocumentFragment();
        res.messages.forEach(function (m) { var n = render(m); frag.appendChild(n); if (m.id) { byId[m.id] = n; } });
        var firstMsg = list.querySelector('.gc-msg');
        list.insertBefore(frag, firstMsg ? (firstMsg.previousElementSibling && firstMsg.previousElementSibling.classList.contains('gc-day') ? firstMsg.previousElementSibling : firstMsg) : null);
        if (res.messages.length) { oldest = res.messages[0].id; }
        hasMore = res.has_more;
        relayout();
        list.scrollTop = list.scrollHeight - h;
      }).catch(function () {}).then(function () { loadingOlder = false; });
    }
    function jumpTo(id, tries) {
      var node = byId[id];
      if (node) {
        node.scrollIntoView({ block: 'center', behavior: 'smooth' });
        node.classList.add('is-found'); setTimeout(function () { node.classList.remove('is-found'); }, 2400);
        return;
      }
      if ((tries || 0) > 8 || !hasMore) { toast("That message is too far back to show here — open the chat in Messages."); return; }
      loadOlder().then(function () { jumpTo(id, (tries || 0) + 1); });
    }

    // ---------------- "Seen by N" under your latest message ----------------
    function updateSeen() {
      list.querySelectorAll('.js-gc-seen').forEach(function (s) { s.textContent = ''; s.hidden = true; });
      var mineMsgs = list.querySelectorAll('.gc-msg.is-mine');
      var last = mineMsgs[mineMsgs.length - 1];
      if (!last || !last._msg || !last._msg.id) { return; }
      var at = new Date(last._msg.created_at), n = 0;
      Object.keys(reads).forEach(function (k) { if (reads[k] && new Date(reads[k]) >= at) { n++; } });
      var s = last.querySelector('.js-gc-seen');
      if (!s) { return; }
      s.hidden = false;
      s.textContent = '';
      s.appendChild(document.createTextNode(n ? 'Seen by ' + n + ' ' : 'Sent '));
      s.appendChild(icon(n ? 'bi-check2-all' : 'bi-check2'));
      s.classList.toggle('is-read', n > 0);
    }
    var seenTimer = null;
    function refreshSeen() {
      clearTimeout(seenTimer);
      seenTimer = setTimeout(function () {
        getJSON('/groups/' + cfg.group + '/chat/seen/').then(function (res) { reads = res.reads || {}; updateSeen(); }).catch(function () {});
      }, 400);
    }

    // ---------------- the WebSocket ----------------
    var queue = [];
    function connect() {
      if (closed) { return; }
      try { ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/chat/'); }
      catch (e) { return later(); }
      ws.onopen = function () { retry = 0; root.classList.remove('is-offline'); var p = queue; queue = []; p.forEach(send); markRead(); };
      ws.onmessage = function (e) { var d; try { d = JSON.parse(e.data); } catch (err) { return; } handle(d); };
      ws.onclose = function () { if (!closed) { root.classList.add('is-offline'); later(); } };
    }
    function later() { setTimeout(connect, Math.min(15000, 1000 * Math.pow(2, retry++))); }
    function send(obj) {
      if (ws && ws.readyState === 1) { ws.send(JSON.stringify(obj)); return true; }
      if (obj.type === 'message') { queue.push(obj); }
      return false;
    }
    if (signal) { signal.addEventListener('abort', function () { closed = true; if (ws) { ws.close(); } }); }

    function handle(d) {
      if (d.type === 'message' && d.message && d.message.conversation === conv) {
        add(d.message);
        if (d.message.sender && typers[d.message.sender.id]) { delete typers[d.message.sender.id]; showTyping(); }
      } else if (d.type === 'reaction' && d.conversation === conv && byId[d.message]) {
        var m = byId[d.message]._msg; m.reactions = d.reactions;
        var n = render(m); byId[d.message].replaceWith(n); byId[d.message] = n; relayout();
      } else if (d.type === 'edited' && d.conversation === conv) {
        showEdited(d.message);
      } else if (d.type === 'pins' && d.conversation === conv) {
        if (window.UCPins) { UCPins.set(conv, d.pins); refreshPins(); }
      } else if (d.type === 'poll' && d.conversation === conv) {
        if (byId[d.message]) { byId[d.message]._msg.poll = d.poll; }
        if (window.UCPoll) { UCPoll.update(d.message, d.poll); }
      } else if (d.type === 'deleted' && d.conversation === conv && byId[d.message]) {
        var dm = byId[d.message]._msg; dm.is_deleted = true; dm.content = ''; dm.attachment = null; dm.reactions = []; dm.reply_to = null;
        var dn = render(dm); byId[d.message].replaceWith(dn); byId[d.message] = dn; relayout();
      } else if (d.type === 'typing' && d.conversation === conv && d.user !== me.id) {
        if (d.state) { typers[d.user] = { name: d.name, until: Date.now() + 5000 }; } else { delete typers[d.user]; }
        showTyping();
      } else if (d.type === 'receipt' && d.conversation === conv) {
        refreshSeen();
      } else if (d.type === 'seen' && d.conversation === conv && d.user !== me.id) {
        reads[String(d.user)] = d.at; updateSeen();
      } else if (d.type === 'error' && d.client_id) {
        var p = list.querySelector('.gc-msg[data-client="' + d.client_id + '"]');
        if (p) { p._msg.status = 'failed'; p._msg.error = d.error; p.replaceWith(render(p._msg)); }
        toast(d.error || 'Could not send.', 'error');
      }
    }
    var typingBox = root.querySelector('.js-gc-typing');
    function showTyping() {
      var now = Date.now(), names = [];
      Object.keys(typers).forEach(function (k) { if (typers[k].until > now) { names.push(typers[k].name); } else { delete typers[k]; } });
      typingBox.hidden = !names.length;
      typingBox.textContent = names.length === 1 ? names[0] + ' is typing…' : names.length === 2 ? names.join(' and ') + ' are typing…' : names.length ? 'Several people are typing…' : '';
    }
    var typingTick = setInterval(showTyping, 2000);
    if (signal) { signal.addEventListener('abort', function () { clearInterval(typingTick); }); }

    function markRead() {
      if (document.visibilityState !== 'visible' || !atBottom) { return; }
      send({ type: 'read', conversation: conv });
    }
    document.addEventListener('visibilitychange', markRead, { signal: signal });

    // ---------------- editing your message (chat/editing.py) ----------------
    var EDITABLE = ['text', 'image', 'video', 'file'], editing = null;
    function canEdit(msg) {
      return !!msg.id && !msg.is_deleted && EDITABLE.indexOf(msg.kind) > -1 && Date.now() - new Date(msg.created_at) <= 15 * 60000;
    }
    function startEdit(msg) {
      if (!canEdit(msg)) { toast('Messages can only be edited for 15 minutes after sending.', 'error'); return; }
      replyTo = null; editing = msg;
      var bar = root.querySelector('.js-gc-reply');
      bar.querySelector('.js-gc-reply-name').textContent = 'Editing your message';
      bar.querySelector('.js-gc-reply-text').textContent = msg.content || (msg.attachment ? msg.attachment.name : '');
      bar.classList.add('is-editing');
      bar.hidden = false;
      input.value = msg.content || '';
      grow(); input.focus(); input.setSelectionRange(input.value.length, input.value.length);
    }
    function stopEdit(clear) {
      if (!editing) { return; }
      editing = null;
      var bar = root.querySelector('.js-gc-reply');
      bar.hidden = true; bar.classList.remove('is-editing');
      if (clear) { input.value = ''; grow(); }
    }
    function saveEdit() {
      var msg = editing, text = input.value.trim();
      if (text === (msg.content || '')) { stopEdit(true); return; }
      var body = new URLSearchParams(); body.append('content', text);
      fetch('/messages/m/' + msg.id + '/edit/', { method: 'POST', body: body, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { if (!r.ok) { throw new Error(d.error || 'Could not edit — try again.'); } return d; }); })
        .then(function (d) { stopEdit(true); showEdited(d.message); })
        .catch(function (err) { toast(err.message, 'error'); });
    }
    function showEdited(m) {
      var node = byId[m.id];
      if (!node) { return; }
      var fresh = render(m); node.replaceWith(fresh); byId[m.id] = fresh; relayout();
    }

    // ---------------- sending ----------------
    function grow() { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 140) + 'px'; }
    function replyInfo() {
      if (!replyTo) { return null; }
      return { id: replyTo.id, name: replyTo.sender ? replyTo.sender.name : '', sender: replyTo.sender ? replyTo.sender.id : null,
        kind: replyTo.kind, text: replyTo.content || (replyTo.attachment ? replyTo.attachment.name : '') };
    }
    function setReply(msg) {
      stopEdit(true);
      replyTo = msg;
      var bar = root.querySelector('.js-gc-reply');
      bar.querySelector('.js-gc-reply-name').textContent = msg.sender && msg.sender.id === me.id ? 'Replying to yourself' : 'Replying to ' + (msg.sender ? msg.sender.name : '');
      bar.querySelector('.js-gc-reply-text').textContent = msg.content || (msg.attachment ? msg.attachment.name : '');
      bar.hidden = false;
      input.focus();
    }
    function clearReply() { if (editing) { stopEdit(true); return; } replyTo = null; root.querySelector('.js-gc-reply').hidden = true; }

    function sendText() {
      if (editing) { saveEdit(); return; }
      var text = input.value.trim();
      if (!text) { return; }
      if (text.length > 4000) { toast('Messages can be up to 4000 characters.', 'error'); return; }
      var cid = uid();
      var empty = list.querySelector('.gc-empty'); if (empty) { empty.remove(); }
      add({ id: null, client_id: cid, conversation: conv, kind: 'text', sender: me, content: text, created_at: new Date().toISOString(),
        status: 'pending', reactions: [], attachment: null, reply_to: replyInfo() });
      send({ type: 'message', conversation: conv, content: text, client_id: cid, reply_to: replyTo ? replyTo.id : null });
      clearReply();
      input.value = ''; grow(); stopTyping();
      input.focus();
    }
    function upload(file) {
      if (!file) { return; }
      if (file.size > 25 * 1024 * 1024) { toast('Files must be 25 MB or smaller.', 'error'); return; }
      var cid = uid();
      var empty = list.querySelector('.gc-empty'); if (empty) { empty.remove(); }
      add({ id: null, client_id: cid, conversation: conv, kind: 'text', sender: me, content: 'Uploading ' + file.name + '…',
        created_at: new Date().toISOString(), status: 'pending', reactions: [], attachment: null, reply_to: replyInfo() });
      var form = new FormData();
      form.append('file', file, file.name);
      form.append('kind', /^image\//.test(file.type) ? 'image' : 'file');
      var caption = input.value.trim();
      if (caption) { form.append('caption', caption); input.value = ''; grow(); }
      if (replyTo) { form.append('reply_to', replyTo.id); clearReply(); }
      var xhr = new XMLHttpRequest();
      xhr.open('POST', '/messages/c/' + conv + '/upload/');
      xhr.setRequestHeader('X-CSRFToken', csrf());
      xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
      xhr.upload.onprogress = function (e) {
        var p = list.querySelector('.gc-msg[data-client="' + cid + '"] .gc-text');
        if (p && e.lengthComputable) { p.textContent = 'Uploading ' + file.name + '… ' + Math.round(e.loaded / e.total * 100) + '%'; }
      };
      xhr.onload = function () {
        var res = {}; try { res = JSON.parse(xhr.responseText); } catch (err) { /* ignore */ }
        var p = list.querySelector('.gc-msg[data-client="' + cid + '"]');
        if (xhr.status >= 200 && xhr.status < 300) {
          if (p) { p.remove(); }
          if (res.message) { add(res.message); }          // also arrives over the WebSocket; shown once
        } else {
          if (p) { p._msg.status = 'failed'; p._msg.error = res.error || 'Upload failed'; p.replaceWith(render(p._msg)); }
          toast(res.error || 'Upload failed.', 'error');
        }
      };
      xhr.onerror = function () { toast('Upload failed — check your connection.', 'error'); };
      xhr.send(form);
    }
    function typing() {
      var now = Date.now();
      if (now - typingSent > 2500) { send({ type: 'typing', conversation: conv, state: true }); typingSent = now; }
      clearTimeout(typingStop); typingStop = setTimeout(stopTyping, 3000);
    }
    function stopTyping() { clearTimeout(typingStop); if (typingSent) { send({ type: 'typing', conversation: conv, state: false }); } typingSent = 0; }

    root.querySelector('.js-gc-composer').addEventListener('submit', function (e) { e.preventDefault(); sendText(); }, { signal: signal });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && window.matchMedia('(hover:hover)').matches) { e.preventDefault(); sendText(); }
      if (e.key === 'Escape') { clearReply(); }
    }, { signal: signal });
    input.addEventListener('input', function () { grow(); if (input.value.trim()) { typing(); } }, { signal: signal });
    root.addEventListener('change', function (e) {
      var f = e.target.closest('.js-gc-file');
      if (!f) { return; }
      Array.prototype.slice.call(f.files || []).forEach(upload);
      f.value = '';
      root.querySelector('.js-gc-attach-menu').hidden = true;
    }, { signal: signal });

    // Emoji panel
    var emojiBox = root.querySelector('.js-gc-emoji');
    EMOJI.forEach(function (e) { var b = el('button', 'gc-emoji-btn', e); b.type = 'button'; emojiBox.appendChild(b); });

    // ---------------- clicks ----------------
    var pop = null;
    function closePop() { if (pop) { pop.remove(); pop = null; } }
    function quickReactions(row, anchor) {
      closePop();
      var msg = row._msg;
      pop = el('div', 'gc-pop');
      QUICK.forEach(function (emoji) {
        var b = el('button', 'gc-pop-btn', emoji); b.type = 'button';
        if ((msg.reactions || []).some(function (r) { return r.emoji === emoji && r.users.indexOf(me.id) > -1; })) { b.classList.add('is-mine'); }
        b.addEventListener('click', function () { send({ type: 'react', message: msg.id, emoji: emoji }); closePop(); });
        pop.appendChild(b);
      });
      document.body.appendChild(pop);
      var r = anchor.getBoundingClientRect();
      pop.style.left = Math.max(8, Math.min(window.innerWidth - pop.offsetWidth - 8, r.left - 10)) + 'px';
      pop.style.top = Math.max(8, r.top - pop.offsetHeight - 8) + 'px';
    }

    document.addEventListener('click', function (e) {
      var t = e.target;
      if (pop && !pop.contains(t) && !t.closest('.js-gc-quick')) { closePop(); }
      if (!root.contains(t) && !t.closest('.js-gc-search-open')) { return; }
      var b;
      if ((b = t.closest('.js-gc-search-open'))) { e.preventDefault(); openSearch(); return; }
      if ((b = t.closest('.js-gc-quick'))) { quickReactions(b.closest('.gc-msg'), b); return; }
      if ((b = t.closest('.js-gc-react'))) { send({ type: 'react', message: b.closest('.gc-msg')._msg.id, emoji: b.dataset.emoji }); return; }
      if ((b = t.closest('.js-gc-star'))) {
        var sRow = b.closest('.gc-msg'), sMsg = sRow._msg, want = !starred[sMsg.id];
        var body = new URLSearchParams(); body.append('star', want ? '1' : '0');
        fetch('/messages/m/' + sMsg.id + '/star/', { method: 'POST', body: body, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' } })
          .then(function (r) { if (!r.ok) { throw new Error(); } return r.json(); })
          .then(function (d) {
            if (d.starred) { starred[sMsg.id] = true; } else { delete starred[sMsg.id]; }
            var fresh = render(sMsg); byId[sMsg.id].replaceWith(fresh); byId[sMsg.id] = fresh; relayout();
            toast(d.starred ? 'Starred — find it in Messages → Starred.' : 'Unstarred.');
          })
          .catch(function () { toast('Could not star that — try again.', 'error'); });
        return;
      }
      if ((b = t.closest('.js-gc-forward'))) { UCForward.open(b.closest('.gc-msg')._msg); return; }
      if ((b = t.closest('.js-gc-edit'))) { startEdit(b.closest('.gc-msg')._msg); return; }
      if ((b = t.closest('.js-gc-pin'))) {
        var pinned = UCPins.isPinned(conv, b.closest('.gc-msg')._msg.id);
        UCPins.toggle(conv, b.closest('.gc-msg')._msg.id)
          .then(function () { toast(pinned ? 'Message unpinned.' : 'Pinned to the top of the chat for everyone.'); })
          .catch(function (err) { toast(err.message, 'error'); });
        return;
      }
      if ((b = t.closest('.js-gc-replybtn'))) { setReply(b.closest('.gc-msg')._msg); return; }
      if ((b = t.closest('.js-gc-delete'))) {
        if (window.confirm('Delete this message for everyone?')) { send({ type: 'delete', message: b.closest('.gc-msg')._msg.id }); }
        return;
      }
      if ((b = t.closest('.js-gc-jump'))) { jumpTo(parseInt(b.dataset.jump, 10)); return; }
      if ((b = t.closest('.js-gc-reply-cancel'))) { clearReply(); return; }
      if ((b = t.closest('.js-gc-poll'))) {
        root.querySelector('.js-gc-attach-menu').hidden = true;
        if (window.UCPoll) { UCPoll.open(conv, { replyTo: replyTo ? replyTo.id : '', onSent: function (m) { clearReply(); add(m); } }); }
        return;
      }
      if ((b = t.closest('.js-gc-attach'))) { var m = root.querySelector('.js-gc-attach-menu'); m.hidden = !m.hidden; emojiBox.hidden = true; return; }
      if ((b = t.closest('.js-gc-emoji-toggle'))) { emojiBox.hidden = !emojiBox.hidden; root.querySelector('.js-gc-attach-menu').hidden = true; return; }
      if ((b = t.closest('.gc-emoji-btn'))) {
        var s = input.selectionStart || input.value.length;
        input.value = input.value.slice(0, s) + b.textContent + input.value.slice(input.selectionEnd || s);
        input.focus(); input.selectionStart = input.selectionEnd = s + b.textContent.length; grow();
        return;
      }
      if ((b = t.closest('.js-gc-search-close'))) { closeSearch(); return; }
      if ((b = t.closest('.js-gc-result'))) { closeSearch(); jumpTo(parseInt(b.dataset.id, 10)); return; }
    }, { signal: signal });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { closePop(); } }, { signal: signal });

    // ---------------- search ----------------
    var searchForm = root.querySelector('.js-gc-search'), searchInput = root.querySelector('.js-gc-search-input');
    var results = root.querySelector('.js-gc-search-results'), searchTimer = null;
    function openSearch() { searchForm.hidden = false; searchInput.focus(); root.scrollIntoView({ block: 'start', behavior: 'smooth' }); }
    function closeSearch() { searchForm.hidden = true; results.hidden = true; searchInput.value = ''; }
    searchForm.addEventListener('submit', function (e) { e.preventDefault(); }, { signal: signal });
    searchInput.addEventListener('input', function () {
      clearTimeout(searchTimer);
      var q = searchInput.value.trim();
      if (q.length < 2) { results.hidden = true; return; }
      searchTimer = setTimeout(function () {
        getJSON('/groups/' + cfg.group + '/chat/search/?q=' + encodeURIComponent(q)).then(function (res) {
          results.innerHTML = '';
          if (!res.results.length) { results.appendChild(el('p', 'gc-noresults', 'No messages with “' + q + '”.')); }
          res.results.forEach(function (m) {
            var r = el('button', 'gc-result js-gc-result'); r.type = 'button'; r.dataset.id = m.id;
            r.appendChild(el('b', '', (m.sender ? m.sender.name : '') + ' · ' + new Date(m.created_at).toLocaleDateString([], { day: 'numeric', month: 'short' })));
            r.appendChild(el('span', '', m.content || (m.attachment ? m.attachment.name : '')));
            results.appendChild(r);
          });
          results.hidden = false;
        }).catch(function () {});
      }, 250);
    }, { signal: signal });

    loadFirst();
    connect();
  }

  function init(doc, signal) {
    var root = document.getElementById('groupChat');
    if (root && !root.dataset.ready) { root.dataset.ready = '1'; start(root, signal); }
  }
  if (window.UC && UC.onPage) { UC.onPage(init); }
  else if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', function () { init(document, null); }); }
  else { init(document, null); }
})();

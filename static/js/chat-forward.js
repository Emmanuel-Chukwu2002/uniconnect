/* ---------------------------------------------------------------
   "Forward to…" (chat/forwarding.py) — shared by the group page's Chat
   tab (group-chat.js) and Messages (chat/conversation.js).

   UCForward.open(message)  shows your chats (search at the top); tick up
   to 5 and Send. Each gets a copy marked "Forwarded".
   --------------------------------------------------------------- */
(function () {
  'use strict';
  if (window.UCForward) { return; }
  var MAX = 5, modal = null, current = null, picked = [], timer = null, req = 0;

  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ''; }
  function toast(t, k) { if (window.showToast) { window.showToast(t, k); } }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) { e.className = cls; } if (text != null) { e.textContent = text; } return e; }

  function preview(msg) {
    var labels = { image: '📷 Photo', video: '🎥 Video', audio: '🎤 Voice message', poll: '📊 Poll: ' };
    if (msg.kind === 'file') { return '📄 ' + (msg.attachment ? msg.attachment.name : 'Document') + (msg.content ? ' — ' + msg.content : ''); }
    if (msg.kind === 'poll') { return labels.poll + (msg.content || ''); }
    return (labels[msg.kind] ? labels[msg.kind] + (msg.content ? ' — ' : '') : '') + (msg.content || '');
  }

  function build() {
    modal = el('div', 'modal fade fw-modal');
    modal.tabIndex = -1;
    modal.setAttribute('aria-labelledby', 'fwTitle');
    modal.innerHTML =
      '<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><div class="modal-content">' +
      '<div class="modal-header"><h2 class="modal-title" id="fwTitle"><i class="bi bi-forward-fill"></i> Forward to…</h2>' +
      '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>' +
      '<div class="fw-top"><div class="fw-quote js-fw-quote"></div>' +
      '<label class="fw-search"><i class="bi bi-search" aria-hidden="true"></i><input type="search" class="js-fw-q" placeholder="Search your chats" aria-label="Search your chats"></label></div>' +
      '<div class="modal-body"><div class="fw-list js-fw-list" role="group" aria-label="Your chats"></div></div>' +
      '<div class="modal-footer"><span class="fw-count js-fw-count">Choose up to ' + MAX + ' chats</span>' +
      '<button type="button" class="btn btn-primary js-fw-send" disabled><i class="bi bi-send-fill"></i> Send</button></div>' +
      '</div></div>';
    document.body.appendChild(modal);
    modal.querySelector('.js-fw-q').addEventListener('input', function (e) {
      clearTimeout(timer);
      var q = e.target.value;
      timer = setTimeout(function () { load(q); }, 200);
    });
    modal.addEventListener('change', function (e) {
      var box = e.target.closest('.js-fw-pick');
      if (!box) { return; }
      var id = parseInt(box.value, 10);
      if (box.checked) {
        if (picked.length >= MAX) { box.checked = false; toast('You can forward to up to ' + MAX + ' chats at a time.', 'error'); return; }
        picked.push(id);
      } else {
        picked = picked.filter(function (x) { return x !== id; });
      }
      update();
    });
    modal.querySelector('.js-fw-send').addEventListener('click', send);
  }

  function update() {
    var n = picked.length;
    modal.querySelector('.js-fw-count').textContent = n ? n + ' chosen' + (n === MAX ? ' (the most at once)' : '') : 'Choose up to ' + MAX + ' chats';
    modal.querySelector('.js-fw-send').disabled = !n;
  }

  function avatar(c) {
    var a = el('span', 'fw-ava');
    if (c.photo) { a.style.backgroundImage = 'url(' + c.photo + ')'; }
    else if (c.is_group) { a.appendChild(el('i', 'bi bi-people-fill')); }
    else { a.textContent = c.initials; a.style.background = c.colour; }
    return a;
  }

  function load(q) {
    var list = modal.querySelector('.js-fw-list'), mine = ++req;
    fetch('/messages/forward/chats/?q=' + encodeURIComponent(q || ''), { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (mine !== req) { return; }
        list.innerHTML = '';
        var chats = (d.chats || []).filter(function (c) { return !(current.kind === 'poll' && !c.is_group); });
        if (!chats.length) { list.appendChild(el('p', 'fw-empty', q ? 'No chats match “' + q + '”.' : 'No chats to forward to yet.')); return; }
        chats.forEach(function (c) {
          var row = el('label', 'fw-row');
          var box = el('input', 'js-fw-pick'); box.type = 'checkbox'; box.value = c.id; box.checked = picked.indexOf(c.id) > -1;
          row.appendChild(box);
          row.appendChild(avatar(c));
          var t = el('span', 'fw-name', c.title);
          row.appendChild(t);
          if (c.is_group) { row.appendChild(el('small', 'fw-sub', c.community ? c.community : 'Group')); }   // same-named groups: which community
          if (c.id === current.conversation) { row.appendChild(el('small', 'fw-here', 'This chat')); }
          list.appendChild(row);
        });
      })
      .catch(function () { list.innerHTML = ''; list.appendChild(el('p', 'fw-empty', 'Could not load your chats — check your connection.')); });
  }

  function send() {
    var btn = modal.querySelector('.js-fw-send');
    btn.disabled = true;
    var body = new URLSearchParams();
    picked.forEach(function (id) { body.append('to', id); });
    fetch('/messages/m/' + current.id + '/forward/', { method: 'POST', body: body, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { if (!r.ok) { throw new Error(d.error || 'Could not forward — try again.'); } return d; }); })
      .then(function (d) { bootstrap.Modal.getOrCreateInstance(modal).hide(); toast(d.message); })
      .catch(function (err) { toast(err.message, 'error'); update(); });
  }

  function open(msg) {
    if (!window.bootstrap || !msg || !msg.id) { return; }
    if (!modal) { build(); }
    current = msg; picked = [];
    modal.querySelector('.js-fw-quote').textContent = preview(msg);
    modal.querySelector('.js-fw-q').value = '';
    modal.querySelector('.js-fw-list').innerHTML = '<div class="fw-empty"><span class="spinner-border spinner-border-sm"></span></div>';
    update();
    bootstrap.Modal.getOrCreateInstance(modal).show();
    load('');
  }

  window.UCForward = { open: open };
})();

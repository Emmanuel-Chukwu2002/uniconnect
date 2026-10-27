/* ---------------------------------------------------------------
   Pinned messages bar (chat/pins.py) — shared by the group page's Chat
   tab (group-chat.js) and Messages (chat/conversation.js).

   UCPins.set(conv, pins, canPin)   remember the chat's pins (newest first)
   UCPins.render(bar, conv, onJump) draw the bar: "Pinned message 1 of 3",
                                    who wrote it and the start of it. Tapping
                                    it jumps to that message and moves on to
                                    the next pin (like WhatsApp).
   UCPins.isPinned(conv, id)
   UCPins.toggle(conv, id)          pin / unpin; resolves with the new pins
   --------------------------------------------------------------- */
(function () {
  'use strict';
  if (window.UCPins) { return; }
  var chats = {};   // conv id -> { pins: [...], canPin: bool, at: index shown }

  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ''; }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) { e.className = cls; } if (text != null) { e.textContent = text; } return e; }
  function icon(name) { return el('i', 'bi ' + name); }
  function chat(conv) { return chats[conv] || (chats[conv] = { pins: [], canPin: false, at: 0 }); }

  function set(conv, pins, canPin) {
    var c = chat(conv);
    c.pins = pins || [];
    if (canPin != null) { c.canPin = !!canPin; }
    if (c.at >= c.pins.length) { c.at = 0; }
  }

  function render(bar, conv, onJump) {
    if (!bar) { return; }
    var c = chat(conv);
    bar.innerHTML = '';
    bar.hidden = !c.pins.length;
    if (!c.pins.length) { return; }
    var p = c.pins[c.at];
    if (c.pins.length > 1) {
      // One dash per pin; the one showing is darker.
      var dots = el('span', 'pb-dots');
      c.pins.forEach(function (_, i) { dots.appendChild(el('span', i === c.at ? 'is-on' : '')); });
      bar.appendChild(dots);
    }
    var go = el('button', 'pb-main');
    go.type = 'button';
    go.setAttribute('aria-label', 'Pinned message ' + (c.at + 1) + ' of ' + c.pins.length + ': ' + p.name + ': ' + p.text + '. Go to it.');
    go.appendChild(icon('bi-pin-angle-fill'));
    var body = el('span', 'pb-body');
    body.appendChild(el('small', '', c.pins.length > 1 ? 'Pinned message ' + (c.at + 1) + ' of ' + c.pins.length : 'Pinned message'));
    var line = el('span', 'pb-line');
    if (p.name) { line.appendChild(el('b', '', p.name + ': ')); }
    line.appendChild(document.createTextNode(p.text || 'Message'));
    body.appendChild(line);
    go.appendChild(body);
    go.addEventListener('click', function () {
      if (onJump) { onJump(p.id); }
      if (c.pins.length > 1) { c.at = (c.at + 1) % c.pins.length; render(bar, conv, onJump); }
    });
    bar.appendChild(go);
    if (c.canPin) {
      var x = el('button', 'pb-unpin');
      x.type = 'button';
      x.title = 'Unpin this message';
      x.setAttribute('aria-label', 'Unpin this message');
      x.appendChild(icon('bi-pin-angle'));
      x.addEventListener('click', function () {
        x.disabled = true;
        toggle(conv, p.id).catch(function (err) { x.disabled = false; if (window.showToast) { window.showToast(err.message, 'error'); } });
      });
      bar.appendChild(x);
    }
  }

  function isPinned(conv, id) { return chat(conv).pins.some(function (p) { return p.id === id; }); }
  function canPin(conv) { return chat(conv).canPin; }

  function toggle(conv, id) {
    var body = new URLSearchParams();
    body.append('action', isPinned(conv, id) ? 'unpin' : 'pin');
    return fetch('/messages/m/' + id + '/pin/', { method: 'POST', body: body, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { if (!r.ok) { throw new Error(d.error || 'Could not change the pin — try again.'); } return d; }); })
      .then(function (d) { set(conv, d.pins); document.dispatchEvent(new CustomEvent('uc:pins', { detail: { conversation: conv } })); return d.pins; });
  }

  window.UCPins = { set: set, render: render, isPinned: isPinned, canPin: canPin, toggle: toggle };
})();

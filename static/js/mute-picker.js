/* ---------------------------------------------------------------
   "Mute notifications for…" — 8 hours, 1 week or Always, like WhatsApp.
   Used by Messages (chat/conversation.js) and a group's Notifications
   tile (group-page.js); the server side is chat_action in chat/views.py.

   UCMute.pick(name)  → Promise of '8h' | '1w' | 'always', or null if cancelled
   UCMute.label(iso)  → "Muted until Tue 9:10 pm" (or "Muted" for Always)
   UCMute.isOn(muted, untilIso) → still muted now?
   --------------------------------------------------------------- */
(function () {
  'use strict';
  if (window.UCMute) { return; }
  var modal = null, resolve = null;
  var CHOICES = [['8h', '8 hours'], ['1w', '1 week'], ['always', 'Always']];

  function build() {
    modal = document.createElement('div');
    modal.className = 'modal fade um-modal';
    modal.tabIndex = -1;
    modal.setAttribute('aria-labelledby', 'umTitle');
    var opts = CHOICES.map(function (c, i) {
      return '<label class="um-choice"><input type="radio" name="um-for" value="' + c[0] + '"' + (i === 0 ? ' checked' : '') + '><span>' + c[1] + '</span></label>';
    }).join('');
    modal.innerHTML =
      '<div class="modal-dialog modal-dialog-centered modal-sm"><form class="modal-content js-um-form">' +
      '<div class="modal-body">' +
      '<h2 class="um-title" id="umTitle">Mute notifications</h2>' +
      '<p class="um-sub js-um-sub"></p>' +
      '<div class="um-choices" role="radiogroup" aria-labelledby="umTitle">' + opts + '</div>' +
      '<p class="um-note">Nobody else can see that you muted it. Messages still arrive — you just won’t get pop-ups or unread badges.</p>' +
      '</div>' +
      '<div class="modal-footer"><button type="button" class="btn btn-light" data-bs-dismiss="modal">Cancel</button>' +
      '<button type="submit" class="btn btn-primary">Mute</button></div>' +
      '</form></div>';
    document.body.appendChild(modal);
    modal.querySelector('.js-um-form').addEventListener('submit', function (e) {
      e.preventDefault();
      var picked = modal.querySelector('input[name="um-for"]:checked');
      var r = resolve; resolve = null;
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      if (r) { r(picked ? picked.value : '8h'); }
    });
    modal.addEventListener('hidden.bs.modal', function () { if (resolve) { var r = resolve; resolve = null; r(null); } });
  }

  function pick(name) {
    if (!window.bootstrap) { return Promise.resolve('always'); }
    if (!modal) { build(); }
    modal.querySelector('.js-um-sub').textContent = name ? 'Mute “' + name + '” for…' : 'Mute this chat for…';
    modal.querySelector('input[value="8h"]').checked = true;
    return new Promise(function (res) {
      resolve = res;
      bootstrap.Modal.getOrCreateInstance(modal).show();
      setTimeout(function () { var c = modal.querySelector('input:checked'); if (c) { c.focus(); } }, 250);
    });
  }

  function when(iso) {
    var d = new Date(iso), now = new Date();
    var time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    if (d.toDateString() === now.toDateString()) { return time; }
    var tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
    if (d.toDateString() === tomorrow.toDateString()) { return 'tomorrow ' + time; }
    return d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' }) + ', ' + time;
  }
  function label(iso) { return iso ? 'Muted until ' + when(iso) : 'Muted'; }
  function isOn(muted, until) { return !!muted && (!until || new Date(until) > new Date()); }

  window.UCMute = { pick: pick, label: label, when: when, isOn: isOn };
})();

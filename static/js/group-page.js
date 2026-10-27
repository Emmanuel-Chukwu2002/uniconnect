/* A group's page (templates/studygroups/detail.html): "Copy link", and the
   Notifications tile — it mutes or unmutes the group chat, the same switch
   as Mute in Messages (chat/views.py chat_action). Listeners are on the
   document, so pages opened in place (static/js/nav.js) work too. */
(function () {
  'use strict';
  if (window.__ucGroupPage) { return; }
  window.__ucGroupPage = true;
  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ''; }
  function toast(t, k) { if (window.showToast) { window.showToast(t, k); } }

  document.addEventListener('click', function (e) {
    // Sessions tab: "Edit" opens the session's form in place (no reload); it
    // still works as a link without JavaScript.
    var ed = e.target.closest('.js-ss-edit');
    if (ed) {
      var form = document.getElementById(ed.dataset.target);
      if (form) {
        e.preventDefault();
        form.hidden = !form.hidden;
        if (!form.hidden) { var t = form.querySelector('input[name=time]'); if (t) { t.focus(); } }
      }
      return;
    }
    var copy = e.target.closest('.js-gp-copy');
    if (copy) {
      (navigator.clipboard ? navigator.clipboard.writeText(copy.dataset.url) : Promise.reject())
        .then(function () { toast('Link copied.'); }, function () { toast("Couldn't copy the link.", 'error'); });
      return;
    }
    var tile = e.target.closest('.js-gp-mute');
    if (!tile || tile.disabled) { return; }
    var mute = !(window.UCMute ? UCMute.isOn(tile.dataset.muted === '1', tile.dataset.until) : tile.dataset.muted === '1');
    var title = document.querySelector('.gp-titles h1');
    var ask = mute && window.UCMute ? UCMute.pick(title ? title.textContent.trim() : '') : Promise.resolve(mute ? 'always' : null);
    ask.then(function (length) {
      if (mute && !length) { return; }               // cancelled
      var body = new FormData();
      body.append('action', mute ? 'mute' : 'unmute');
      if (mute) { body.append('for', length); }
      tile.disabled = true;
      return fetch(tile.dataset.url, { method: 'POST', body: body, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { if (!r.ok) { throw new Error(); } return r.json(); })
        .then(function (res) {
          var until = mute ? res.muted_until : null;
          tile.dataset.muted = mute ? '1' : '0';
          if (until) { tile.dataset.until = until; } else { delete tile.dataset.until; }
          tile.setAttribute('aria-pressed', mute ? 'false' : 'true');
          tile.querySelector('i').className = 'bi ' + (mute ? 'bi-bell-slash' : 'bi-bell');
          tile.querySelector('.js-gp-mute-state').textContent = mute ? (until ? 'Off until ' + UCMute.when(until) : 'Off') : 'On';
          toast(mute ? (until ? 'Group chat muted until ' + UCMute.when(until) + '.' : 'Group chat muted until you turn it back on.') : 'Notifications for this group are on.');
        })
        .catch(function () { toast('Could not change notifications — try again.', 'error'); })
        .then(function () { tile.disabled = false; });
    });
  });
})();

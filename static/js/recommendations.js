/* Interested / Not interested on recommendations (recommendations/views.py feedback).
   Works on every page (loaded once from base.html; document-level listeners, so
   pages swapped in by nav.js need nothing extra). Without JavaScript the same
   buttons are plain forms. */
(function () {
  'use strict';
  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ''; }
  function send(form, value) {
    var data = new FormData(form);
    data.set('value', value);
    return fetch(form.action, { method: 'POST', body: data, credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { if (!r.ok) { throw new Error(); } return r.json(); });
  }
  function toast(t, tag) { if (window.showToast) { window.showToast(t, tag || 'error'); } }
  function setInterested(form, on) {
    var btn = form.querySelector('.js-rec-interested');
    form.querySelector('input[name="value"]').value = on ? '' : 'interested';
    if (!btn) { return; }
    btn.classList.toggle('is-on', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    var icon = btn.querySelector('i'); if (icon) { icon.className = 'bi ' + (on ? 'bi-star-fill' : 'bi-star'); }
    var label = btn.querySelector('span');
    if (label) {
      label.textContent = form.classList.contains('js-rec-post') ? (on ? 'Interested (undo)' : 'Interested in this post') : (on ? 'Interested' : 'Interested?');
    }
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.classList || !form.classList.contains('js-rec-form')) { return; }
    e.preventDefault(); e.stopPropagation();
    var value = form.querySelector('input[name="value"]').value;
    var card = form.closest('.js-rec-card');
    send(form, value).then(function (res) {
      if (res.value === 'not_interested') {
        if (card) { card.classList.add('is-gone'); card.dataset.recUndoForm = ''; card._recForm = form; }
        return;
      }
      setInterested(form, res.value === 'interested');
      if (card) {          // Interested clears any Not interested on the same item
        var other = card.querySelector('.js-rec-interested');
        if (other && other.closest('form') !== form) { setInterested(other.closest('form'), res.value === 'interested'); }
      }
      if (form.classList.contains('js-rec-post')) { toast(res.value ? "Thanks — you'll see more like this." : 'Removed.', 'success'); }
    }).catch(function () { toast('Something went wrong — try again.'); });
  }, true);

  document.addEventListener('click', function (e) {
    var undo = e.target.closest('.js-rec-undo');
    if (!undo) { return; }
    var card = undo.closest('.js-rec-card');
    var form = card && card._recForm;
    if (!form) { return; }
    send(form, '').then(function () {
      card.classList.remove('is-gone');
      var fav = card.querySelector('.js-rec-interested');
      if (fav) { setInterested(fav.closest('form'), false); }
    }).catch(function () { toast('Could not undo — try again.'); });
  });
})();

/* =====================================================================
   UniConnect Messages — You (settings). Each change saves straight
   away and takes effect at once.
   ===================================================================== */
(function () {
  'use strict';
  var WA = window.WA;
  var app = document.getElementById('waApp');
  if (!WA || !app) { return; }

  function save(field, value) {
    return WA.post('/messages/you/settings/', { field: field, value: value }).then(function (res) {
      if (field === 'enter_to_send') { app.setAttribute('data-enter-send', res.value ? '1' : '0'); }
      if (field === 'sounds') { app.setAttribute('data-sounds', res.value ? '1' : '0'); }
      if (field === 'wallpaper') {
        app.classList.remove('wa-wallpaper-doodle', 'wa-wallpaper-plain');
        app.classList.add('wa-wallpaper-' + res.value);
      }
      WA.toast('Saved.');
      return res;
    }).catch(function (err) { WA.toast(err.message, 'error'); throw err; });
  }

  document.addEventListener('change', function (e) {
    var el = e.target.closest('.js-wa-setting');
    if (!el) { return; }
    save(el.getAttribute('data-field'), el.type === 'checkbox' ? (el.checked ? '1' : '0') : el.value)
      .catch(function () { if (el.type === 'checkbox') { el.checked = !el.checked; } });
  });

  document.addEventListener('submit', function (e) {
    if (!e.target.matches('.js-wa-about-form')) { return; }
    e.preventDefault();
    var value = e.target.querySelector('.js-wa-about-input').value.trim();
    save('about', value).then(function (res) {
      document.querySelectorAll('.js-wa-about-text').forEach(function (t) { t.textContent = res.value; });
    });
  });
})();

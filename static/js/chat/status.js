/* =====================================================================
   UniConnect Messages — Updates (status)
   Status updates are UniConnect Stories; this opens the same viewer and
   uploader app.js uses on Home (window.UniStories).
   ===================================================================== */
(function () {
  'use strict';
  var WA = window.WA;
  if (!WA || !document.getElementById('waApp')) { return; }

  function stories() { return window.UniStories; }

  document.addEventListener('click', function (e) {
    var add = e.target.closest('.js-wa-add-status');
    if (add) {
      e.stopPropagation();
      if (stories()) { stories().upload(); } else { location.href = '/messages/updates/'; }
      return;
    }
    var row = e.target.closest('.js-wa-status-row');
    if (!row) { return; }
    var userId = parseInt(row.getAttribute('data-user'), 10);
    if (!stories()) { return; }
    if (row.getAttribute('data-mine') === '1' && row.getAttribute('data-count') === '0') { stories().upload(); return; }
    stories().open(userId);
    var ring = row.querySelector('.wa-status-ring');
    if (ring) { ring.classList.add('is-seen'); }
  });
  document.addEventListener('keydown', function (e) {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.js-wa-status-row')) { e.preventDefault(); e.target.click(); }
  });

  // Search box on the Updates tab.
  document.addEventListener('click', function (e) {
    if (!e.target.closest('.js-wa-filter-toggle')) { return; }
    var box = document.querySelector('.js-wa-filter-box');
    if (!box) { return; }
    box.hidden = !box.hidden;
    if (!box.hidden) { box.querySelector('input').focus(); }
  });
  document.addEventListener('input', function (e) {
    if (!e.target.matches('.js-wa-filter-input')) { return; }
    var term = e.target.value.trim().toLowerCase();
    document.querySelectorAll('.js-wa-status-row[data-name]').forEach(function (row) {
      row.hidden = term && row.getAttribute('data-name').indexOf(term) === -1;
    });
  });

  // Someone you follow / chat with posted a status: dot on the Updates tab.
  WA.on('status', function () {
    document.querySelectorAll('.js-wa-status-dot').forEach(function (d) {
      d.hidden = document.getElementById('waApp').getAttribute('data-tab') === 'updates';
    });
  });
  WA.on('page', function () {
    if (document.getElementById('waApp').getAttribute('data-tab') === 'updates') {
      document.querySelectorAll('.js-wa-status-dot').forEach(function (d) { d.hidden = true; });
    }
  });
})();

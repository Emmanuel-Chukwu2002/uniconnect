/* =====================================================================
   Bookshop (templates/bookshop/*): save / unsave, shelf arrows, the
   sell form's cover photo preview (click or drag & drop), share,
   confirm-before-delete and the sort menu.
   ===================================================================== */
(function () {
  'use strict';

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  function toast(msg, kind) {
    if (typeof window.showToast === 'function') { window.showToast(msg, kind); }
  }
  function pop(el) { el.classList.remove('bs-pop'); void el.offsetWidth; el.classList.add('bs-pop'); }

  // ---------------- save / unsave (card hearts and the big Save button) ----------------
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.js-bs-save');
    if (!btn) { return; }
    e.preventDefault();
    e.stopPropagation();
    if (btn.disabled) { return; }
    btn.disabled = true;
    fetch(btn.dataset.url, { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { if (!r.ok) { throw new Error(); } return r.json(); })
      .then(function (data) {
        // Every heart for this book on the page follows.
        document.querySelectorAll('.js-bs-save[data-url="' + btn.dataset.url + '"]').forEach(function (b) {
          b.classList.toggle('is-saved', data.saved);
          b.setAttribute('aria-pressed', data.saved ? 'true' : 'false');
          var big = b.classList.contains('js-bs-save-big');
          b.setAttribute('aria-label', data.saved ? (big ? 'Remove from saved' : 'Unlike') : (big ? 'Save' : 'Like'));
          b.title = data.saved ? (big ? 'Saved' : 'Unlike') : (big ? 'Save' : 'Like');
          var n = b.querySelector('.js-bs-like-count');
          if (n) { n.textContent = data.saves; n.hidden = !data.saves; }
          var i = b.querySelector('i');
          if (i) { i.className = 'bi ' + (data.saved ? 'bi-heart-fill' : 'bi-heart'); }
          var label = b.querySelector('.js-bs-save-label');
          if (label) { label.textContent = data.saved ? 'Saved' : 'Save'; }
          if (data.saved) { pop(b); }
        });
        // The "N likes" line on the book page — only for this book, not for books in the shelves below it.
        document.querySelectorAll('.js-bs-save-count[data-url="' + btn.dataset.url + '"]').forEach(function (c) {
          c.textContent = data.saves;
          var word = c.nextSibling;
          if (word && word.nodeType === 3) { word.textContent = data.saves === 1 ? ' like' : ' likes'; }
        });
        // On the Saved page, an unsaved book leaves the grid.
        var grid = btn.closest('.js-bs-saved-grid');
        if (grid && !data.saved) {
          var card = btn.closest('.bs-card');
          card.style.transition = 'opacity .2s, transform .2s';
          card.style.opacity = '0';
          card.style.transform = 'scale(.95)';
          setTimeout(function () { card.remove(); if (!grid.children.length) { window.UC ? UC.reload() : location.reload(); } }, 200);
        }
        toast(data.saved ? 'Liked — find it under Saved.' : 'Removed from your likes.');
      })
      .catch(function () { toast("Couldn't update. Please try again.", 'error'); })
      .then(function () { btn.disabled = false; });
  });

  // ---------------- shelf arrows ----------------
  function updateArrows(shelf) {
    var row = shelf.querySelector('.js-bs-row');
    var prev = shelf.querySelector('.js-bs-prev'), next = shelf.querySelector('.js-bs-next');
    if (!row || !prev || !next) { return; }
    var max = row.scrollWidth - row.clientWidth - 2;
    prev.disabled = row.scrollLeft <= 2;
    next.disabled = row.scrollLeft >= max;
    var scrollable = max > 2;
    prev.hidden = next.hidden = !scrollable;
  }
  function setUpShelves() {
    document.querySelectorAll('.js-bs-shelf').forEach(function (shelf) {
      var row = shelf.querySelector('.js-bs-row');
      if (!row || row._bsReady) { return; }
      row._bsReady = true;
      row.addEventListener('scroll', function () { updateArrows(shelf); }, { passive: true });
      shelf.querySelector('.js-bs-prev').addEventListener('click', function () { row.scrollBy({ left: -row.clientWidth * 0.85 }); });
      shelf.querySelector('.js-bs-next').addEventListener('click', function () { row.scrollBy({ left: row.clientWidth * 0.85 }); });
      updateArrows(shelf);
    });
  }
  window.addEventListener('resize', function () { document.querySelectorAll('.js-bs-shelf').forEach(updateArrows); });

  // ---------------- sell form: cover photo preview, drag & drop, remove ----------------
  function setUpUploader() {
  var uploader = document.querySelector('.js-bs-uploader');
  if (uploader && !uploader._bsReady) {
    uploader._bsReady = true;
    var input = uploader.querySelector('input[type=file]');
    var img = uploader.querySelector('.js-bs-cover-preview');
    var removeBtn = document.querySelector('.js-bs-cover-remove');
    var removeFlag = document.querySelector('.js-bs-remove-cover');
    var label = document.querySelector('.js-bs-cover-label');
    var objectUrl = null;
    var show = function (src) {
      if (objectUrl && src !== objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = null; }
      if (src) { img.src = src; img.hidden = false; } else { img.removeAttribute('src'); img.hidden = true; }
      uploader.classList.toggle('has-image', !!src);
      removeBtn.hidden = !src;
      label.textContent = src ? 'Change photo' : 'Choose photo';
    };
    input.addEventListener('change', function () {
      var f = input.files && input.files[0];
      if (!f) { return; }
      if (!/^image\//.test(f.type)) { toast('Please choose an image.', 'error'); input.value = ''; return; }
      if (f.size > 8 * 1024 * 1024) { toast('The photo must be smaller than 8 MB.', 'error'); input.value = ''; return; }
      removeFlag.value = '0';
      objectUrl = URL.createObjectURL(f);
      show(objectUrl);
    });
    removeBtn.addEventListener('click', function () {
      input.value = '';
      removeFlag.value = '1';
      show(null);
    });
    ['dragenter', 'dragover'].forEach(function (ev) {
      uploader.addEventListener(ev, function (e) { e.preventDefault(); uploader.classList.add('is-drag'); });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      uploader.addEventListener(ev, function (e) { e.preventDefault(); uploader.classList.remove('is-drag'); });
    });
    uploader.addEventListener('drop', function (e) {
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (!f) { return; }
      var dt = new DataTransfer();
      dt.items.add(f);
      input.files = dt.files;
      input.dispatchEvent(new Event('change'));
    });
  }
  }

  // Runs on every Bookshop page shown (nav.js loads pages in place).
  function setUp() { setUpShelves(); setUpUploader(); }
  if (window.UC && UC.onPage) { UC.onPage(setUp); } else { setUp(); }

  // ---------------- share ----------------
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.js-bs-share');
    if (!btn) { return; }
    var url = btn.dataset.url, title = btn.dataset.title;
    if (navigator.share) {
      navigator.share({ title: title, text: title + ' — on UniConnect Bookshop', url: url }).catch(function () {});
    } else if (navigator.clipboard) {
      navigator.clipboard.writeText(url).then(function () { toast('Link copied.'); }, function () { toast("Couldn't copy the link.", 'error'); });
    }
  });

  // ---------------- confirm delete + sort menu ----------------
  document.addEventListener('submit', function (e) {
    var form = e.target.closest('.js-bs-confirm');
    if (form && !window.confirm(form.dataset.confirm)) { e.preventDefault(); }
  });
  document.addEventListener('change', function (e) {
    if (e.target.matches('.js-bs-autosubmit')) {
      var f = e.target.form;
      if (f.requestSubmit) { f.requestSubmit(); } else { f.submit(); }
    }
  });
})();

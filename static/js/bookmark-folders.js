/* ---------------------------------------------------------------
   Bookmark folders (feed/bookmark_folders.py).
   - "Save to a bookmark folder" in a post's ... menu (.js-bf-open), and
     "Add to folder" on the note that pops up after bookmarking a post
     (app.js sends uc:bookmarked), open the picker (#bookmarkFolderModal
     in base.html): tap a folder to put the post there, or make a new one.
   - "New folder" on the Bookmarks page (.js-bf-new-folder) opens the
     same picker just to make a folder, then shows it.
   --------------------------------------------------------------- */
(function () {
  'use strict';
  var postId = null, current = null, busy = false;

  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ''; }
  function modalEl() { return document.getElementById('bookmarkFolderModal'); }
  function toast(t, kind) { if (window.showToast) { window.showToast(t, kind); } }
  function post(url, fields) {
    var data = new FormData();
    Object.keys(fields).forEach(function (k) { data.append(k, fields[k] == null ? '' : fields[k]); });
    data.append('csrfmiddlewaretoken', csrf());
    return fetch(url, { method: 'POST', body: data, credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json().then(function (d) { if (!r.ok) { throw new Error(d.error || 'Something went wrong — try again.'); } return d; }); });
  }
  function showError(msg) {
    var el = modalEl().querySelector('.js-bf-error');
    el.textContent = msg || ''; el.hidden = !msg;
  }

  // The post's bookmark button(s) on the page show it as saved.
  function markSaved(id) {
    document.querySelectorAll('.js-bookmark-btn[data-post-id="' + id + '"]').forEach(function (b) {
      b.classList.add('bookmarked'); b.title = 'Remove bookmark';
      var i = b.querySelector('i'); if (i) { i.className = 'bi bi-bookmark-fill'; }
    });
  }

  function row(folder, isCurrent) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'bf-row js-bf-pick' + (isCurrent ? ' is-on' : '');
    b.setAttribute('role', 'listitem');
    b.dataset.folder = folder ? folder.id : '';
    b.innerHTML = '<i class="bi ' + (folder ? 'bi-folder' : 'bi-bookmarks') + '"></i><span class="bf-row-name"></span><small></small><i class="bi bi-check-lg bf-row-check" aria-hidden="true"></i>';
    b.querySelector('.bf-row-name').textContent = folder ? folder.name : 'No folder';
    b.querySelector('small').textContent = folder ? (folder.n + (folder.n === 1 ? ' post' : ' posts')) : 'Just in All bookmarks';
    if (isCurrent) { b.setAttribute('aria-current', 'true'); }
    return b;
  }

  function open(forPost) {
    var m = modalEl();
    if (!m || !window.bootstrap) { return; }
    postId = forPost || null;
    current = null;
    showError('');
    m.querySelector('.js-bf-title').textContent = postId ? 'Save to a folder' : 'New bookmark folder';
    var list = m.querySelector('.js-bf-list');
    list.hidden = !postId;
    list.innerHTML = '<div class="bf-loading"><span class="spinner-border spinner-border-sm"></span></div>';
    m.querySelector('.js-bf-new-name').value = '';
    bootstrap.Modal.getOrCreateInstance(m).show();
    if (!postId) { setTimeout(function () { m.querySelector('.js-bf-new-name').focus(); }, 250); return; }
    fetch('/bookmarks/folders/?post=' + encodeURIComponent(postId), { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        current = d.bookmarked ? (d.current || '') : null;
        list.innerHTML = '';
        list.appendChild(row(null, d.bookmarked && !d.current));
        d.folders.forEach(function (f) { list.appendChild(row(f, d.current === f.id)); });
        if (!d.folders.length) {
          var p = document.createElement('p');
          p.className = 'bf-hint';
          p.textContent = 'No folders yet — make one below.';
          list.appendChild(p);
        }
      })
      .catch(function () { list.innerHTML = ''; showError('Could not load your folders — check your connection.'); });
  }

  // Saved: tell the person, update the page, close.
  function saved(d) {
    markSaved(d.post);
    toast(d.message);
    // On a folder of the Bookmarks page, a post moved somewhere else leaves it.
    var tab = document.querySelector('.js-bookmarks-tab[data-folder]');
    if (tab && String(d.folder ? d.folder.id : '') !== tab.dataset.folder) {
      var card = tab.querySelector('.post-card[data-post-id="' + d.post + '"]');
      if (card) { card.classList.add('is-leaving'); setTimeout(function () { card.remove(); }, 220); }
    }
    bootstrap.Modal.getOrCreateInstance(modalEl()).hide();
  }

  document.addEventListener('click', function (e) {
    var t = e.target, b;
    if ((b = t.closest('.js-bf-open'))) { e.preventDefault(); hideSnack(); open(b.dataset.postId); return; }
    if ((b = t.closest('.js-bf-new-folder'))) { e.preventDefault(); open(null); return; }
    if ((b = t.closest('.js-bf-pick'))) {
      if (busy || !postId) { return; }
      busy = true;
      post('/bookmarks/folders/put/', { post: postId, folder: b.dataset.folder })
        .then(saved).catch(function (err) { showError(err.message); })
        .then(function () { busy = false; });
    }
  });

  document.addEventListener('submit', function (e) {
    if (!e.target.matches || !e.target.matches('.js-bf-new-form')) { return; }
    e.preventDefault();
    if (busy) { return; }
    var name = e.target.querySelector('.js-bf-new-name').value.trim();
    if (!name) { showError('Give the folder a name.'); return; }
    busy = true;
    post('/bookmarks/folders/new/', { name: name, post: postId || '' })
      .then(function (d) {
        if (postId) { saved(d); return; }
        bootstrap.Modal.getOrCreateInstance(modalEl()).hide();
        toast('Folder “' + d.folder.name + '” made.');
        if (window.UC && UC.navigate) { UC.navigate(d.url); } else { location.href = d.url; }
      })
      .catch(function (err) { showError(err.message); })
      .then(function () { busy = false; });
  });

  // ---------- the note after bookmarking ----------
  var snack = null, snackTimer = null;
  function hideSnack() {
    clearTimeout(snackTimer);
    if (snack) { snack.classList.remove('is-shown'); }
  }
  document.addEventListener('uc:bookmarked', function (e) {
    if (!modalEl()) { return; }
    if (!snack) {
      snack = document.createElement('div');
      snack.className = 'bf-snack';
      snack.setAttribute('role', 'status');
      snack.innerHTML = '<i class="bi bi-bookmark-fill"></i><span>Added to your Bookmarks</span><button type="button" class="js-bf-open">Add to folder</button>';
      document.body.appendChild(snack);
      snack.addEventListener('mouseenter', function () { clearTimeout(snackTimer); });
      snack.addEventListener('mouseleave', function () { snackTimer = setTimeout(hideSnack, 2500); });
    }
    snack.querySelector('.js-bf-open').dataset.postId = e.detail.postId;
    clearTimeout(snackTimer);
    requestAnimationFrame(function () { snack.classList.add('is-shown'); });
    snackTimer = setTimeout(hideSnack, 5000);
  });
  document.addEventListener('uc:page', hideSnack);
})();

/* =====================================================================
   Communities (templates/communities/*): Join / Leave without leaving the
   page, the create form's banner preview and character counters, the
   delete confirmation, and "copy link".
   Listeners are on the document, so pages loaded in place
   (static/js/nav.js) work without setting anything up again.
   ===================================================================== */
(function () {
  'use strict';
  if (window.__ucCommunities) { return; }
  window.__ucCommunities = true;

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  function toast(msg, kind) {
    if (msg && typeof window.showToast === 'function') { window.showToast(msg, kind); }
  }

  // ---------------- Join / Joined / Requested ----------------
  function paint(form, state) {
    var restricted = form.dataset.restricted === '1';
    form.dataset.state = state;
    form.action = state === 'none' ? form.dataset.joinUrl : form.dataset.leaveUrl;
    var btn = form.querySelector('.cm-join');
    btn.classList.remove('is-none', 'is-joined', 'is-requested');
    btn.classList.add('is-' + state);
    btn.querySelector('.cm-join-text').textContent =
      state === 'joined' ? 'Joined' : state === 'requested' ? 'Requested' : (restricted ? 'Ask to join' : 'Join');
    btn.querySelector('.cm-join-hover').textContent =
      state === 'joined' ? 'Leave' : state === 'requested' ? 'Cancel' : '';
    btn.classList.remove('cm-pop'); void btn.offsetWidth; btn.classList.add('cm-pop');
  }

  document.addEventListener('submit', function (e) {
    var form = e.target.closest('.js-cm-join-form');
    if (!form) { return; }
    e.preventDefault();
    var btn = form.querySelector('.cm-join');
    if (btn.disabled) { return; }
    btn.disabled = true;
    var before = form.dataset.state;
    fetch(form.action, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
      .then(function (res) {
        if (!res.ok) { throw new Error(res.data.error || 'Something went wrong — please try again.'); }
        var data = res.data;
        var id = form.dataset.communityId;
        document.querySelectorAll('.js-cm-join-form[data-community-id="' + id + '"]').forEach(function (f) { paint(f, data.state); });
        document.querySelectorAll('.js-cm-count[data-community-id="' + id + '"]').forEach(function (n) { n.textContent = data.members; });
        document.querySelectorAll('.js-cm-count-word[data-community-id="' + id + '"]').forEach(function (w) { w.textContent = data.members === 1 ? 'Member' : 'Members'; });
        toast(data.message);
        // On the community's own page, joining or leaving changes what you
        // can do there (post, see requests…), so refresh it in place.
        if (document.querySelector('.cm-detail') && (before === 'joined' || data.state === 'joined') && window.UC && UC.reload) {
          UC.reload();
        }
      })
      .catch(function (err) { toast(err.message, 'error'); })
      .then(function () { btn.disabled = false; });
  });

  // ---------------- create / edit form ----------------
  document.addEventListener('change', function (e) {
    var input = e.target.closest('.js-cm-banner-input');
    if (input) {
      var picker = input.closest('.js-cm-banner-picker');
      var file = input.files && input.files[0];
      if (!file) { return; }
      if (!/^image\//.test(file.type)) { toast('Please choose a photo for the banner.', 'error'); input.value = ''; return; }
      var url = URL.createObjectURL(file);
      picker.style.backgroundImage = "url('" + url + "')";
      picker.classList.add('has-photo');
      var hint = picker.querySelector('.js-cm-banner-hint');
      if (hint) { hint.textContent = 'Change banner photo'; }
      var remove = document.querySelector('.js-cm-remove-banner');
      if (remove) { remove.checked = false; }
      return;
    }
    var icon = e.target.closest('.js-cm-icon-input');
    if (icon) {
      var f = icon.files && icon.files[0];
      if (!f) { return; }
      if (!/^image\//.test(f.type)) { toast('Please choose a photo for the icon.', 'error'); icon.value = ''; return; }
      var ip = icon.closest('.js-cm-icon-picker');
      ip.style.backgroundImage = "url('" + URL.createObjectURL(f) + "')";
      ip.classList.add('has-photo');
      return;
    }
    var rm = e.target.closest('.js-cm-remove-banner');
    if (rm) {
      var p = document.querySelector('.js-cm-banner-picker');
      if (p && rm.checked) { p.style.backgroundImage = ''; p.classList.remove('has-photo'); }
    }
  });

  function count(input) {
    var foot = input.parentElement.querySelector('.js-cm-counter');
    if (foot) { foot.textContent = input.value.length + '/' + input.dataset.max; }
  }
  document.addEventListener('input', function (e) {
    var input = e.target.closest('.js-cm-count-input');
    if (input) { count(input); return; }
    var confirmName = e.target.closest('.js-cm-confirm-name');
    if (confirmName) {
      var ok = confirmName.value.trim().toLowerCase() === confirmName.dataset.name.toLowerCase();
      confirmName.form.querySelector('.js-cm-delete-btn').disabled = !ok;
    }
  });
  function initCounters() { document.querySelectorAll('.js-cm-count-input').forEach(count); }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', initCounters); } else { initCounters(); }
  document.addEventListener('uc:page', initCounters);

  // ---------------- Explore: sort menu, "+N" tags ----------------
  document.addEventListener('change', function (e) {
    var sel = e.target.closest('.js-cm-sort');
    if (!sel) { return; }
    var form = sel.form, url = form.action + '?' + new URLSearchParams(new FormData(form)).toString();
    if (window.UC && UC.navigate) { UC.navigate(url); } else { form.submit(); }
  });
  document.addEventListener('click', function (e) {
    var more = e.target.closest('.js-cm-more-tags');
    if (!more) { return; }
    more.parentElement.querySelectorAll('.cm-tag[hidden]').forEach(function (t) { t.hidden = false; });
    more.remove();
  });

  // ---------------- a community's page ----------------
  document.addEventListener('click', function (e) {
    // "Leave community" in the ... menu: the same as the Joined button.
    var leave = e.target.closest('.js-cm-leave');
    if (leave) {
      var f = document.querySelector('.cm-head .js-cm-join-form[data-community-id="' + leave.dataset.communityId + '"]');
      if (f) { f.requestSubmit ? f.requestSubmit() : f.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true })); }
      return;
    }
    // The banner's search button shows the search box under the header.
    var s = e.target.closest('.js-cm-search-toggle');
    if (s) {
      var box = document.getElementById('cmPostSearch');
      if (!box) { return; }
      box.hidden = !box.hidden;
      s.setAttribute('aria-expanded', box.hidden ? 'false' : 'true');
      if (!box.hidden) { box.querySelector('input[type="search"]').focus(); }
      return;
    }
    // The composer card and the + button: open the pop-up composer, on the chosen tool.
    var b = e.target.closest('.js-cm-compose');
    if (!b) { return; }
    var modalEl = document.getElementById('composePostModal');
    if (!modalEl || !window.bootstrap) { location.href = b.dataset.composeUrl; return; }
    var form = modalEl.querySelector('form.compose-form');
    var tool = b.dataset.tool;
    var media = form.querySelector('.compose-media-input');
    var text = form.querySelector('.compose-textarea');
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
    if ((tool === 'photo' || tool === 'video') && media) {
      if (window.UCPolls && !form.querySelector('.js-cp-poll').hidden) { UCPolls.setPoll(form, false); }
      media.setAttribute('accept', tool === 'photo' ? 'image/*' : 'video/*');
      media.click();                    // the file picker (still inside the tap)
      var restore = function () { media.setAttribute('accept', 'image/*,video/*'); };
      media.addEventListener('change', restore, { once: true });
      modalEl.addEventListener('hidden.bs.modal', restore, { once: true });
    } else if (tool === 'poll' && window.UCPolls) {
      var hasMedia = form.querySelector('.compose-media-preview-grid') && form.querySelector('.compose-media-preview-grid').children.length;
      if (hasMedia) { toast("Remove the photos or video first — a poll can't have them."); }
      else { UCPolls.setPoll(form, true); }
    } else if (tool === 'link' && text) {
      text.dataset.placeholder = text.dataset.placeholder || text.placeholder;
      text.placeholder = 'Paste a link — a preview card is added when you post';
      modalEl.addEventListener('hidden.bs.modal', function () { text.placeholder = text.dataset.placeholder; }, { once: true });
    }
    if (tool !== 'photo' && tool !== 'video') { setTimeout(function () { text && text.focus(); }, 300); }
  });

  // ---------------- copy link ----------------
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.js-cm-copy-link');
    if (!btn) { return; }
    var url = btn.dataset.url;
    var done = function () { toast('Link copied — share it to invite people.'); };
    var failed = function () { toast("Couldn't copy the link.", 'error'); };
    if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(url).then(done, failed); } else { failed(); }
  });
})();

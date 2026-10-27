/* ---------------------------------------------------------------
   Composer tools (templates/feed/_compose_tools.html):
     camera    take a photo (phones open the camera; computers pick a file)
     GIF       pick a GIF from your device (it's added like a photo)
     emoji     a picker; also on the comment box (any .js-emoji-btn)
     schedule  post later (feed/scheduling.py) — the Post button says "Schedule"
     location  tag a place, with suggestions from /places/
     drafts    closing with something typed asks Save draft / Discard /
               Keep editing (feed/drafts.py); /post/new/?draft=<id> reopens one
   Everything listens on the document, so it works in the pop-up composer,
   the full-page composer and pages loaded in place. Styles: restyle.css
   ("Composer tools").
   --------------------------------------------------------------- */
(function () {
  'use strict';

  // ---------- camera & GIF: reuse the composer's own photo input ----------
  function pickInto(form, accept, capture) {
    var input = form.querySelector('.compose-media-input');
    if (!input || input.disabled) {
      if (window.showToast) { showToast("Polls can't have photos — remove the poll first."); }
      return;
    }
    var oldAccept = input.getAttribute('accept');
    input.setAttribute('accept', accept);
    if (capture) { input.setAttribute('capture', 'environment'); }
    var restore = function () {
      input.setAttribute('accept', oldAccept);
      input.removeAttribute('capture');
      window.removeEventListener('focus', later);
    };
    var later = function () { setTimeout(restore, 600); };
    input.addEventListener('change', restore, { once: true });
    window.addEventListener('focus', later);
    input.click();
  }

  // ---------- emoji picker ----------
  var EMOJI = [
    ['Smileys', '😀 😃 😄 😁 😆 😅 😂 🤣 😊 😇 🙂 😉 😌 😍 🥰 😘 😋 😎 🤩 🥳 😏 😒 😞 😔 😟 😕 🙁 😣 😖 😫 😩 🥺 😢 😭 😤 😠 😡 🤯 😳 🥵 🥶 😱 😨 😰 😥 😓 🤗 🤔 🤭 🤫 🤥 😶 😐 😑 😬 🙄 😯 😦 😧 😮 😲 🥱 😴 🤤 😪 😵 🤐 🥴 🤢 🤮 🤧 😷 🤒 🤕 🤑 🤠 😈 💀 👻 👽 🤖 💩'],
    ['Hands', '👍 👎 👌 ✌️ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ ✋ 🤚 🖐️ 🖖 👋 🤝 🙏 👏 🙌 👐 🤲 💪 ✍️ 💅 🫶'],
    ['Hearts', '❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣️ 💕 💞 💓 💗 💖 💘 💝 💯 ✨ ⭐ 🌟 🔥 💥 🎉 🎊'],
    ['Campus', '📚 📖 📝 ✏️ 🖊️ 📒 📓 📎 📌 🎓 🏫 🧑‍🎓 👩‍🏫 👨‍🏫 💻 🖥️ 📱 🔬 🧪 🧮 📊 📈 ⏰ ⏳ 📅 🗓️ ☕ 🎧 🏀 ⚽ 🏆 🎤 🎭 🎨 🎮'],
    ['Food', '🍚 🍛 🍲 🥘 🍗 🍖 🍕 🍔 🍟 🌭 🥪 🌮 🍝 🍜 🍳 🥗 🍞 🥐 🍰 🧁 🍩 🍪 🍫 🍿 🍌 🍍 🍉 🍊 🥭 🥥 🥤 🧃 🍹 🍺'],
    ['Places', '🇳🇬 🏠 🏢 🏥 🏦 ⛪ 🕌 🚌 🚕 🚗 🏍️ 🚲 ✈️ 🌍 🌞 🌧️ ⛈️ 🌈 ⚡ 🌙']
  ];
  var RECENT_KEY = 'uc-emoji-recent';
  var pop = null, target = null;

  function recent() {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); } catch (e) { return []; }
  }
  function remember(ch) {
    try {
      var list = recent().filter(function (x) { return x !== ch; });
      list.unshift(ch);
      localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 16)));
    } catch (e) {}
  }

  function buildPop() {
    pop = document.createElement('div');
    pop.className = 'emoji-pop';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'Emoji');
    pop.hidden = true;
    document.body.appendChild(pop);
    pop.addEventListener('mousedown', function (e) { e.preventDefault(); });   // keep the text box focused
    pop.addEventListener('click', function (e) {
      var b = e.target.closest('.emoji-cell');
      if (b) { insert(b.textContent); remember(b.textContent); return; }
      var tab = e.target.closest('.emoji-tab');
      if (tab) {
        var sec = pop.querySelector('[data-sec="' + tab.dataset.sec + '"]');
        if (sec) { pop.querySelector('.emoji-scroll').scrollTop = sec.offsetTop - 44; }
      }
    });
  }

  function render() {
    var sections = EMOJI.slice();
    var r = recent();
    if (r.length) { sections.unshift(['Recent', r.join(' ')]); }
    var icons = { Recent: 'bi-clock', Smileys: 'bi-emoji-smile', Hands: 'bi-hand-thumbs-up', Hearts: 'bi-heart', Campus: 'bi-mortarboard', Food: 'bi-cup-hot', Places: 'bi-geo-alt' };
    pop.innerHTML = '<div class="emoji-tabs">' + sections.map(function (s, i) {
      return '<button type="button" class="emoji-tab" data-sec="' + i + '" title="' + s[0] + '" aria-label="' + s[0] + '"><i class="bi ' + icons[s[0]] + '"></i></button>';
    }).join('') + '</div><div class="emoji-scroll">' + sections.map(function (s, i) {
      return '<div class="emoji-sec" data-sec="' + i + '"><small>' + s[0] + '</small><div class="emoji-grid">' +
        s[1].split(' ').filter(Boolean).map(function (ch) { return '<button type="button" class="emoji-cell">' + ch + '</button>'; }).join('') +
        '</div></div>';
    }).join('') + '</div>';
  }

  function openFor(btn) {
    if (!pop) { buildPop(); }
    var scope = btn.closest('form') || btn.parentNode;
    target = scope.querySelector('textarea, input[type=text]:not([name=location]):not(.js-cx-place)');
    if (!target) { return; }
    render();
    pop.hidden = false;
    var r = btn.getBoundingClientRect(), w = Math.min(330, window.innerWidth - 16), h = pop.offsetHeight || 320;
    pop.style.width = w + 'px';
    pop.style.left = Math.max(8, Math.min(r.left - w / 2 + r.width / 2, window.innerWidth - w - 8)) + 'px';
    pop.style.top = (r.top > h + 12 ? r.top - h - 8 : Math.min(r.bottom + 8, window.innerHeight - h - 8)) + 'px';
    btn.setAttribute('aria-expanded', 'true');
    pop._btn = btn;
  }
  function closePop() {
    if (pop && !pop.hidden) { pop.hidden = true; if (pop._btn) { pop._btn.setAttribute('aria-expanded', 'false'); } }
  }
  function insert(ch) {
    if (!target) { return; }
    var start = target.selectionStart == null ? target.value.length : target.selectionStart;
    var end = target.selectionEnd == null ? start : target.selectionEnd;
    if (target.maxLength > 0 && target.value.length - (end - start) + ch.length > target.maxLength) { return; }
    target.value = target.value.slice(0, start) + ch + target.value.slice(end);
    var pos = start + ch.length;
    target.focus();
    try { target.setSelectionRange(pos, pos); } catch (e) {}
    target.dispatchEvent(new Event('input', { bubbles: true }));
  }

  // ---------- schedule ----------
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function localValue(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()); }
  function setPostLabel(form) {
    var btn = form.querySelector('.compose-post-btn'), when = form.querySelector('.js-cx-when');
    if (!btn) { return; }
    var on = when && when.value && !form.querySelector('.js-cx-schedule').hidden;
    var thread = threadCount(form) > 0;
    btn.textContent = on ? (thread ? 'Schedule all' : 'Schedule') : (thread ? 'Post all' : 'Post');
    var text = form.querySelector('.js-cx-when-text');
    if (text && on) {
      var d = new Date(when.value);
      if (!isNaN(d)) {
        text.firstChild.textContent = 'Goes out ' + d.toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) + '. Change or cancel it in ';
      }
    }
  }
  function toggleSchedule(form, on) {
    var panel = form.querySelector('.js-cx-schedule'), btn = form.querySelector('.js-compose-schedule'), when = form.querySelector('.js-cx-when');
    if (!panel) { return; }
    panel.hidden = !on;
    btn.classList.toggle('is-on', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    var min = new Date(Date.now() + 6 * 60000), max = new Date(Date.now() + 30 * 86400000);
    when.min = localValue(min); when.max = localValue(max);
    if (on) {
      if (!when.value) { var d = new Date(Date.now() + 60 * 60000); d.setMinutes(0); when.value = localValue(d); }
      when.disabled = false;
    } else { when.value = ''; when.disabled = true; }
    setPostLabel(form);
  }

  // ---------- thread (the + button; feed/threads.py) ----------
  var MAX_PARTS = 24;
  function threadCount(form) { return form.querySelectorAll('.js-cx-thread .cx-thread-part').length; }
  function grow(t) { t.style.height = 'auto'; t.style.height = t.scrollHeight + 'px'; }
  function addPart(form, text, focus) {
    var box = form.querySelector('.js-cx-thread'), tpl = form.querySelector('.js-cx-thread-tpl');
    if (!box || !tpl) { return null; }
    if (threadCount(form) >= MAX_PARTS) {
      if (window.showToast) { showToast('A thread can have up to ' + (MAX_PARTS + 1) + ' posts.'); }
      return null;
    }
    var part = tpl.content.firstElementChild.cloneNode(true);
    box.appendChild(part);
    var t = part.querySelector('.js-cx-thread-text');
    if (text) { t.value = text; }
    setPostLabel(form);
    requestAnimationFrame(function () { grow(t); if (focus) { t.focus(); } });
    return part;
  }
  function clearThread(form) {
    var box = form.querySelector('.js-cx-thread');
    if (box) { box.innerHTML = ''; }
  }

  // Each + box's own photos (up to 4) or video — the same rules as a post.
  function isVideo(f) { return /^video\//.test(f.type); }
  function partFiles(part) { return part._files || (part._files = []); }
  function syncPart(part) {
    var input = part.querySelector('.js-cx-thread-file'), files = partFiles(part);
    if (window.DataTransfer) { var dt = new DataTransfer(); files.forEach(function (f) { dt.items.add(f); }); input.files = dt.files; }
    var box = part.querySelector('.js-cx-thread-previews');
    box.innerHTML = '';
    files.forEach(function (f, i) {
      var item = document.createElement('span');
      item.className = 'cx-thread-thumb';
      if (isVideo(f)) { item.classList.add('is-video'); item.innerHTML = '<i class="bi bi-play-fill"></i>'; }
      else { item.style.backgroundImage = 'url("' + URL.createObjectURL(f) + '")'; }
      var x = document.createElement('button');
      x.type = 'button'; x.className = 'js-cx-thread-unfile'; x.dataset.i = i;
      x.setAttribute('aria-label', 'Remove ' + f.name); x.innerHTML = '<i class="bi bi-x"></i>';
      item.appendChild(x);
      box.appendChild(item);
    });
    box.hidden = !files.length;
    part.querySelector('.cx-thread-photo').hidden = files.length >= 4 || files.some(isVideo);
  }
  function addPartFiles(part, picked) {
    var files = partFiles(part), next = files.concat(picked);
    var videos = next.filter(isVideo).length;
    if (videos && next.length > 1) {
      if (window.showToast) { showToast('A post can have photos or one video, not both.'); }
      syncPart(part);            // the file box goes back to what it had
      return;
    }
    if (next.length > 4) { if (window.showToast) { showToast('Up to 4 photos in each post.'); } next = next.slice(0, 4); }
    part._files = next;
    syncPart(part);
  }
  // Before sending: box n's files go as thread_media_n (feed/threads.py clean_parts).
  function numberParts(form) {
    form.querySelectorAll('.js-cx-thread .cx-thread-part').forEach(function (part, i) {
      var input = part.querySelector('.js-cx-thread-file');
      if (input) { input.name = 'thread_media_' + i; }
    });
  }

  // ---------- location ----------
  var placeTimer = null;
  function toggleLocation(form, on) {
    var panel = form.querySelector('.js-cx-location'), btn = form.querySelector('.js-compose-location'), input = form.querySelector('.js-cx-place');
    if (!panel) { return; }
    panel.hidden = !on;
    btn.classList.toggle('is-on', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    if (on) { input.disabled = false; input.focus(); loadPlaces(form, input.value); }
    else { input.value = ''; input.disabled = true; }
  }
  function loadPlaces(form, q) {
    clearTimeout(placeTimer);
    placeTimer = setTimeout(function () {
      fetch('/places/?q=' + encodeURIComponent(q || ''), { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.ok ? r.json() : { places: [] }; })
        .then(function (d) {
          var box = form.querySelector('.js-cx-places');
          if (!box) { return; }
          box.innerHTML = '';
          (d.places || []).forEach(function (name) {
            var b = document.createElement('button');
            b.type = 'button'; b.className = 'cx-place js-cx-place-pick';
            b.innerHTML = '<i class="bi bi-geo-alt"></i> ';
            b.appendChild(document.createTextNode(name));
            b.dataset.name = name;
            box.appendChild(b);
          });
        }).catch(function () {});
    }, q ? 200 : 0);
  }

  // ---------- drafts ----------
  function pendingFiles(form) { return (window.jQuery && jQuery(form).data('pendingMediaFiles')) || []; }
  function snapshot(form) {
    var parts = [];
    form.querySelectorAll('.compose-textarea, .cp-poll-input, .cp-poll-days, .js-cx-place, .js-cx-when, .js-cx-thread-text').forEach(function (i) { parts.push(i.disabled ? '' : i.value.trim()); });
    pendingFiles(form).forEach(function (f) { parts.push(f.name + ':' + f.size); });
    form.querySelectorAll('.js-cx-thread .cx-thread-part').forEach(function (p) { partFiles(p).forEach(function (f) { parts.push(f.name + ':' + f.size); }); });
    return parts.join('\u0001');
  }
  function hasWords(form) {
    var t = form.querySelector('.compose-textarea');
    var poll = Array.prototype.some.call(form.querySelectorAll('.cp-poll-input, .js-cx-thread-text'), function (i) { return i.value.trim(); });
    var partMedia = Array.prototype.some.call(form.querySelectorAll('.js-cx-thread .cx-thread-part'), function (p) { return partFiles(p).length; });
    return (t && t.value.trim()) || poll || pendingFiles(form).length || partMedia;
  }
  function isDirty(form) { return hasWords(form) && snapshot(form) !== (form.dataset.cleanSnapshot || ''); }
  function markClean(form) { form.dataset.cleanSnapshot = snapshot(form); }

  var leaveThen = null;
  function askToLeave(form, then) {
    var box = form.querySelector('.js-cx-leave');
    if (!box) { then(); return; }
    leaveThen = then;
    box.querySelector('.js-cx-save-label').textContent = form.querySelector('.js-draft-id').value ? 'Save changes' : 'Save draft';
    box.hidden = false;
    box.querySelector('.js-cx-save-draft').focus();
  }
  function clearComposer(form) {
    form.reset();
    var grid = form.querySelector('.compose-media-preview-grid');
    if (grid) { grid.innerHTML = ''; }
    if (window.jQuery) { jQuery(form).data('pendingMediaFiles', []); }
    if (form.querySelector('.js-cp-poll') && window.UCPolls) { UCPolls.setPoll(form, false); }
    clearThread(form);
    if (form.querySelector('.js-cx-schedule')) { toggleSchedule(form, false); toggleLocation(form, false); }
    form.querySelector('.js-draft-id').value = '';
    var post = form.querySelector('.compose-post-btn'); if (post) { post.disabled = true; post.textContent = 'Post'; }
    markClean(form);
  }
  function saveDraft(form) {
    numberParts(form);
    var data = new FormData(form);         // text, poll, place, time and the photos/videos
    var btn = form.querySelector('.js-cx-save-draft');
    btn.disabled = true;
    return fetch('/post/drafts/save/', { method: 'POST', body: data, credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        btn.disabled = false;
        if (!res.ok) { if (window.showToast) { showToast(res.d.error || 'Could not save the draft.', 'error'); } return false; }
        if (window.showToast) { showToast('Saved to drafts.'); }
        document.dispatchEvent(new CustomEvent('uc:draft-saved', { detail: res.d }));
        return true;
      })
      .catch(function () { btn.disabled = false; if (window.showToast) { showToast('Could not save the draft — check your connection.', 'error'); } return false; });
  }
  function finishLeave(form, save) {
    var box = form.querySelector('.js-cx-leave'), then = leaveThen;
    var go = function () { box.hidden = true; clearComposer(form); leaveThen = null; if (then) { then(); } };
    if (!save) { go(); return; }
    saveDraft(form).then(function (ok) { if (ok) { go(); } });
  }

  // Load a draft opened with /post/new/?draft=<id> (feed/views.py compose_post).
  function loadDraft(form) {
    var el = document.getElementById('composeDraft');
    if (!el) { return; }
    var d; try { d = JSON.parse(el.textContent); } catch (e) { return; }
    fillDraft(form, d).then(function () { markClean(form); });
  }
  // Puts a draft (feed/drafts.py draft_payload: id, content, poll,
  // poll_days, location, schedule_at, media) back into a composer.
  // Returns a promise: the photos/videos are fetched back as files.
  function fillDraft(form, d) {
    if (d.id) { form.querySelector('.js-draft-id').value = d.id; }
    var t = form.querySelector('.compose-textarea');
    if (typeof d.content === 'string' && t) { t.value = d.content; }
    if (d.poll && d.poll.length && form.querySelector('.js-cp-poll') && window.UCPolls) {
      UCPolls.setPoll(form, true);
      var inputs = form.querySelectorAll('.cp-poll-input');
      inputs.forEach(function (inp, i) { inp.value = d.poll[i] || ''; inp.hidden = i > 1 && !d.poll[i]; });
      var add = form.querySelector('.js-cp-poll-add'); if (add) { add.hidden = !form.querySelector('.cp-poll-input[hidden]'); }
      var days = form.querySelector('.cp-poll-days'); if (days) { days.value = String(d.poll_days || 1); }
    }
    if (d.location && form.querySelector('.js-cx-location')) {
      toggleLocation(form, true);
      clearTimeout(placeTimer);                       // it's already chosen: no suggestions
      form.querySelector('.js-cx-place').value = d.location;
      form.querySelector('.js-cx-places').innerHTML = '';
    }
    if (d.schedule_at && form.querySelector('.js-cx-schedule')) {
      form.querySelector('.js-cx-when').value = d.schedule_at;
      toggleSchedule(form, true);
    }
    var partEls = (d.thread || []).map(function (text) { return addPart(form, text, false); });
    if (t) { t.dispatchEvent(new Event('input', { bubbles: true })); }
    function fetchFiles(list) {
      return Promise.all(list.map(function (m) {
        return fetch(m.url, { credentials: 'same-origin' })
          .then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.blob(); })
          .then(function (b) { return new File([b], m.name, { type: m.type || b.type }); })
          .catch(function () { return null; });
      })).then(function (files) { return files.filter(Boolean); });
    }
    // The + boxes' own photos/videos.
    var partsDone = Promise.all(Object.keys(d.thread_media || {}).map(function (k) {
      var part = partEls[parseInt(k, 10) - 1];
      if (!part) { return null; }
      return fetchFiles(d.thread_media[k]).then(function (files) { if (files.length) { addPartFiles(part, files); } });
    }));
    var input = form.querySelector('.compose-media-input');
    if (!d.media || !d.media.length || !input || !window.DataTransfer) { return partsDone; }
    return Promise.all(d.media.map(function (m) {
      return fetch(m.url, { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.blob(); })
        .then(function (b) { return new File([b], m.name, { type: m.type || b.type }); })
        .catch(function () { return null; });
    })).then(function (files) {
      files = files.filter(Boolean);
      if (files.length < d.media.length && window.showToast) { showToast("Some photos or videos in this draft couldn't be loaded."); }
      if (!files.length) { return; }
      var dt = new DataTransfer();
      files.forEach(function (f) { dt.items.add(f); });
      input.disabled = false;
      input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));   // app.js shows them like freshly picked ones
    }).then(function () { return partsDone; });
  }

  // Unsent posts > Drafts on a big screen: a draft opens in the pop-up
  // composer (the same one as on Home), not the full-page one. Phones,
  // and drafts for a community, keep the full page.
  document.addEventListener('click', function (e) {
    var link = e.target.closest && e.target.closest('.js-open-draft');
    if (!link || window.innerWidth <= 768 || !window.bootstrap) { return; }
    var modalEl = document.getElementById('composePostModal');
    var data = document.getElementById('draft-data-' + link.dataset.draftId);
    if (!modalEl || !data || link.dataset.community || link.dataset.fullPage) { return; }
    e.preventDefault();
    var form = modalEl.querySelector('form.compose-form');
    clearComposer(form);
    var filling;
    try { filling = fillDraft(form, JSON.parse(data.textContent)); } catch (err) { location.href = link.href; return; }
    markClean(form);
    filling.then(function () { markClean(form); });
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
    setTimeout(function () { var t = form.querySelector('.compose-textarea'); t.focus(); t.setSelectionRange(t.value.length, t.value.length); }, 300);
  });
  // ...and the list shows the change once the pop-up closes.
  document.addEventListener('uc:draft-saved', function () {
    if (document.querySelector('.js-drafts-page')) { document.querySelector('.js-drafts-page').dataset.stale = '1'; }
  });
  document.addEventListener('hidden.bs.modal', function () {
    var page = document.querySelector('.js-drafts-page');
    if (page && page.dataset.stale && window.UC && UC.navigate) { UC.navigate(location.href); }
  });

  // Panels start switched off (their inputs disabled, so nothing is sent).
  function init(root) {
    (root || document).querySelectorAll('.js-cx-when, .js-cx-place').forEach(function (i) {
      if (i.closest('.cx-panel').hidden) { i.disabled = true; }
    });
    document.querySelectorAll('form.compose-form').forEach(function (form) {
      if (form.dataset.cxReady) { return; }
      form.dataset.cxReady = '1';
      markClean(form);
      loadDraft(form);
    });
  }

  document.addEventListener('click', function (e) {
    var t = e.target;
    var b;
    if ((b = t.closest('.js-compose-camera'))) { e.preventDefault(); pickInto(b.closest('form'), 'image/*', true); return; }
    if ((b = t.closest('.js-compose-gif'))) { e.preventDefault(); pickInto(b.closest('form'), 'image/gif', false); return; }
    if ((b = t.closest('.js-emoji-btn'))) {
      e.preventDefault();
      if (pop && !pop.hidden && pop._btn === b) { closePop(); } else { openFor(b); }
      return;
    }
    if ((b = t.closest('.js-compose-schedule'))) { var f = b.closest('form'); toggleSchedule(f, f.querySelector('.js-cx-schedule').hidden); return; }
    if ((b = t.closest('.js-cx-schedule-clear'))) { toggleSchedule(b.closest('form'), false); return; }
    if ((b = t.closest('.js-compose-location'))) { var g = b.closest('form'); toggleLocation(g, g.querySelector('.js-cx-location').hidden); return; }
    if ((b = t.closest('.js-cx-location-clear'))) { toggleLocation(b.closest('form'), false); return; }
    if ((b = t.closest('.js-compose-thread'))) { e.preventDefault(); addPart(b.closest('form'), '', true); return; }
    if ((b = t.closest('.js-cx-thread-unfile'))) {
      var pp = b.closest('.cx-thread-part');
      partFiles(pp).splice(parseInt(b.dataset.i, 10), 1);
      syncPart(pp);
      return;
    }
    if ((b = t.closest('.js-cx-thread-remove'))) {
      var tf = b.closest('form'), gone = b.closest('.cx-thread-part'), prev = gone.previousElementSibling;
      gone.remove();
      setPostLabel(tf);
      (prev ? prev.querySelector('.js-cx-thread-text') : tf.querySelector('.compose-textarea')).focus();
      return;
    }
    if ((b = t.closest('.js-cx-place-pick'))) {
      var form = b.closest('form'), input = form.querySelector('.js-cx-place');
      input.value = b.dataset.name;
      form.querySelector('.js-cx-places').innerHTML = '';
      return;
    }
    if ((b = t.closest('.js-cx-save-draft'))) { finishLeave(b.closest('form'), true); return; }
    if ((b = t.closest('.js-cx-discard'))) { finishLeave(b.closest('form'), false); return; }
    if ((b = t.closest('.js-cx-keep'))) { b.closest('.js-cx-leave').hidden = true; leaveThen = null; return; }
    // Leaving the full-page composer (its X, or the Drafts link) with unsaved words.
    if ((b = t.closest('a.compose-close-btn, a.compose-drafts-link'))) {
      var lf = b.closest('form');
      if (lf && isDirty(lf)) {
        e.preventDefault();
        var href = b.href;
        askToLeave(lf, function () { location.href = href; });
        return;
      }
    }
    if (pop && !pop.hidden && !pop.contains(t)) { closePop(); }
  });
  // The pop-up composer: closing it (X, Esc, clicking outside) with unsaved words asks first.
  document.addEventListener('hide.bs.modal', function (e) {
    var form = e.target.querySelector && e.target.querySelector('form.compose-form');
    if (!form || form.dataset.leaving || !isDirty(form)) { return; }
    e.preventDefault();
    askToLeave(form, function () {
      form.dataset.leaving = '1';
      if (window.bootstrap) { bootstrap.Modal.getOrCreateInstance(e.target).hide(); }
      setTimeout(function () { delete form.dataset.leaving; }, 600);
    });
  });
  // Sent: nothing to keep.
  document.addEventListener('submit', function (e) {
    if (e.target.matches && e.target.matches('form.compose-form')) { numberParts(e.target); e.target.dataset.leaving = '1'; markClean(e.target); }
  }, true);
  document.addEventListener('change', function (e) {
    if (!e.target.matches || !e.target.matches('.js-cx-thread-file')) { return; }
    var part = e.target.closest('.cx-thread-part');
    var picked = Array.prototype.slice.call(e.target.files || []).filter(function (f) { return partFiles(part).indexOf(f) === -1; });
    addPartFiles(part, picked);
  });
  document.addEventListener('input', function (e) {
    if (e.target.matches && e.target.matches('.js-cx-place')) { loadPlaces(e.target.closest('form'), e.target.value); }
    if (e.target.matches && e.target.matches('.js-cx-when')) { setPostLabel(e.target.closest('form')); }
    if (e.target.matches && e.target.matches('.js-cx-thread-text')) { grow(e.target); }
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { closePop(); } });
  window.addEventListener('resize', closePop);
  document.addEventListener('uc:page', function () { closePop(); init(); });
  // A composer that was just sent/closed: reset its panels.
  document.addEventListener('hidden.bs.modal', function (e) {
    var form = e.target.querySelector && e.target.querySelector('.compose-form');
    if (form) { clearThread(form); }
    if (form && form.querySelector('.js-cx-schedule')) { toggleSchedule(form, false); toggleLocation(form, false); }
    if (form) { var lv = form.querySelector('.js-cx-leave'); if (lv) { lv.hidden = true; } }
    closePop();
  });
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', function () { init(); }); } else { init(); }
})();

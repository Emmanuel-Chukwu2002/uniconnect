/* Polls in feed posts.
   Composer: the poll button (.js-compose-poll) shows the choices box
   (templates/feed/_compose_poll.html); a poll and photos/videos don't mix,
   so the photo button is switched off while the poll is on.
   Post cards: tapping a choice (.js-pp-vote) votes and swaps in the results
   (feed/polls.py vote). */
(function () {
  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ''; }

  function setPoll(form, on) {
    var box = form.querySelector('.js-cp-poll'), btn = form.querySelector('.js-compose-poll');
    if (!box) { return; }
    box.hidden = !on;
    form.querySelector('.js-cp-poll-on').value = on ? '1' : '';
    if (btn) { btn.classList.toggle('is-on', on); btn.setAttribute('aria-pressed', on ? 'true' : 'false'); }
    var media = form.querySelector('.compose-media-input');
    if (media) {
      media.disabled = on;
      var label = media.closest('label');
      if (label) { label.classList.toggle('compose-tool-disabled', on); label.title = on ? "Polls can't have photos or videos" : 'Add up to 4 photos, or a video'; }
    }
    var text = form.querySelector('.compose-textarea');
    if (text) {
      if (on) { text.dataset.placeholder = text.dataset.placeholder || text.placeholder; text.placeholder = 'Ask a question…'; text.focus(); }
      else if (text.dataset.placeholder) { text.placeholder = text.dataset.placeholder; }
    }
    if (on) { var first = box.querySelector('.cp-poll-input'); if (first && text && text.value) { first.focus(); } }
    else {
      box.querySelectorAll('.cp-poll-input').forEach(function (i, n) { i.value = ''; if (n > 1) { i.hidden = true; } });
      var add = box.querySelector('.js-cp-poll-add'); if (add) { add.hidden = false; }
    }
  }

  // compose-tools.js uses this to reopen a draft with a poll.
  window.UCPolls = { setPoll: setPoll };

  document.addEventListener('click', function (e) {
    var t = e.target;
    var pollBtn = t.closest('.js-compose-poll');
    if (pollBtn) {
      e.preventDefault();
      var form = pollBtn.closest('form');
      var hasMedia = form.querySelector('.compose-media-preview-grid') && form.querySelector('.compose-media-preview-grid').children.length;
      if (hasMedia && form.querySelector('.js-cp-poll').hidden) {
        if (window.showToast) { showToast("Remove the photos or video first — a poll can't have them."); }
        return;
      }
      setPoll(form, form.querySelector('.js-cp-poll').hidden);
      return;
    }
    var add = t.closest('.js-cp-poll-add');
    if (add) {
      var next = add.closest('.js-cp-poll').querySelector('.cp-poll-input[hidden]');
      if (next) { next.hidden = false; next.focus(); }
      if (!add.closest('.js-cp-poll').querySelector('.cp-poll-input[hidden]')) { add.hidden = true; }
      return;
    }
    var remove = t.closest('.js-cp-poll-remove');
    if (remove) { setPoll(remove.closest('form'), false); return; }

    var choice = t.closest('.js-pp-vote');
    if (choice) {
      e.preventDefault(); e.stopPropagation();
      var box = choice.closest('.js-pp'), body = new FormData();
      body.append('option', choice.getAttribute('data-option'));
      box.querySelectorAll('.js-pp-vote').forEach(function (b) { b.disabled = true; });
      fetch(box.getAttribute('data-vote-url'), { method: 'POST', body: body, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          var wrap = document.createElement('div'); wrap.innerHTML = res.html.trim();
          // The same post can be on the page twice (e.g. a repost and the original).
          var url = box.getAttribute('data-vote-url');
          document.querySelectorAll('.js-pp[data-vote-url="' + url + '"]').forEach(function (el) { el.replaceWith(wrap.firstElementChild.cloneNode(true)); });
          if (res.error && window.showToast) { showToast(res.error); }
        })
        .catch(function () { box.querySelectorAll('.js-pp-vote').forEach(function (b) { b.disabled = false; }); if (window.showToast) { showToast('Could not vote — try again.'); } });
    }
  }, true);

  // A sent or closed composer starts without a poll next time.
  document.addEventListener('hidden.bs.modal', function (e) {
    var form = e.target.querySelector && e.target.querySelector('form.compose-form');
    if (form && form.querySelector('.js-cp-poll')) { setPoll(form, false); }
  });
})();

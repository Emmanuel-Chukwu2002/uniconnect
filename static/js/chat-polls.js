/* ---------------------------------------------------------------
   Polls in group chats (chat/polls.py) — shared by the group page's
   Chat tab (group-chat.js) and Messages (chat/conversation.js).

   UCPoll.card(msg, meId)   the poll drawn inside a message bubble
   UCPoll.update(id, poll)  new counts (from the 'poll' WebSocket event)
   UCPoll.open(convId, opts) the "Make a poll" pop-up; opts.replyTo,
                            opts.onSent(message) once it's sent

   Tapping an option votes (or takes the vote back); with "more than one
   answer" each tap adds/removes that option. "View votes" shows who
   chose what. The person who made it can end the poll.
   --------------------------------------------------------------- */
(function () {
  'use strict';
  if (window.UCPoll) { return; }
  var MAX_OPTIONS = 12;

  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ''; }
  function toast(t, k) { if (window.showToast) { window.showToast(t, k); } else { window.alert(t); } }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) { e.className = cls; } if (text != null) { e.textContent = text; } return e; }
  function icon(name) { return el('i', 'bi ' + name); }
  function post(url, fields) {
    // Sent as a plain form (not multipart): an empty multipart body —
    // "End poll", or taking back your only vote — is refused by Django.
    var data = new URLSearchParams();
    Object.keys(fields).forEach(function (k) {
      [].concat(fields[k]).forEach(function (v) { data.append(k, v == null ? '' : v); });
    });
    return fetch(url, { method: 'POST', body: data, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (d) {
          if (!r.ok) { throw new Error(d.error || 'Something went wrong — try again.'); }
          return d;
        });
      });
  }

  function mineIn(option, meId) { return option.votes.some(function (v) { return v.id === meId; }); }

  // ---------------- the poll in a message ----------------
  function fill(card, poll, meId) {
    card.innerHTML = '';
    card._poll = poll;
    card.classList.toggle('is-closed', poll.closed);
    var top = el('div', 'cp-top');
    top.appendChild(icon('bi-bar-chart-fill'));
    top.appendChild(el('span', '', poll.closed ? 'Poll · ended' : 'Poll'));
    card.appendChild(top);
    card.appendChild(el('div', 'cp-question', poll.question));
    card.appendChild(el('div', 'cp-hint', poll.closed ? 'Voting has ended' : poll.multiple ? 'Select one or more' : 'Select one'));

    var most = 0;
    poll.options.forEach(function (o) { most = Math.max(most, o.votes.length); });
    var list = el('div', 'cp-options');
    list.setAttribute('role', poll.multiple ? 'group' : 'radiogroup');
    list.setAttribute('aria-label', poll.question);
    poll.options.forEach(function (o) {
      var mine = mineIn(o, meId);
      var b = el('button', 'cp-opt js-cp-opt' + (mine ? ' is-mine' : '') + (most && o.votes.length === most && poll.closed ? ' is-top' : ''));
      b.type = 'button';
      b.dataset.option = o.id;
      b.disabled = poll.closed;
      b.setAttribute('role', poll.multiple ? 'checkbox' : 'radio');
      b.setAttribute('aria-checked', mine ? 'true' : 'false');
      var mark = el('span', 'cp-mark' + (poll.multiple ? ' is-box' : ''));
      if (mine) { mark.appendChild(icon('bi-check-lg')); }
      b.appendChild(mark);
      var body = el('span', 'cp-opt-body');
      var line = el('span', 'cp-opt-line');
      line.appendChild(el('span', 'cp-opt-text', o.text));
      line.appendChild(el('span', 'cp-opt-count', String(o.votes.length)));
      body.appendChild(line);
      var bar = el('span', 'cp-bar');
      var fillBar = el('span', '');
      fillBar.style.width = (poll.voters ? Math.round(o.votes.length / poll.voters * 100) : 0) + '%';
      bar.appendChild(fillBar);
      body.appendChild(bar);
      b.appendChild(body);
      b.setAttribute('aria-label', o.text + ', ' + o.votes.length + (o.votes.length === 1 ? ' vote' : ' votes') + (mine ? ', your choice' : ''));
      list.appendChild(b);
    });
    card.appendChild(list);

    var foot = el('div', 'cp-foot');
    foot.appendChild(el('span', 'cp-total', poll.voters + (poll.voters === 1 ? ' person voted' : ' people voted')));
    if (poll.voters) {
      var view = el('button', 'cp-link js-cp-view', card._showVotes ? 'Hide votes' : 'View votes'); view.type = 'button';
      foot.appendChild(view);
    }
    if (!poll.closed && poll.by === meId) {
      var end = el('button', 'cp-link js-cp-close', 'End poll'); end.type = 'button';
      foot.appendChild(end);
    }
    card.appendChild(foot);

    if (card._showVotes && poll.voters) {
      var who = el('div', 'cp-votes');
      poll.options.forEach(function (o) {
        var sec = el('div', 'cp-votes-opt');
        var h = el('div', 'cp-votes-head');
        h.appendChild(el('b', '', o.text));
        h.appendChild(el('span', '', o.votes.length + (o.votes.length === 1 ? ' vote' : ' votes')));
        sec.appendChild(h);
        if (o.votes.length) {
          var names = el('ul', '');
          o.votes.forEach(function (v) { names.appendChild(el('li', '', v.id === meId ? 'You' : v.name)); });
          sec.appendChild(names);
        }
        who.appendChild(sec);
      });
      card.appendChild(who);
    }
  }

  function card(msg, meId) {
    var c = el('div', 'cp-card js-cp-card');
    c.dataset.msg = msg.id || '';
    c._meId = meId;
    if (msg.poll) { fill(c, msg.poll, meId); }
    return c;
  }

  function update(msgId, poll) {
    document.querySelectorAll('.js-cp-card[data-msg="' + msgId + '"]').forEach(function (c) { fill(c, poll, c._meId); });
  }

  var busy = {};
  document.addEventListener('click', function (e) {
    var b = e.target.closest('.js-cp-opt, .js-cp-view, .js-cp-close');
    if (!b) { return; }
    var c = b.closest('.js-cp-card');
    if (!c || !c._poll || !c.dataset.msg) { return; }
    e.preventDefault();
    var poll = c._poll, id = c.dataset.msg, meId = c._meId;
    if (b.classList.contains('js-cp-view')) { c._showVotes = !c._showVotes; fill(c, poll, meId); return; }
    if (busy[id]) { return; }
    if (b.classList.contains('js-cp-close')) {
      if (!window.confirm('End this poll? People won’t be able to vote any more; the results stay.')) { return; }
      busy[id] = true;
      post('/messages/poll/' + id + '/close/', {}).then(function (d) { update(id, d.poll); })
        .catch(function (err) { toast(err.message, 'error'); }).then(function () { busy[id] = false; });
      return;
    }
    // Voting: work out the new answer, show it straight away, then save.
    var opt = parseInt(b.dataset.option, 10);
    var chosen = poll.options.filter(function (o) { return mineIn(o, meId); }).map(function (o) { return o.id; });
    var had = chosen.indexOf(opt) > -1;
    if (poll.multiple) { chosen = had ? chosen.filter(function (x) { return x !== opt; }) : chosen.concat([opt]); }
    else { chosen = had ? [] : [opt]; }
    var before = JSON.parse(JSON.stringify(poll));
    var guess = JSON.parse(JSON.stringify(poll));
    var voted = false;
    guess.options.forEach(function (o) {
      o.votes = o.votes.filter(function (v) { return v.id !== meId; });
      if (chosen.indexOf(o.id) > -1) { o.votes.push({ id: meId, name: 'You' }); voted = true; }
    });
    var wasVoter = before.options.some(function (o) { return mineIn(o, meId); });
    guess.voters = before.voters + (voted && !wasVoter ? 1 : 0) - (!voted && wasVoter ? 1 : 0);
    update(id, guess);
    busy[id] = true;
    post('/messages/poll/' + id + '/vote/', { option: chosen.length ? chosen : [] })
      .then(function (d) { update(id, d.poll); })
      .catch(function (err) { update(id, before); toast(err.message, 'error'); })
      .then(function () { busy[id] = false; });
  });

  // ---------------- "Make a poll" ----------------
  var modal = null, current = null;
  function build() {
    modal = el('div', 'modal fade cp-modal');
    modal.tabIndex = -1;
    modal.setAttribute('aria-labelledby', 'cpModalTitle');
    modal.innerHTML =
      '<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable"><form class="modal-content js-cp-form" novalidate>' +
      '<div class="modal-header"><h2 class="modal-title" id="cpModalTitle"><i class="bi bi-bar-chart-fill"></i> Make a poll</h2>' +
      '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>' +
      '<div class="modal-body">' +
      '<label class="cp-label" for="cpQuestion">Question</label>' +
      '<input id="cpQuestion" class="cp-input js-cp-question" maxlength="200" placeholder="Ask something — e.g. When should we meet to read?" required>' +
      '<div class="cp-label">Options</div><div class="cp-opt-inputs js-cp-inputs"></div>' +
      '<p class="cp-note">A new box appears as you fill the last one (up to ' + MAX_OPTIONS + ').</p>' +
      '<label class="cp-switch"><input type="checkbox" class="js-cp-multiple"> Let people choose more than one answer</label>' +
      '<p class="cp-error js-cp-error" role="alert" hidden></p>' +
      '</div>' +
      '<div class="modal-footer"><button type="button" class="btn btn-light" data-bs-dismiss="modal">Cancel</button>' +
      '<button type="submit" class="btn btn-primary js-cp-send"><i class="bi bi-send-fill"></i> Send poll</button></div>' +
      '</form></div>';
    document.body.appendChild(modal);
    modal.addEventListener('input', function (e) { if (e.target.closest('.js-cp-inputs')) { tidyInputs(); } });
    modal.addEventListener('click', function (e) {
      var r = e.target.closest('.js-cp-remove');
      if (r) { r.closest('.cp-opt-row').remove(); tidyInputs(); }
    });
    modal.querySelector('.js-cp-form').addEventListener('submit', submit);
  }
  function optionRow(value) {
    var row = el('div', 'cp-opt-row');
    var inp = el('input', 'cp-input js-cp-option'); inp.maxLength = 100; inp.value = value || '';
    row.appendChild(inp);
    var x = el('button', 'cp-remove js-cp-remove'); x.type = 'button'; x.setAttribute('aria-label', 'Remove this option'); x.appendChild(icon('bi-x-lg'));
    row.appendChild(x);
    return row;
  }
  // Always one empty box at the end (until 12); numbered placeholders.
  function tidyInputs() {
    var box = modal.querySelector('.js-cp-inputs');
    var rows = box.querySelectorAll('.cp-opt-row');
    var last = rows[rows.length - 1];
    if (rows.length < MAX_OPTIONS && (!last || last.querySelector('input').value.trim())) { box.appendChild(optionRow('')); }
    while (box.querySelectorAll('.cp-opt-row').length < 2) { box.appendChild(optionRow('')); }
    box.querySelectorAll('.cp-opt-row').forEach(function (r, i, all) {
      var inp = r.querySelector('input');
      inp.placeholder = 'Option ' + (i + 1) + (i > 1 ? ' (optional)' : '');
      inp.setAttribute('aria-label', 'Option ' + (i + 1));
      r.querySelector('.js-cp-remove').hidden = all.length <= 2;
    });
  }
  function showError(t) { var e = modal.querySelector('.js-cp-error'); e.textContent = t || ''; e.hidden = !t; }
  function submit(e) {
    e.preventDefault();
    var q = modal.querySelector('.js-cp-question').value.trim();
    var opts = Array.prototype.map.call(modal.querySelectorAll('.js-cp-option'), function (i) { return i.value.trim(); }).filter(Boolean);
    if (!q) { showError('Write the question.'); modal.querySelector('.js-cp-question').focus(); return; }
    if (opts.length < 2) { showError('Add at least two options.'); return; }
    var lower = opts.map(function (o) { return o.toLowerCase(); });
    var dup = opts.filter(function (o, i) { return lower.indexOf(o.toLowerCase()) !== i; })[0];
    if (dup) { showError('“' + dup + '” is in the list twice.'); return; }
    var btn = modal.querySelector('.js-cp-send');
    btn.disabled = true;
    showError('');
    post('/messages/c/' + current.conv + '/poll/', {
      question: q, option: opts, multiple: modal.querySelector('.js-cp-multiple').checked ? '1' : '',
      reply_to: current.replyTo || '',
    }).then(function (d) {
      bootstrap.Modal.getOrCreateInstance(modal).hide();
      if (current.onSent) { current.onSent(d.message); }
    }).catch(function (err) { showError(err.message); })
      .then(function () { btn.disabled = false; });
  }
  function open(convId, opts) {
    if (!window.bootstrap) { return; }
    if (!modal) { build(); }
    current = { conv: convId, replyTo: (opts && opts.replyTo) || '', onSent: opts && opts.onSent };
    modal.querySelector('.js-cp-question').value = '';
    modal.querySelector('.js-cp-multiple').checked = false;
    modal.querySelector('.js-cp-inputs').innerHTML = '';
    showError('');
    tidyInputs();
    bootstrap.Modal.getOrCreateInstance(modal).show();
    setTimeout(function () { modal.querySelector('.js-cp-question').focus(); }, 300);
  }

  window.UCPoll = { card: card, update: update, open: open };
})();

/* =====================================================================
   UniConnect Messages — picking people
   One panel (#waPeopleSheet), four uses:
     chat      tap someone -> open (or create) your chat with them
     group     tick several people, name it -> new group
     call      tap the phone / camera next to someone -> call them
     members   tick people -> add them to a community (admins)
   ===================================================================== */
(function () {
  'use strict';
  var WA = window.WA;
  var sheet = document.getElementById('waPeopleSheet');
  if (!WA || !sheet) { return; }

  var mode = 'chat', selected = {}, onConfirm = null, searchTimer = null, lastQuery = null;
  var listEl = sheet.querySelector('.js-wa-people');

  function open(newMode, options) {
    options = options || {};
    mode = newMode; selected = {}; onConfirm = options.onConfirm || null;
    sheet.querySelector('.js-wa-sheet-title').textContent = options.title ||
      ({ chat: 'New chat', group: 'New group', call: 'New call', members: 'Add members' })[mode];
    sheet.querySelector('.js-wa-sheet-sub').textContent = mode === 'group' || mode === 'members' ? 'Tap people to select them' : '';
    sheet.querySelector('.js-wa-sheet-shortcuts').hidden = mode !== 'chat';
    sheet.querySelector('.js-wa-sheet-footer').hidden = true;
    sheet.querySelector('.js-wa-group-name').hidden = mode !== 'group';
    sheet.querySelector('.js-wa-group-name').value = '';
    renderSelected();
    var search = sheet.querySelector('.js-wa-people-search');
    search.value = '';
    lastQuery = null;
    // Wide screens: the panel covers the chat list, like WhatsApp Web.
    var pane = document.getElementById('waListPane');
    if (WA.isWide() && pane) {
      var r = pane.getBoundingClientRect();
      sheet.style.left = r.left + 'px'; sheet.style.top = r.top + 'px';
      sheet.style.width = r.width + 'px'; sheet.style.height = r.height + 'px';
    } else { sheet.style.left = sheet.style.top = sheet.style.width = sheet.style.height = ''; }
    sheet.hidden = false;
    requestAnimationFrame(function () { sheet.classList.add('is-open'); });
    load('');
    if (WA.isWide()) { search.focus({ preventScroll: true }); }
  }
  function close() {
    sheet.classList.remove('is-open');
    setTimeout(function () { sheet.hidden = true; }, 200);
  }
  WA.people = { open: open, close: close };

  function load(qText) {
    if (qText === lastQuery) { return; }
    lastQuery = qText;
    WA.getJSON('/messages/people/?q=' + encodeURIComponent(qText)).then(function (data) {
      if (qText !== lastQuery) { return; }
      listEl.innerHTML = '';
      var people = data.people.slice();
      if (mode === 'chat' && !qText) { people.unshift(data.me); }
      if (!people.length) { listEl.appendChild(WA.el('p', 'wa-note', 'Nobody found.')); return; }
      people.forEach(function (p) { listEl.appendChild(personRow(p, p.id === WA.me.id)); });
    }).catch(function () { listEl.innerHTML = ''; listEl.appendChild(WA.el('p', 'wa-note', "Couldn't load people.")); });
  }

  function personRow(p, isMe) {
    var row = WA.el(mode === 'call' ? 'div' : 'button', 'wa-person' + (selected[p.id] ? ' is-selected' : ''));
    if (mode !== 'call') { row.type = 'button'; }
    row.setAttribute('data-id', p.id);
    var av = WA.el('span', 'wa-person-avatar');
    av.appendChild(WA.avatar(p, 44));
    av.appendChild(WA.el('span', 'wa-person-check')).appendChild(WA.icon('bi-check'));
    row.appendChild(av);
    var text = WA.el('span', 'wa-person-text');
    text.appendChild(WA.el('span', 'wa-person-name', isMe ? p.name + ' (You)' : p.name));
    text.appendChild(WA.el('span', 'wa-person-about', isMe ? 'Message yourself' : p.about));
    row.appendChild(text);
    if (mode === 'call') {
      ['audio', 'video'].forEach(function (kind) {
        var b = WA.el('button', 'wa-icon-btn js-wa-call'); b.type = 'button';
        b.setAttribute('data-user', p.id); b.setAttribute('data-kind', kind);
        b.setAttribute('aria-label', (kind === 'video' ? 'Video call ' : 'Voice call ') + p.name);
        b.appendChild(WA.icon(kind === 'video' ? 'bi-camera-video' : 'bi-telephone'));
        row.appendChild(b);
      });
    }
    row._person = p;
    return row;
  }

  function renderSelected() {
    var box = sheet.querySelector('.js-wa-selected');
    var ids = Object.keys(selected);
    box.innerHTML = '';
    box.hidden = !ids.length;
    ids.forEach(function (id) {
      var chip = WA.el('button', 'wa-selected-chip'); chip.type = 'button'; chip.setAttribute('data-id', id);
      chip.appendChild(WA.avatar(selected[id], 24));
      chip.appendChild(document.createTextNode(selected[id].name.split(' ')[0]));
      chip.appendChild(WA.icon('bi-x'));
      box.appendChild(chip);
    });
    sheet.querySelector('.js-wa-sheet-footer').hidden = !ids.length || (mode !== 'group' && mode !== 'members');
  }

  function toggle(p) {
    if (selected[p.id]) { delete selected[p.id]; } else { selected[p.id] = p; }
    listEl.querySelectorAll('.wa-person[data-id="' + p.id + '"]').forEach(function (r) { r.classList.toggle('is-selected', !!selected[p.id]); });
    renderSelected();
  }

  function confirm() {
    var ids = Object.keys(selected);
    if (mode === 'group') {
      var name = sheet.querySelector('.js-wa-group-name').value.trim();
      if (!name) { WA.toast('Give the group a name.', 'error'); sheet.querySelector('.js-wa-group-name').focus(); return; }
      var form = new FormData();
      form.append('name', name);
      ids.forEach(function (id) { form.append('members', id); });
      WA.post('/messages/groups/new/', form).then(function (res) { close(); WA.navigate(res.url); })
        .catch(function (err) { WA.toast(err.message, 'error'); });
    } else if (mode === 'members' && onConfirm) {
      onConfirm(ids);
    }
  }

  sheet.addEventListener('click', function (e) {
    var t = e.target;
    if (t.closest('.js-wa-sheet-close')) { return close(); }
    if (t.closest('.js-wa-sheet-confirm')) { return confirm(); }
    if (t.closest('.js-wa-new-group')) { return open('group'); }
    var chip = t.closest('.wa-selected-chip');
    if (chip) { return toggle(selected[chip.getAttribute('data-id')]); }
    if (t.closest('.js-wa-call')) { close(); return; }  // calls.js starts the call
    var row = t.closest('.wa-person');
    if (!row || mode === 'call') { return; }
    if (mode === 'group' || mode === 'members') { return toggle(row._person); }
    // chat: open or create the conversation
    WA.post('/messages/start/' + row._person.id + '/', {}).then(function (res) { close(); WA.navigate(res.url); })
      .catch(function (err) { WA.toast(err.message, 'error'); });
  });
  sheet.querySelector('.js-wa-people-search').addEventListener('input', function (e) {
    clearTimeout(searchTimer);
    var v = e.target.value.trim();
    searchTimer = setTimeout(function () { load(v); }, 200);
  });
  sheet.querySelector('.js-wa-group-name').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); confirm(); } });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !sheet.hidden) { close(); } });

  document.addEventListener('click', function (e) {
    if (e.target.closest('.js-wa-new-chat')) { open('chat'); }
    else if (e.target.closest('.js-wa-new-group') && !sheet.contains(e.target)) { open('group'); }
    else if (e.target.closest('.js-wa-new-call')) { open('call'); }
  });
  WA.on('nav:click', function () { if (!sheet.hidden) { close(); } });
})();

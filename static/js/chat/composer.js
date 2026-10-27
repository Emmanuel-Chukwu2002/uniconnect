/* =====================================================================
   UniConnect Messages — the message box

   - text: sent over the WebSocket, shown at once with a clock icon
     until the server confirms it (then ticks)
   - "typing…": sent at most every 2.5s while typing, and "stopped"
     after 3s of no typing (the server throttles too)
   - emoji panel, photos/documents (uploaded over HTTP with progress),
     camera, and voice messages (MediaRecorder)
   - the green button is a microphone when the box is empty and a
     send button when there's something to send
   ===================================================================== */
(function () {
  'use strict';
  var WA = window.WA;
  if (!WA || !document.getElementById('waApp')) { return; }

  var EMOJI = ('😀 😃 😄 😁 😆 😅 😂 🤣 😊 😇 🙂 😉 😍 🥰 😘 😋 😎 🤩 🥳 😏 😌 😴 🤔 🤗 🤭 😐 😑 😶 🙄 😬 😮 😯 😲 😳 🥺 😢 😭 😤 😠 😡 🤯 😱 😩 🤒 🤧 ' +
    '👍 👎 👏 🙌 🙏 🤝 👋 ✌️ 🤞 👌 💪 👀 🫶 ❤️ 🧡 💛 💚 💙 💜 🖤 💔 💯 🔥 ✨ 🎉 🎊 🎓 📚 ✅ ❌ ⚡ ⭐ 🌟 ☀️ 🌙 ☕ 🍕 ⚽ 🏆 📌 📎 💡 📝').split(' ');

  var typingSent = 0, stopTimer = null, recorder = null, recChunks = [], recStart = 0, recTimer = null, recCancelled = false;

  function root() { return document.querySelector('#waMainPane .js-wa-conv'); }
  function q(sel) { var r = root(); return r && r.querySelector(sel); }
  function input() { return q('.js-wa-input'); }

  // ---------------- size + mic/send toggle ----------------
  function autosize() {
    var el = input();
    if (!el) { return; }
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 140) + 'px';
  }
  function updateButton() {
    var btn = q('.js-wa-send'), el = input();
    if (!btn || !el) { return; }
    // Group chats have their own mic button inside the input; there Send stays a paper plane (greyed while the box is empty).
    var split = !!q('.js-wa-composer .js-wa-mic');
    var mode = recorder ? 'send-voice' : (el.value.trim() ? 'send' : (split ? 'idle' : 'mic'));
    btn.setAttribute('data-mode', mode);
    btn.setAttribute('aria-disabled', mode === 'idle' ? 'true' : 'false');
    btn.setAttribute('aria-label', mode === 'mic' ? 'Record voice message' : 'Send');
    btn.firstElementChild.className = 'bi ' + (mode === 'mic' ? 'bi-mic-fill' : 'bi-send-fill');
  }

  // ---------------- typing events ----------------
  function typing() {
    var id = WA.conv.id();
    if (!id) { return; }
    var now = Date.now();
    if (now - typingSent > 2500) { WA.socket.send({ type: 'typing', conversation: id, state: true }); typingSent = now; }
    clearTimeout(stopTimer);
    stopTimer = setTimeout(stopTyping, 3000);
  }
  function stopTyping() {
    clearTimeout(stopTimer);
    var id = WA.conv.id();
    if (typingSent && id) { WA.socket.send({ type: 'typing', conversation: id, state: false }); }
    typingSent = 0;
  }

  // ---------------- replying ----------------
  var replyTo = null;
  WA.setReply = function (msg) {
    var bar = q('.js-wa-reply-bar');
    if (!bar) { return; }
    if (editing) { stopEdit(true); }
    replyTo = msg;
    bar.querySelector('.js-wa-reply-name').textContent = msg.sender && msg.sender.id === WA.me.id ? 'You' : (msg.sender ? msg.sender.name : '');
    bar.querySelector('.js-wa-reply-text').textContent = msg.content || (msg.attachment ? msg.attachment.name : '');
    bar.hidden = false;
    var el = input(); if (el) { el.focus(); }
  };
  function clearReply() {
    if (editing) { stopEdit(true); return; }
    replyTo = null; var bar = q('.js-wa-reply-bar'); if (bar) { bar.hidden = true; }
  }

  // ---------------- editing your message (chat/editing.py) ----------------
  var editing = null;
  WA.startEdit = function (msg) {
    var bar = q('.js-wa-reply-bar'), el = input();
    if (!bar || !el) { return; }
    replyTo = null; editing = msg;
    bar.querySelector('.js-wa-reply-name').textContent = 'Editing message';
    bar.querySelector('.js-wa-reply-text').textContent = msg.content || (msg.attachment ? msg.attachment.name : '');
    bar.classList.add('is-editing');
    bar.hidden = false;
    el.value = msg.content || '';
    autosize(); updateButton();
    el.focus(); el.setSelectionRange(el.value.length, el.value.length);
  };
  function stopEdit(clear) {
    editing = null;
    var bar = q('.js-wa-reply-bar');
    if (bar) { bar.hidden = true; bar.classList.remove('is-editing'); }
    var el = input();
    if (clear && el) { el.value = ''; autosize(); updateButton(); }
  }
  function saveEdit() {
    var msg = editing, el = input(), text = el.value.trim();
    if (text === (msg.content || '')) { stopEdit(true); return; }
    WA.post('/messages/m/' + msg.id + '/edit/', { content: text })
      .then(function (res) { stopEdit(true); WA.emit('edited', { conversation: res.message.conversation, message: res.message }); })
      .catch(function (err) { WA.toast(err.message, 'error'); });
  }
  function replyInfo() {
    if (!replyTo) { return null; }
    return { id: replyTo.id, name: replyTo.sender ? replyTo.sender.name : '', sender: replyTo.sender ? replyTo.sender.id : null,
      kind: replyTo.kind, text: replyTo.content || (replyTo.attachment ? replyTo.attachment.name : '') };
  }
  document.addEventListener('click', function (e) { if (e.target.closest('.js-wa-reply-cancel')) { clearReply(); } });

  // ---------------- sending text ----------------
  function sendText() {
    if (editing) { saveEdit(); return; }
    var el = input(), id = WA.conv.id();
    if (!el || !id) { return; }
    var text = el.value.trim();
    if (!text) { return; }
    if (text.length > 4000) { WA.toast('Messages can be up to 4000 characters.', 'error'); return; }
    var clientId = WA.uid();
    WA.conv.addPending({
      id: null, client_id: clientId, conversation: id, kind: 'text', sender: WA.me, content: text,
      created_at: new Date().toISOString(), status: 'pending', reactions: [], attachment: null, reply_to: replyInfo(),
    });
    WA.socket.send({ type: 'message', conversation: id, content: text, client_id: clientId, reply_to: replyTo ? replyTo.id : null });
    clearReply();
    el.value = '';
    autosize(); updateButton(); stopTyping();
    el.focus();
  }

  WA.on('error', function (e) {
    if (e.client_id) { WA.conv.failPending(e.client_id, e.error); }
    WA.toast(e.error || 'Something went wrong.', 'error');
  });

  // ---------------- files (photos, documents, voice) ----------------
  function upload(file, kind, extra) {
    var id = WA.conv.id();
    if (!id || !file) { return; }
    if (file.size > 25 * 1024 * 1024) { WA.toast('Files must be 25 MB or smaller.', 'error'); return; }
    var clientId = WA.uid();
    var label = kind === 'audio' ? 'Voice message' : file.name;
    var pending = WA.conv.addPending({
      id: null, client_id: clientId, conversation: id, kind: 'text', sender: WA.me, content: 'Uploading ' + label + '…',
      created_at: new Date().toISOString(), status: 'pending', reactions: [], attachment: null,
    });
    var form = new FormData();
    form.append('file', file, file.name || 'voice.webm');
    form.append('kind', kind);
    if (replyTo) { form.append('reply_to', replyTo.id); clearReply(); }
    Object.keys(extra || {}).forEach(function (k) { form.append(k, extra[k]); });
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/messages/c/' + id + '/upload/');
    xhr.setRequestHeader('X-CSRFToken', WA.csrf());
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.upload.onprogress = function (e) {
      var text = pending && pending.querySelector('.wa-text');
      if (text && e.lengthComputable) { text.textContent = 'Uploading ' + label + '… ' + Math.round(e.loaded / e.total * 100) + '%'; }
    };
    xhr.onload = function () {
      var res = {};
      try { res = JSON.parse(xhr.responseText); } catch (err) { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        // The real message arrives over the WebSocket; drop the placeholder.
        if (pending) { pending.remove(); }
      } else {
        WA.conv.failPending(clientId, res.error || 'Upload failed');
        WA.toast(res.error || 'Upload failed.', 'error');
      }
    };
    xhr.onerror = function () { WA.conv.failPending(clientId, 'Upload failed'); };
    xhr.send(form);
  }

  // ---------------- voice messages ----------------
  function startRecording() {
    if (!navigator.mediaDevices || !window.MediaRecorder) { WA.toast('Voice messages need a browser with microphone support.', 'error'); return; }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      recChunks = []; recCancelled = false;
      var type = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'].find(function (t) { return MediaRecorder.isTypeSupported(t); }) || '';
      recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
      recorder.ondataavailable = function (e) { if (e.data.size) { recChunks.push(e.data); } };
      recorder.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        var seconds = Math.round((Date.now() - recStart) / 1000);
        var mime = recorder.mimeType || 'audio/webm';
        recorder = null;
        showRecorder(false);
        if (recCancelled || seconds < 1 || !recChunks.length) { return; }
        var ext = mime.indexOf('ogg') > -1 ? 'ogg' : (mime.indexOf('mp4') > -1 ? 'm4a' : 'webm');
        var file = new File(recChunks, 'voice-message.' + ext, { type: mime });
        upload(file, 'audio', { duration: seconds });
      };
      recorder.start();
      recStart = Date.now();
      showRecorder(true);
    }).catch(function () { WA.toast('Microphone permission was blocked.', 'error'); });
  }
  function showRecorder(on) {
    var box = q('.js-wa-composer .wa-composer-box'), rec = q('.js-wa-recorder');
    if (box) { box.hidden = on; }
    if (rec) { rec.hidden = !on; }
    clearInterval(recTimer);
    if (on) {
      var t = q('.js-wa-rec-time');
      recTimer = setInterval(function () {
        if (t) { t.textContent = WA.formatDuration((Date.now() - recStart) / 1000); }
        if (Date.now() - recStart > 10 * 60000 && recorder) { recorder.stop(); }  // 10 minute cap
      }, 250);
    }
    updateButton();
  }

  // ---------------- emoji panel ----------------
  function buildEmoji(panel) {
    if (panel.childElementCount) { return; }
    EMOJI.forEach(function (e) {
      var b = WA.el('button', 'wa-emoji', e); b.type = 'button';
      panel.appendChild(b);
    });
  }
  function insertAtCursor(el, text) {
    var start = el.selectionStart || el.value.length, end = el.selectionEnd || el.value.length;
    el.value = el.value.slice(0, start) + text + el.value.slice(end);
    el.selectionStart = el.selectionEnd = start + text.length;
    el.focus(); autosize(); updateButton();
  }

  // ---------------- events ----------------
  document.addEventListener('input', function (e) {
    if (e.target.matches('#waMainPane .js-wa-input')) { autosize(); updateButton(); if (e.target.value.trim()) { typing(); } else { stopTyping(); } }
  });
  document.addEventListener('keydown', function (e) {
    if (!e.target.matches('#waMainPane .js-wa-input') || e.key !== 'Enter' || e.isComposing) { return; }
    var enterSends = document.getElementById('waApp').getAttribute('data-enter-send') === '1' && !('ontouchstart' in window && !WA.isWide());
    if (enterSends && !e.shiftKey) { e.preventDefault(); sendText(); }
  });
  document.addEventListener('submit', function (e) {
    if (e.target.matches('#waMainPane .js-wa-composer')) { e.preventDefault(); sendText(); }
  });
  document.addEventListener('click', function (e) {
    var t = e.target;
    var emojiPanel = q('.js-wa-emoji-panel'), attachMenu = q('.js-wa-attach-menu');
    if (t.closest('.js-wa-mic') && root() && root().contains(t)) {
      if (!recorder) { startRecording(); }
      return;
    }
    if (t.closest('.js-wa-send') && root() && root().contains(t)) {
      var mode = t.closest('.js-wa-send').getAttribute('data-mode');
      if (mode === 'send') { sendText(); }
      else if (mode === 'mic') { startRecording(); }
      else if (mode === 'send-voice' && recorder) { recorder.stop(); }
      return;
    }
    if (t.closest('.js-wa-rec-cancel') && recorder) { recCancelled = true; recorder.stop(); return; }
    if (t.closest('.js-wa-emoji-toggle')) {
      if (attachMenu) { attachMenu.hidden = true; }
      buildEmoji(emojiPanel);
      emojiPanel.hidden = !emojiPanel.hidden;
      return;
    }
    if (t.closest('.js-wa-emoji-panel .wa-emoji')) { insertAtCursor(input(), t.closest('.wa-emoji').textContent); return; }
    if (t.closest('#waMainPane .js-wa-poll')) {
      if (attachMenu) { attachMenu.hidden = true; }
      var convId = WA.conv.id();
      if (window.UCPoll && convId) {
        UCPoll.open(convId, { replyTo: replyTo ? replyTo.id : '', onSent: function (m) { clearReply(); if (m && WA.emit) { WA.emit('message', { type: 'message', message: m }); } } });
      }
      return;
    }
    if (t.closest('.js-wa-attach-toggle')) {
      if (emojiPanel) { emojiPanel.hidden = true; }
      attachMenu.hidden = !attachMenu.hidden;
      return;
    }
    if (emojiPanel && !emojiPanel.hidden && !t.closest('.js-wa-emoji-panel')) { emojiPanel.hidden = true; }
    if (attachMenu && !attachMenu.hidden && !t.closest('.js-wa-attach-menu')) { attachMenu.hidden = true; }
  });
  document.addEventListener('change', function (e) {
    if (!e.target.matches('#waMainPane .js-wa-file')) { return; }
    var kind = e.target.getAttribute('data-kind');
    Array.prototype.slice.call(e.target.files || [], 0, 10).forEach(function (f) { upload(f, kind); });
    e.target.value = '';
    var menu = q('.js-wa-attach-menu'); if (menu) { menu.hidden = true; }
  });

  // A ready-made first message passed in the address (?draft=…), e.g. from
  // the Bookshop's "Message seller": put it in the box to edit and send,
  // then drop it from the address so a refresh doesn't add it again.
  function applyDraft() {
    var params = new URLSearchParams(location.search);
    var draft = params.get('draft');
    var el = input();
    if (!draft || !el) { return; }
    if (!el.value.trim()) { el.value = draft.slice(0, 1000); }
    params.delete('draft');
    history.replaceState(history.state, '', location.pathname + (params.toString() ? '?' + params : '') + location.hash);
    autosize();
    updateButton();
    el.focus({ preventScroll: true });
    el.setSelectionRange(el.value.length, el.value.length);
  }

  WA.on('conversation:ready', function () {
    typingSent = 0;
    updateButton();
    if (WA.isWide() && input()) { input().focus({ preventScroll: true }); }
    applyDraft();
  });
  applyDraft();
  WA.on('conversation:closed', function () {
    stopTyping();
    if (recorder) { recCancelled = true; recorder.stop(); }
  });
})();

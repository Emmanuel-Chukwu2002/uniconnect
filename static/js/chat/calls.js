/* =====================================================================
   UniConnect Messages — calls

   Ringing, answering, declining and hanging up all happen live over
   the WebSocket and are saved as call history. There is no audio or
   video stream in this version (that would need WebRTC); the call
   screen says so honestly.
   ===================================================================== */
(function () {
  'use strict';
  var WA = window.WA;
  var screen = document.querySelector('.js-wa-call-screen');
  if (!WA || !screen) { return; }

  var call = null;          // {id, kind, role: 'caller'|'callee', state}
  var ringTimer = null, clockTimer = null, closeTimer = null, answeredAt = 0, ringTone = null;
  var RING_SECONDS = 30;

  function $(sel) { return screen.querySelector(sel); }

  function show(person, kind, stateText, incoming) {
    clearTimeout(closeTimer);
    var holder = $('.js-wa-call-avatar');
    holder.innerHTML = '';
    holder.appendChild(WA.avatar(person, 110));
    $('.js-wa-call-name').textContent = person.name;
    $('.js-wa-call-kind').innerHTML = '';
    $('.js-wa-call-kind').appendChild(WA.icon(kind === 'video' ? 'bi-camera-video-fill' : 'bi-telephone-fill'));
    $('.js-wa-call-kind').appendChild(document.createTextNode(kind === 'video' ? ' UniConnect video call' : ' UniConnect voice call'));
    $('.js-wa-call-state').textContent = stateText;
    $('.js-wa-call-accept').hidden = !incoming;
    screen.hidden = false;
    screen.classList.toggle('is-incoming', !!incoming);
  }
  function setState(text) { $('.js-wa-call-state').textContent = text; }
  function finish(text) {
    clearTimeout(ringTimer); clearInterval(clockTimer); stopRing();
    if (text) { setState(text); }
    $('.js-wa-call-accept').hidden = true;
    call = null;
    closeTimer = setTimeout(function () { screen.hidden = true; }, 1600);
  }

  // A soft repeating tone while ringing (generated, no audio file).
  function startRing() {
    stopRing();
    var on = true;
    ringTone = setInterval(function () { if (on) { WA.beep(); } on = !on; }, 900);
  }
  function stopRing() { clearInterval(ringTone); ringTone = null; }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.js-wa-call');
    if (btn) {
      if (call) { WA.toast("You're already in a call.", 'error'); return; }
      if (!WA.socket.isOpen()) { WA.toast("You're offline. Try again in a moment.", 'error'); return; }
      WA.socket.send({ type: 'call', action: 'start', user: parseInt(btn.getAttribute('data-user'), 10), kind: btn.getAttribute('data-kind') });
      return;
    }
    if (e.target.closest('.js-wa-call-accept') && call && call.role === 'callee') {
      WA.socket.send({ type: 'call', action: 'accept', call: call.id });
      stopRing();
      return;
    }
    if (e.target.closest('.js-wa-call-end')) {
      if (!call) { screen.hidden = true; return; }
      var action = call.state === 'connected' ? 'end' : (call.role === 'caller' ? 'cancel' : 'decline');
      WA.socket.send({ type: 'call', action: action, call: call.id });
    }
  });

  WA.on('call', function (e) {
    var s = e.state;
    if (s === 'ringing' || s === 'unavailable') {
      call = { id: e.call.id, kind: e.call.kind, role: 'caller', state: s };
      show(e.callee, e.call.kind, s === 'ringing' ? 'Ringing…' : 'Calling…', false);
      if (s === 'unavailable') { return finish(e.callee.name.split(' ')[0] + " is offline. They'll see a missed call."); }
      ringTimer = setTimeout(function () {
        if (call && call.state === 'ringing') { WA.socket.send({ type: 'call', action: 'cancel', call: call.id }); }
      }, RING_SECONDS * 1000);
      return;
    }
    if (s === 'incoming') {
      if (call) { WA.socket.send({ type: 'call', action: 'decline', call: e.call.id }); return; }  // busy
      call = { id: e.call.id, kind: e.call.kind, role: 'callee', state: 'ringing' };
      show(e.caller, e.call.kind, 'Incoming ' + (e.call.kind === 'video' ? 'video' : 'voice') + ' call…', true);
      startRing();
      return;
    }
    if (!call || call.id !== e.call.id) { return; }
    if (s === 'connected') {
      call.state = 'connected';
      clearTimeout(ringTimer); stopRing();
      $('.js-wa-call-accept').hidden = true;
      screen.classList.remove('is-incoming');
      answeredAt = Date.now();
      setState('0:00');
      clockTimer = setInterval(function () { setState(WA.formatDuration((Date.now() - answeredAt) / 1000)); }, 500);
    } else if (s === 'declined') {
      finish(call.role === 'caller' ? 'Call declined' : 'Call declined');
    } else if (s === 'missed') {
      finish(call.role === 'caller' ? 'No answer' : 'Missed call');
    } else if (s === 'ended') {
      finish('Call ended · ' + WA.formatDuration(e.call.duration));
    }
  });
})();

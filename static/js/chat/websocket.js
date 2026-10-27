/* =====================================================================
   UniConnect Messages — the WebSocket (WA.socket)

   One connection per tab to /ws/chat/. Every event from the server is
   passed on with WA.emit(event.type, event), so each feature listens
   for what it needs:  WA.on('message', fn), WA.on('typing', fn) ...

   If the connection drops it reconnects by itself (1s, 2s, 4s ... up
   to 15s) and shows a small "Reconnecting…" bar. Messages typed while
   offline wait in a queue and are sent once it's back.
   ===================================================================== */
(function () {
  'use strict';
  var WA = window.WA;
  if (!WA || !document.getElementById('waApp')) { return; }

  var ws = null, retry = 0, queue = [], banner = document.getElementById('waConn'), bannerTimer = null, everOpen = false;

  function showBanner(text) {
    clearTimeout(bannerTimer);
    // Only show it if the problem lasts a moment (avoids flashing on load).
    bannerTimer = setTimeout(function () {
      if (!banner) { return; }
      banner.textContent = text;
      banner.hidden = false;
    }, everOpen ? 600 : 1500);
  }
  function hideBanner() {
    clearTimeout(bannerTimer);
    if (banner) { banner.hidden = true; }
  }

  function connect() {
    var proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
    try { ws = new WebSocket(proto + location.host + '/ws/chat/'); }
    catch (e) { return schedule(); }

    showBanner('Connecting…');
    ws.onopen = function () {
      retry = 0;
      everOpen = true;
      hideBanner();
      WA.emit('open', {});
      var pending = queue; queue = [];
      pending.forEach(send);
    };
    ws.onmessage = function (e) {
      var data;
      try { data = JSON.parse(e.data); } catch (err) { return; }
      if (data && data.type) { WA.emit(data.type, data); }
    };
    ws.onclose = function (e) {
      WA.emit('close', {});
      if (e.code === 4401) { if (banner) { banner.textContent = 'Please sign in again to use Messages.'; banner.hidden = false; } return; }
      schedule();
    };
    ws.onerror = function () { /* onclose follows and reconnects */ };
  }

  function schedule() {
    showBanner('Reconnecting…');
    var delay = Math.min(15000, 1000 * Math.pow(2, retry++));
    setTimeout(connect, delay);
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
      return true;
    }
    // Keep chat messages for later; typing/read events are only useful now.
    if (obj.type === 'message') { queue.push(obj); }
    return false;
  }

  WA.socket = {
    send: send,
    isOpen: function () { return !!ws && ws.readyState === WebSocket.OPEN; },
  };

  // Reconnect straight away when the laptop/phone comes back online.
  window.addEventListener('online', function () { if (!ws || ws.readyState > 1) { retry = 0; connect(); } });
  connect();
})();

/* ---------------------------------------------------------------
   Counts post impressions for Post analytics (feed/analytics.py).
   A post card counts as seen once at least half of it has been on
   screen for a second. Seen ids are sent in small batches to
   /posts/seen/ every few seconds and when the page is left. The
   server keeps one view per person per post per day and ignores your
   own posts, so sending an id twice is harmless.
   --------------------------------------------------------------- */
(function () {
  'use strict';
  if (!('IntersectionObserver' in window)) { return; }
  var DWELL_MS = 1000, FLUSH_MS = 5000;
  var timers = new Map(), sent = new Set(), queue = new Set();

  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ''; }

  function flush(useBeacon) {
    if (!queue.size) { return; }
    var ids = Array.from(queue).slice(0, 100);
    ids.forEach(function (id) { queue.delete(id); sent.add(id); });
    var data = new FormData();
    data.append('ids', ids.join(','));
    data.append('csrfmiddlewaretoken', csrf());
    if (useBeacon && navigator.sendBeacon) { navigator.sendBeacon('/posts/seen/', data); return; }
    fetch('/posts/seen/', { method: 'POST', body: data, credentials: 'same-origin', keepalive: true,
      headers: { 'X-Requested-With': 'XMLHttpRequest' } }).catch(function () {});
  }

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      var id = e.target.getAttribute('data-post-id');
      if (!id || sent.has(id)) { return; }
      if (e.isIntersecting && e.intersectionRatio >= 0.5) {
        if (!timers.has(id)) {
          timers.set(id, setTimeout(function () { timers.delete(id); if (!sent.has(id)) { queue.add(id); } }, DWELL_MS));
        }
      } else if (timers.has(id)) {
        clearTimeout(timers.get(id));
        timers.delete(id);
      }
    });
  }, { threshold: [0, 0.5] });

  var watched = new WeakSet();
  function scan() {
    document.querySelectorAll('.post-card[data-post-id]').forEach(function (card) {
      if (!watched.has(card)) { watched.add(card); io.observe(card); }
    });
  }

  if ('MutationObserver' in window) {
    var pending = false;
    new MutationObserver(function () {
      if (pending) { return; }
      pending = true;
      requestAnimationFrame(function () { pending = false; scan(); });
    }).observe(document.documentElement, { childList: true, subtree: true });
  }
  document.addEventListener('uc:page', scan);
  setInterval(function () { flush(false); }, FLUSH_MS);
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'hidden') { flush(true); } });
  window.addEventListener('pagehide', function () { flush(true); });
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', scan); } else { scan(); }
})();

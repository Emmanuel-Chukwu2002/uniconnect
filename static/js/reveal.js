/* =====================================================================
   Scroll reveal: posts, events, listings, books, notifications, people…
   gently fade and glide into place every time they scroll into view,
   like the feed in most social apps.

   - Every time: an item resets quietly once it is completely off screen,
     and animates again whenever it comes back — scrolling down or up.
   - Direction-aware: scrolling down, items rise up from below; scrolling
     back up, they drift down from above.
   - What's on screen when a page opens just shows — no waiting.
   - Several items arriving together come in one after another, a beat
     apart.
   - Works whichever way the page scrolls (the middle column on wide
     screens, the whole page on phones), and picks up new content
     (pages loaded in place, profile tabs, new posts) by itself.
   - Turned off for people who ask their device for reduced motion.
   ===================================================================== */
(function () {
  'use strict';
  if (!('IntersectionObserver' in window)) { return; }
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) { return; }

  var ITEMS = [
    '.post-card',                       // Home, Bookmarks, Profile, post pages
    '.events-card', '.events-list-item', '.mkt-rec-card', // Events, Marketplace
    '.notif-item',                      // Notifications
    '.wtf-row', '.follow-request-row',  // Who to follow, requests
    '.top-story',                       // Top stories page
    '.bs-grid > .bs-card', '.bs-shelf', '.bs-myrow', '.bs-how-grid > *' // Bookshop
  ].map(function (s) { return '.app-main ' + s; }).join(', ');

  var DIST = 18;          // px an item travels while fading in
  var DURATION = 600;     // ms
  var STAGGER = 70;       // ms between items arriving together
  var EASE = 'cubic-bezier(.22,.61,.36,1)';

  var style = document.createElement('style');
  style.textContent =
    '.uc-reveal{opacity:0;transform:translate3d(0,var(--uc-from,' + DIST + 'px),0);}' +
    '.uc-reveal.uc-in{opacity:1;transform:none;' +
      'transition:opacity ' + DURATION + 'ms ' + EASE + ',transform ' + DURATION + 'ms ' + EASE + ';' +
      'transition-delay:var(--uc-delay,0ms);}';
  document.head.appendChild(style);

  // Hidden, ready for its next entrance (only ever done off screen).
  function hide(el) {
    clearTimeout(el._ucTimer);
    el.classList.remove('uc-in');
    el.classList.add('uc-reveal');
    el.style.removeProperty('--uc-delay');
  }
  // Back to normal once the entrance is over (no transform left behind).
  // Not while a viewer/pop-up covers the page: changing the feed behind
  // it then can make the browser shift the scroll position, so it waits.
  function settle(el) {
    if (pageCovered()) { el._ucTimer = setTimeout(function () { settle(el); }, 250); return; }
    el.classList.remove('uc-reveal', 'uc-in');
    el.style.removeProperty('--uc-delay');
    el.style.removeProperty('--uc-from');
  }

  // While a full-screen photo/video viewer or a pop-up covers the page,
  // the feed behind it isn't really "leaving the screen" — leave every
  // item exactly as it is, so closing the viewer never moves or replays
  // anything (and the page stays where you were).
  function pageCovered() {
    var shell = document.querySelector('.app-shell');
    return document.documentElement.classList.contains('mv-locked') ||
      document.body.classList.contains('modal-open') || !!(shell && shell.hasAttribute('inert'));
  }

  var io = new IntersectionObserver(function (entries) {
    if (pageCovered()) { return; }
    var arriving = [];
    entries.forEach(function (e) {
      var el = e.target;
      if (!e.isIntersecting) { hide(el); return; }
      if (el.classList.contains('uc-reveal') && !el.classList.contains('uc-in')) { arriving.push(e); }
    });
    arriving.sort(function (a, b) {
      return (a.boundingClientRect.top - b.boundingClientRect.top) || (a.boundingClientRect.left - b.boundingClientRect.left);
    });
    // Coming in at the top (scrolling up) cascades upwards; at the bottom, downwards.
    var mid = window.innerHeight / 2;
    var fromAbove = arriving.filter(function (e) { return e.boundingClientRect.top < mid; }).reverse();
    var fromBelow = arriving.filter(function (e) { return e.boundingClientRect.top >= mid; });
    [fromAbove, fromBelow].forEach(function (group, g) {
      group.forEach(function (e, i) {
        var el = e.target;
        var delay = Math.min(i, 5) * STAGGER;
        // Start on the side it's coming in from, then glide into place.
        el.style.setProperty('--uc-from', (g === 0 ? -DIST : DIST) + 'px');
        void el.offsetWidth;
        el.style.setProperty('--uc-delay', delay + 'ms');
        el.classList.add('uc-in');
        clearTimeout(el._ucTimer);
        el._ucTimer = setTimeout(function () { settle(el); }, DURATION + delay + 50);
      });
    });
  }, { rootMargin: '0px', threshold: 0 });

  // Watch every item. The observer reports each one straight away: those
  // off screen get hidden (unseen), those on screen are left alone.
  function scan() {
    var found = document.querySelectorAll(ITEMS);
    for (var i = 0; i < found.length; i++) {
      var el = found[i];
      if (el._ucWatched) { continue; }
      el._ucWatched = true;
      io.observe(el);
    }
  }

  var queued = false;
  function queueScan() {
    if (queued) { return; }
    queued = true;
    requestAnimationFrame(function () { queued = false; scan(); });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scan);
  } else {
    scan();
  }
  function forget(n) {
    if (n._ucWatched) { io.unobserve(n); n._ucWatched = false; }
  }
  new MutationObserver(function (records) {
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (r.addedNodes.length) { queueScan(); }
      // Stop watching items that have left the page.
      for (var j = 0; j < r.removedNodes.length; j++) {
        var n = r.removedNodes[j];
        if (n.nodeType !== 1) { continue; }
        forget(n);
        if (n.querySelectorAll) { Array.prototype.forEach.call(n.querySelectorAll(ITEMS.replace(/\.app-main /g, '')), forget); }
      }
    }
  }).observe(document.body, { childList: true, subtree: true });
})();

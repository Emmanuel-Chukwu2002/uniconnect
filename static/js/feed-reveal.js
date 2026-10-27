/* =====================================================================
   Scroll reveal: posts, events, listings, books, notifications and
   people fade in and rise gently into place as they scroll into view —
   on Home, Profile, Events, Marketplace, Bookshop, Notifications,
   Bookmarks, Top stories and Who to follow.

   How it works
   - An item waiting below the screen gets .uc-feed-wait (app.css: a
     little transparent and 24px lower). An IntersectionObserver watches
     it; the first time it enters the screen it gets .uc-feed-in, and a
     CSS transition fades it to full opacity and lifts it into place.
   - Once per item: as soon as it starts its entrance the observer stops
     watching it, and when the entrance is over both classes are removed —
     so it stays fully visible, never replays when you scroll up and down,
     and nothing is left on it (no lingering transform or opacity) to get
     in the way of videos, menus, likes, comments, reposts or the photo
     viewer.
   - Items already on screen when a page or profile tab opens simply show.
   - Items added later to a list that's already showing (more posts
     loaded as you scroll, a live notification) animate in too — even if
     they land right on screen.
   - Only opacity and transform change (both handled by the graphics
     card), the observer does the visibility work instead of scroll
     listeners, and new content is checked by looking only at what was
     added, so it stays light on phones.
   - Off for anyone whose device asks for reduced motion.
   ===================================================================== */
(function () {
  'use strict';
  if (!('IntersectionObserver' in window)) { return; }
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
  if (reduce && reduce.matches) { return; }

  // The repeated items in each page's main column (never the sidebars,
  // pop-ups or the chat).
  var ITEM = [
    '.post-card',                                          // Home, Profile, Bookmarks, post pages
    '.events-card', '.events-list-item', '.mkt-rec-card',  // Events, Marketplace
    '.notif-item',                                         // Notifications
    '.wtf-row',                                            // Who to follow, follow requests
    '.top-story',                                          // Top stories
    '.cm-card',                                            // Communities: Explore
    '.bs-grid > .bs-card', '.bs-shelf', '.bs-myrow', '.bs-how-grid > *' // Bookshop
  ].join(', ');

  var DURATION = 550; // ms — matches .uc-feed-in in app.css
  var STAGGER = 80;   // ms between items arriving together
  var MAX_STEPS = 4;  // …so a full row of cards never waits long

  // While the photo viewer or a pop-up covers the page, show items
  // instantly instead of animating them behind it.
  function covered() {
    var shell = document.querySelector('.app-shell');
    return document.documentElement.classList.contains('mv-locked') ||
      document.body.classList.contains('modal-open') || !!(shell && shell.hasAttribute('inert'));
  }

  function settle(el) {
    el.classList.remove('uc-feed-wait', 'uc-feed-in');
    el.style.removeProperty('--uc-feed-delay');
  }

  var io = new IntersectionObserver(function (entries) {
    var arriving = entries.filter(function (e) { return e.isIntersecting; })
      .sort(function (a, b) {
        return (a.boundingClientRect.top - b.boundingClientRect.top) ||
          (a.boundingClientRect.left - b.boundingClientRect.left);
      });
    arriving.forEach(function (e, i) {
      var el = e.target;
      io.unobserve(el);                         // once per item — never replayed
      if (covered()) { settle(el); return; }
      var delay = Math.min(i, MAX_STEPS) * STAGGER;
      el.style.setProperty('--uc-feed-delay', delay + 'ms');
      el.classList.add('uc-feed-in');
      setTimeout(function () { settle(el); }, DURATION + delay + 60);
    });
  }, { rootMargin: '0px 0px -40px 0px', threshold: 0 });

  function onScreen(el) {
    var r = el.getBoundingClientRect();
    return r.height > 0 && r.top < window.innerHeight && r.bottom > 0;
  }

  // Take charge of one item. `fresh` = it was just added to a list that was
  // already showing, so it animates in even if it lands on screen.
  function take(el, fresh) {
    if (el._ucFeedSeen) { return; }
    el._ucFeedSeen = true;
    if (!el.closest('.app-main')) { return; }
    // An item inside another one (say, a card inside a card) moves with
    // its parent rather than animating twice.
    if (el.parentElement && el.parentElement.closest(ITEM)) { return; }
    // A quote you just posted has its own arrival animation.
    if (el.classList.contains('post-card-new')) { return; }
    if (!fresh && onScreen(el)) { return; }    // already on screen as the page opens: just show
    el.classList.add('uc-feed-wait');          // a little faded, just below its spot, until it scrolls in
    io.observe(el);
  }

  // A whole page (first load, or loaded in place by static/js/nav.js).
  function scanPage() {
    var found = document.querySelectorAll('.app-main ' + ITEM.split(', ').join(', .app-main '));
    for (var i = 0; i < found.length; i++) { take(found[i], false); }
  }

  // New content: look only at what was added, once per frame.
  var pending = [];
  var queued = false;
  function flush() {
    queued = false;
    var batch = pending; pending = [];
    batch.forEach(function (p) {
      var n = p[0];
      if (!n.isConnected) { return; }
      if (n.matches(ITEM)) { take(n, p[1]); }
      var inner = n.querySelectorAll(ITEM);
      for (var i = 0; i < inner.length; i++) { take(inner[i], p[1]); }
    });
  }

  new MutationObserver(function (records) {
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      // Stop watching items that have left the page (if one is only being
      // moved, it comes back fully visible).
      for (var j = 0; j < r.removedNodes.length; j++) {
        var gone = r.removedNodes[j];
        if (gone.nodeType !== 1) { continue; }
        if (gone.classList.contains('uc-feed-wait')) { io.unobserve(gone); settle(gone); }
        Array.prototype.forEach.call(gone.querySelectorAll('.uc-feed-wait'), function (x) { io.unobserve(x); settle(x); });
      }
      // Something replaced (a page or profile tab swapped in) shows as a
      // page does; something only added (more posts loaded) animates in.
      var fresh = r.removedNodes.length === 0;
      for (var k = 0; k < r.addedNodes.length; k++) {
        if (r.addedNodes[k].nodeType === 1) { pending.push([r.addedNodes[k], fresh]); }
      }
    }
    if (pending.length && !queued) { queued = true; requestAnimationFrame(flush); }
  }).observe(document.body, { childList: true, subtree: true });

  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', scanPage); } else { scanPage(); }
  // A page loaded in place: anything not picked up yet shows as a page does.
  document.addEventListener('uc:page', function () { requestAnimationFrame(scanPage); });

  // Turning on "reduce motion" while the page is open: show everything now.
  if (reduce && reduce.addEventListener) {
    reduce.addEventListener('change', function () {
      if (!reduce.matches) { return; }
      io.disconnect();
      document.querySelectorAll('.uc-feed-wait, .uc-feed-in').forEach(settle);
    });
  }
})();

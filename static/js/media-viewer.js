/* =====================================================================
   UniConnect media viewer — full-screen photo viewer for posts
   (Facebook-style: X · "2 of 3" · ⋮ on top, the photo centred, the
   post's author and its Like / Comment / Repost / Share / Bookmark row
   and "Liked by" line, in UniConnect's post style, at the bottom).

   Opening: click/tap (or Enter/Space on) any post photo
   (.js-lightbox-img). The viewer collects that post's photos from the
   post card — the same images Django rendered from post.media_items
   (or post.image) — and opens on the one that was clicked.

   Moving between photos: swipe / drag left-right, scroll the mouse
   wheel / trackpad over the photo, or the ← → keys. There are no
   arrow buttons. Swipe down, Esc or X closes it (on wide screens,
   clicking the dimmed page around it too). On wide screens it sits
   over the post it came from; on phones it's full screen.
   The feed underneath is never touched, so it stays exactly where it
   was.

   Post details come from data-* attributes on the .post-card
   (see templates/feed/_post_card.html).
   ===================================================================== */
(function () {
  'use strict';

  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  var SWIPE_RATIO = 0.18;     // drag this share of the width to change photo
  var DISMISS_DISTANCE = 110; // drag down this far (px) to close

  var root = null;            // the viewer element (built once)
  var state = null;           // { card, images, index, trigger, scroll }
  var drag = null;
  var menuClosedAt = 0;
  var observer = null;

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text !== undefined) { n.textContent = text; }
    return n;
  }
  function q(sel) { return root.querySelector(sel); }
  function pad(n) { return n < 10 ? '0' + n : String(n); }

  /** "Yesterday at 6:22 PM", "Today at 9:05 AM", "5 October at 1:10 PM". */
  function postDate(iso) {
    var d = new Date(iso);
    if (isNaN(d)) { return ''; }
    var h = d.getHours(), ampm = h >= 12 ? 'PM' : 'AM';
    var time = (h % 12 || 12) + ':' + pad(d.getMinutes()) + ' ' + ampm;
    var today = new Date(); today.setHours(0, 0, 0, 0);
    var day = new Date(d); day.setHours(0, 0, 0, 0);
    var diff = Math.round((today - day) / 86400000);
    if (diff === 0) { return 'Today at ' + time; }
    if (diff === 1) { return 'Yesterday at ' + time; }
    var date = d.getDate() + ' ' + MONTHS[d.getMonth()] + (d.getFullYear() !== today.getFullYear() ? ' ' + d.getFullYear() : '');
    return date + ' at ' + time;
  }

  // ------------------------------------------------------------------
  // Building the viewer (once)
  // ------------------------------------------------------------------
  function build() {
    root = el('div', 'mv');
    root.id = 'mediaViewer';
    root.hidden = true;
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    root.setAttribute('aria-label', 'Photo viewer');
    root.innerHTML =
      '<div class="mv-frame js-mv-frame">' +
      '<div class="mv-stage js-mv-stage"><div class="mv-track js-mv-track"></div></div>' +
      '<div class="mv-top">' +
        '<button type="button" class="mv-icon-btn mv-close js-mv-close" aria-label="Close photo viewer"><i class="bi bi-x-lg"></i></button>' +
        '<div class="mv-counter js-mv-counter" aria-live="polite"></div>' +
        '<div class="dropdown mv-menu">' +
          '<button type="button" class="mv-icon-btn js-mv-menu-btn" data-bs-toggle="dropdown" aria-expanded="false" aria-label="More options"><i class="bi bi-three-dots-vertical"></i></button>' +
          '<ul class="dropdown-menu dropdown-menu-end mv-menu-list">' +
            '<li><a class="dropdown-item js-mv-open-post" href="#"><i class="bi bi-box-arrow-up-right"></i> Open post</a></li>' +
            '<li><a class="dropdown-item js-mv-download" href="#" download><i class="bi bi-download"></i> Download photo</a></li>' +
            '<li><button type="button" class="dropdown-item js-mv-copy"><i class="bi bi-link-45deg"></i> Copy photo link</button></li>' +
          '</ul>' +
        '</div>' +
      '</div>' +
      '<div class="mv-bottom js-mv-bottom">' +
        '<div class="mv-author">' +
          '<a class="mv-avatar js-mv-avatar" href="#" aria-hidden="true" tabindex="-1"></a>' +
          '<div class="mv-author-text">' +
            '<a class="mv-name js-mv-name" href="#"></a>' +
            '<div class="mv-meta"><span class="js-mv-handle"></span><span class="mv-dot js-mv-dot">&middot;</span><span class="js-mv-time"></span></div>' +
          '</div>' +
        '</div>' +
        '<div class="mv-actions">' +
          '<div class="mv-actions-left">' +
            '<button type="button" class="mv-action js-mv-like" aria-pressed="false" aria-label="Like" title="Like"><i class="bi bi-heart"></i></button>' +
            '<button type="button" class="mv-action js-mv-comment" aria-label="Comments" title="Comments"><i class="bi bi-chat"></i><span class="mv-count js-mv-comment-count"></span></button>' +
            '<span class="mv-action mv-action-disabled js-mv-repost" title="Reposting is coming soon" aria-label="Reposting is coming soon"><i class="bi bi-repeat"></i></span>' +
            '<button type="button" class="mv-action js-mv-share" aria-label="Share" title="Share"><i class="bi bi-send"></i></button>' +
          '</div>' +
          '<button type="button" class="mv-action js-mv-bookmark" aria-pressed="false" aria-label="Bookmark" title="Bookmark"><i class="bi bi-bookmark"></i></button>' +
        '</div>' +
        '<div class="mv-liked-by js-mv-liked-by"></div>' +
      '</div>' +
      '</div>';
    document.body.appendChild(root);

    q('.js-mv-close').addEventListener('click', close);
    q('.js-mv-like').addEventListener('click', function () { pressCardButton('.js-like-btn'); });
    q('.js-mv-bookmark').addEventListener('click', function () { pressCardButton('.js-bookmark-btn'); });
    q('.js-mv-comment').addEventListener('click', function () { handOff('.js-open-comments'); });
    q('.js-mv-share').addEventListener('click', function () { handOff('.js-share-post'); });
    q('.js-mv-copy').addEventListener('click', copyLink);
    root.addEventListener('hide.bs.dropdown', function () { menuClosedAt = Date.now(); });

    var stage = q('.js-mv-stage');
    stage.addEventListener('pointerdown', onDown);
    stage.addEventListener('pointermove', onMove);
    stage.addEventListener('pointerup', onUp);
    stage.addEventListener('pointercancel', onUp);
    // Nothing behind the viewer scrolls while it's open; scrolling (mouse
    // wheel / trackpad, up-down or sideways) over the photo moves to the
    // next / previous photo instead.
    root.addEventListener('wheel', onWheel, { passive: false });
    root.addEventListener('touchmove', function (e) { e.preventDefault(); }, { passive: false });
    // Wide screens: clicking the dimmed page around the viewer closes it.
    root.addEventListener('click', function (e) { if (e.target === root) { close(); } });
    window.addEventListener('resize', function () { if (state) { anchor(); place(false); } });
    // Keep the viewer's heart / bookmark / "Liked by" in step with the
    // post card (its own buttons do the work — see pressCardButton).
    observer = new MutationObserver(function () { if (state) { syncActions(true); } });
  }

  // ------------------------------------------------------------------
  // Opening / closing
  // ------------------------------------------------------------------
  function open(img) {
    var card = img.closest('.post-card');
    if (!card) { return; }
    var thumbs = Array.prototype.slice.call(card.querySelectorAll('.js-lightbox-img'));
    // The sharpest version of each photo (data-full: ImageKit's largest
    // size); what the feed already shows (currentSrc) appears first, then
    // the full one swaps in as soon as it has loaded.
    var images = thumbs.map(function (t) { return t.dataset.full || t.currentSrc || t.src; });
    var shown = thumbs.map(function (t) { return t.currentSrc || t.src; });
    // Real sizes (data-w / data-h): a small photo is shown at its true
    // size on a blurred copy of itself, never stretched to fill the viewer.
    var sizes = thumbs.map(function (t) { return { w: +t.dataset.w || 0, h: +t.dataset.h || 0 }; });
    var index = Math.max(0, thumbs.indexOf(img));
    if (!images.length) { return; }
    if (!root) { build(); }

    state = {
      card: card, images: images, index: index, trigger: img,
      scroll: { x: window.scrollX, y: window.scrollY, main: mainScroll() },
    };

    // Photos
    var track = q('.js-mv-track');
    track.innerHTML = '';
    images.forEach(function (src, i) {
      var slide = el('div', 'mv-slide');
      var pic = el('img', 'mv-img');
      var size = sizes[i];
      if (size.w && size.h && (size.w < 800 || size.h < 600)) {
        pic.classList.add('is-small');
        pic.style.setProperty('--w', size.w + 'px');
        pic.style.setProperty('--h', size.h + 'px');
        slide.classList.add('is-small');
        slide.style.setProperty('--photo-bg', "url('" + (shown[i] || src).replace(/'/g, "%27") + "')");
      }
      pic.src = shown[i] || src;
      if (shown[i] && shown[i] !== src) {
        var full = new Image();
        full.onload = function () { if (pic.isConnected) { pic.src = src; } };
        full.src = src;
      }
      pic.alt = 'Photo ' + (i + 1) + ' of ' + images.length;
      pic.draggable = false;
      slide.appendChild(pic);
      track.appendChild(slide);
    });
    root.classList.toggle('is-single', images.length === 1);

    // Post details
    var d = card.dataset;
    var name = d.authorName || (card.querySelector('.post-card-name') || {}).textContent || '';
    q('.js-mv-name').textContent = name.trim();
    q('.js-mv-name').href = d.authorUrl || '#';
    var avatar = q('.js-mv-avatar');
    avatar.href = d.authorUrl || '#';
    avatar.style.backgroundImage = d.authorPhoto ? 'url("' + d.authorPhoto.replace(/"/g, '%22') + '")' : '';
    avatar.innerHTML = d.authorPhoto ? '' : '<i class="bi bi-person-fill"></i>';
    // "@username · 5 days ago", exactly as the post card shows it.
    var handle = card.querySelector('.post-card-handle');
    var time = card.querySelector('.post-card-time');
    q('.js-mv-handle').textContent = handle ? handle.textContent.trim() : '';
    q('.js-mv-time').textContent = time ? time.textContent.trim() : (d.created ? postDate(d.created) : '');
    q('.js-mv-dot').hidden = !(q('.js-mv-handle').textContent && q('.js-mv-time').textContent);
    q('.js-mv-open-post').href = d.postUrl || '#';
    q('.js-mv-open-post').closest('li').hidden = !d.postUrl;
    syncActions(false);
    observer.disconnect();
    observer.observe(card, { subtree: true, childList: true, attributes: true, attributeFilter: ['class'] });

    // Show it
    lockPage(true);
    root.hidden = false;
    root.classList.remove('is-ui-hidden', 'is-closing');
    anchor();
    place(false);
    root.getBoundingClientRect();  // start the fade/scale from the hidden frame
    root.classList.add('is-open');
    q('.js-mv-close').focus({ preventScroll: true });
    document.addEventListener('keydown', onKey, true);
  }

  function close() {
    if (!state) { return; }
    var s = state;
    var dd = window.bootstrap && bootstrap.Dropdown.getInstance(q('.js-mv-menu-btn'));
    if (dd) { dd.hide(); }
    document.removeEventListener('keydown', onKey, true);
    if (observer) { observer.disconnect(); }
    resetWheel();
    root.classList.remove('is-open');
    root.classList.add('is-closing');
    setTimeout(function () {
      root.hidden = true;
      root.classList.remove('is-closing');
      root.style.removeProperty('--mv-dismiss');
      lockPage(false, s.scroll);
      if (s.trigger && document.contains(s.trigger)) { s.trigger.focus({ preventScroll: true }); }
    }, 180);
    state = null;
  }

  // The page behind can't scroll or be clicked/tabbed into while open;
  // its scroll position is put back exactly on close.
  function mainScroll() { var m = document.querySelector('.app-main'); return m ? m.scrollTop : 0; }
  function lockPage(on, scroll) {
    var shell = document.querySelector('.app-shell');
    document.documentElement.classList.toggle('mv-locked', on);
    if (shell) { if (on) { shell.setAttribute('inert', ''); } else { shell.removeAttribute('inert'); } }
    if (!on && scroll) {
      var m = document.querySelector('.app-main');
      // 'instant': the site uses smooth scrolling, but this must not animate.
      if (m) { m.scrollTo({ top: scroll.main, behavior: 'instant' }); }
      window.scrollTo({ left: scroll.x, top: scroll.y, behavior: 'instant' });
    }
  }

  // ------------------------------------------------------------------
  // Moving between photos
  // ------------------------------------------------------------------
  function place(animate) {
    var track = q('.js-mv-track');
    track.classList.toggle('is-animating', !!animate);
    track.style.transform = 'translate3d(' + (-state.index * 100) + '%,0,0)';
    q('.js-mv-counter').textContent = (state.index + 1) + ' of ' + state.images.length;
    q('.js-mv-download').href = state.images[state.index];
    // Only the photo on screen is exposed to screen readers.
    track.querySelectorAll('.mv-slide').forEach(function (s, i) { s.setAttribute('aria-hidden', i === state.index ? 'false' : 'true'); });
  }
  /** Wide screens: the viewer sits over the post it came from, a little
   *  smaller than the post card (16px inside it on every side) and never
   *  bigger than the window; the photo fills it and the controls sit on
   *  the photo. Phones: full screen. */
  var INSET = 16;
  function anchor() {
    var frame = q('.js-mv-frame');
    var wide = window.matchMedia('(min-width: 769px)').matches;
    root.classList.toggle('is-anchored', wide);
    if (!wide) {
      frame.style.left = frame.style.width = frame.style.top = frame.style.height = '';
      return;
    }
    var vw = window.innerWidth, vh = window.innerHeight;
    var r = state.card.getBoundingClientRect();
    if (!r.width) { r = { left: vw / 2 - 320, top: 0, width: 640, height: vh }; }
    // Width: the card's width minus the inset, at most the window's.
    var width = Math.min(r.width - 2 * INSET, vw - 2 * INSET);
    width = Math.max(Math.min(320, vw - 2 * INSET), width);
    // Height: the card's height minus the inset, at most the window's.
    var height = Math.min(r.height - 2 * INSET, vh - 2 * INSET);
    height = Math.max(Math.min(360, vh - 2 * INSET), height);
    // Centred on the part of the card that's on screen, kept inside the window.
    var visTop = Math.max(r.top, 0), visBottom = Math.min(r.top + r.height, vh);
    var cy = visBottom > visTop ? (visTop + visBottom) / 2 : vh / 2;
    var cx = r.left + r.width / 2;
    var top = Math.max(INSET, Math.min(vh - INSET - height, cy - height / 2));
    var left = Math.max(INSET, Math.min(vw - INSET - width, cx - width / 2));
    frame.style.left = Math.round(left) + 'px';
    frame.style.top = Math.round(top) + 'px';
    frame.style.width = Math.round(width) + 'px';
    frame.style.height = Math.round(height) + 'px';
  }
  // One scroll gesture = one photo. A trackpad keeps sending wheel events
  // for a second or more after the fingers lift (momentum), and a fast
  // mouse-wheel spin sends a burst; all of that counts as the same
  // gesture. Another photo needs the wheel to go quiet first (or a
  // clearly new flick in the other direction).
  var WHEEL_STEP = 30, WHEEL_QUIET = 220;
  var wheel = { sum: 0, used: false, dir: 0, last: 0 };
  function resetWheel() { wheel.sum = 0; wheel.used = false; wheel.dir = 0; wheel.last = 0; }
  function onWheel(e) {
    e.preventDefault();
    if (!state || state.images.length < 2) { return; }
    var delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
    if (e.deltaMode === 1) { delta *= 16; } else if (e.deltaMode === 2) { delta *= 400; }
    var now = e.timeStamp || performance.now();
    if (now - wheel.last > WHEEL_QUIET) { wheel.sum = 0; wheel.used = false; }  // a new gesture
    wheel.last = now;
    var dir = delta > 0 ? 1 : (delta < 0 ? -1 : 0);
    if (wheel.used) {
      // Momentum from the step just taken: ignore it. A firm flick the
      // other way is a new gesture.
      if (dir && dir !== wheel.dir && Math.abs(delta) >= WHEEL_STEP) { wheel.used = false; wheel.sum = 0; }
      else { return; }
    }
    wheel.sum += delta;
    if (Math.abs(wheel.sum) >= WHEEL_STEP) {
      wheel.dir = wheel.sum > 0 ? 1 : -1;
      wheel.used = true;
      wheel.sum = 0;
      go(state.index + wheel.dir);
    }
  }

  function go(i) {
    if (!state) { return; }
    var next = Math.max(0, Math.min(state.images.length - 1, i));
    if (next === state.index) { place(true); return; }  // bounce back at the ends
    state.index = next;
    place(true);
  }

  function onKey(e) {
    if (!state) { return; }
    if (e.key === 'Escape') {
      // Esc closes the ⋮ menu first (Bootstrap hides it just before this runs).
      if (q('.mv-menu-list.show') || Date.now() - menuClosedAt < 80) { return; }
      e.preventDefault(); close();
    } else if (e.key === 'ArrowLeft') { e.preventDefault(); go(state.index - 1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); go(state.index + 1); }
    else if (e.key === 'Tab') { trapFocus(e); }
  }
  function trapFocus(e) {
    var items = Array.prototype.filter.call(
      root.querySelectorAll('button:not([disabled]), a[href]:not([tabindex="-1"])'),
      function (n) { return n.offsetParent !== null && !n.closest('[hidden]'); }
    );
    if (!items.length) { return; }
    var first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    else if (!root.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  }

  // Swipe / drag: sideways changes photo, downwards closes, a tap
  // shows/hides the controls.
  function onDown(e) {
    if (!state || (e.pointerType === 'mouse' && e.button !== 0)) { return; }
    drag = { x: e.clientX, y: e.clientY, t: Date.now(), axis: null, id: e.pointerId };
  }
  function onMove(e) {
    if (!drag || e.pointerId !== drag.id) { return; }
    var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.axis) {
      if (Math.abs(dx) < 8 && Math.abs(dy) < 8) { return; }
      drag.axis = Math.abs(dx) > Math.abs(dy) ? 'x' : (dy > 0 ? 'y' : 'none');
      try { q('.js-mv-stage').setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
    }
    var track = q('.js-mv-track');
    if (drag.axis === 'x') {
      var atEdge = (state.index === 0 && dx > 0) || (state.index === state.images.length - 1 && dx < 0);
      var offset = atEdge ? dx / 3 : dx;   // resist past the first/last photo
      track.classList.remove('is-animating');
      track.style.transform = 'translate3d(calc(' + (-state.index * 100) + '% + ' + offset + 'px),0,0)';
    } else if (drag.axis === 'y') {
      root.style.setProperty('--mv-dismiss', Math.max(0, dy) + 'px');
      root.classList.add('is-dragging-down');
    }
  }
  function onUp(e) {
    if (!drag || e.pointerId !== drag.id) { return; }
    var dx = e.clientX - drag.x, dy = e.clientY - drag.y, dt = Date.now() - drag.t;
    var axis = drag.axis;
    drag = null;
    if (!axis) {
      if (dt < 350 && e.target.closest('.mv-slide')) { root.classList.toggle('is-ui-hidden'); }  // tap
      return;
    }
    if (axis === 'x') {
      var width = q('.js-mv-stage').clientWidth;
      var fast = Math.abs(dx) / Math.max(dt, 1) > 0.5;
      if (dx < -width * SWIPE_RATIO || (fast && dx < -30)) { go(state.index + 1); }
      else if (dx > width * SWIPE_RATIO || (fast && dx > 30)) { go(state.index - 1); }
      else { place(true); }
    } else if (axis === 'y') {
      root.classList.remove('is-dragging-down');
      if (dy > DISMISS_DISTANCE) { close(); } else { root.style.removeProperty('--mv-dismiss'); }
    }
  }

  // ------------------------------------------------------------------
  // Like / Comment / Share — the same actions as on the post card
  // ------------------------------------------------------------------
  function syncActions(fromCard) {
    if (!state) { return; }
    var card = state.card;
    // Heart
    var likeBtn = card.querySelector('.js-like-btn');
    var liked = !!(likeBtn && likeBtn.classList.contains('liked'));
    var like = q('.js-mv-like');
    if (fromCard && liked && !like.classList.contains('is-liked')) { pop(like); }
    like.hidden = !likeBtn;
    like.classList.toggle('is-liked', liked);
    like.setAttribute('aria-pressed', liked ? 'true' : 'false');
    like.setAttribute('aria-label', liked ? 'Unlike' : 'Like');
    like.title = liked ? 'Unlike' : 'Like';
    like.querySelector('i').className = 'bi ' + (liked ? 'bi-heart-fill' : 'bi-heart');
    // Comments (with the card's count)
    var commentBtn = card.querySelector('.js-open-comments');
    var countEl = commentBtn && commentBtn.querySelector('.post-card-action-count');
    q('.js-mv-comment-count').textContent = countEl ? countEl.textContent.trim() : '';
    q('.js-mv-comment').hidden = !commentBtn;
    q('.js-mv-repost').hidden = !card.querySelector('.bi-repeat');
    q('.js-mv-share').hidden = !card.querySelector('.js-share-post');
    // Bookmark
    var bmBtn = card.querySelector('.js-bookmark-btn');
    var saved = !!(bmBtn && bmBtn.classList.contains('bookmarked'));
    var bm = q('.js-mv-bookmark');
    if (fromCard && saved && !bm.classList.contains('is-saved')) { pop(bm); }
    bm.hidden = !bmBtn;
    bm.classList.toggle('is-saved', saved);
    bm.setAttribute('aria-pressed', saved ? 'true' : 'false');
    bm.setAttribute('aria-label', saved ? 'Remove bookmark' : 'Bookmark');
    bm.title = saved ? 'Remove bookmark' : 'Bookmark';
    bm.querySelector('i').className = 'bi ' + (saved ? 'bi-bookmark-fill' : 'bi-bookmark');
    // "Liked by You and 1 other" — the card's own row, copied.
    var slot = card.querySelector('.js-liked-by-slot');
    var html = slot ? slot.innerHTML.trim() : '';
    var likedBy = q('.js-mv-liked-by');
    if (likedBy.innerHTML !== html) { likedBy.innerHTML = html; }
    likedBy.hidden = !html;
  }
  function pop(btn) { btn.classList.remove('mv-pop'); void btn.offsetWidth; btn.classList.add('mv-pop'); }

  /** Like / Bookmark: press the post card's own button, so the feed's
   *  handlers do the request and update the card (heart, "Liked by",
   *  Bookmarks page); the MutationObserver then mirrors it here. */
  function pressCardButton(selector) {
    var btn = state && state.card.querySelector(selector);
    if (!btn) { return; }
    if (window.jQuery) { window.jQuery(btn).trigger('click'); } else { btn.click(); }
  }

  /** Comment / Share: close the viewer, then use the post card's own button
   *  (comments panel / share sheet), so they behave exactly as in the feed. */
  function handOff(selector) {
    var target = state && state.card.querySelector(selector);
    close();
    if (target) { setTimeout(function () { target.click(); }, 200); }
  }

  function copyLink() {
    var url = new URL(state.images[state.index], location.href).href;
    var done = function (ok) {
      if (typeof window.showToast === 'function') { window.showToast(ok ? 'Photo link copied.' : "Couldn't copy the link.", ok ? 'success' : 'error'); }
    };
    if (navigator.clipboard) { navigator.clipboard.writeText(url).then(function () { done(true); }, function () { done(false); }); }
    else { done(false); }
  }

  // ------------------------------------------------------------------
  // Wiring to the feed (event delegation: works for posts added later)
  // ------------------------------------------------------------------
  function shouldHandle(img) {
    // A photo shown inside the comments view's own media stage is
    // already being viewed there.
    return img && !img.closest('.comments-media-stage') && img.closest('.post-card');
  }
  document.addEventListener('click', function (e) {
    var img = e.target.closest('.js-lightbox-img');
    if (!shouldHandle(img)) { return; }
    e.preventDefault();
    open(img);
  });
  document.addEventListener('keydown', function (e) {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('.js-lightbox-img') && shouldHandle(e.target)) {
      e.preventDefault();
      open(e.target);
    }
  });

  window.UniMediaViewer = { open: open, close: close };
})();

/* =====================================================================
   Media feed on phones — one full-screen video at a time
   (templates/feed/home.html Media tab, _reel_item.html; app.css
   "Media feed on phones").

   Scrolling: plain CSS scroll snapping (scroll-snap-type: y mandatory)
   on #reels, so a swipe, a mouse wheel or the keyboard always settles on
   one whole video, with the browser's own smooth touch scrolling — no
   touch handlers of ours fight it.

   Playback: an IntersectionObserver on #reels picks the video that is
   on screen. It plays (muted until the student turns sound on, which
   browsers require for autoplay); every other video is paused. The
   videos either side are got ready ahead of time; ones three or more
   away are released so a long feed doesn't keep every video in memory.
   Streaming, view counting and "one video at a time" come from
   video-player.js, as for every other video in the app.

   Also here: tap the video to pause / play, the sound button, "more"
   on long captions, the follow "+" on the avatar, and the menu button
   in the tab row (opens the app's drawer, whose top bar is hidden here).
   On larger screens #reels is hidden and none of this plays anything.
   ===================================================================== */
(function () {
  'use strict';

  var PHONE = window.matchMedia('(max-width: 768px)');
  var muted = true;          // shared by every video: sound stays on once turned on
  var feed = null;           // the feed currently on the page

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  function videoOf(reel) { return reel.querySelector('video.reel-video'); }
  // (Both #reels and the bottom bar are position:fixed, so offsetParent can't tell if they're shown.)
  function visible(el) { return !!el && getComputedStyle(el).display !== 'none'; }
  function shown(root) { return PHONE.matches && visible(root); }

  // The feed stops just above the app's bottom bar, whatever its height.
  function measureBar() {
    var bar = document.querySelector('.app-mobile-bottomnav');
    var h = visible(bar) ? bar.getBoundingClientRect().height : 0;
    document.documentElement.style.setProperty('--reels-bottom', Math.round(h) + 'px');
  }

  function setSoundButtons() {
    document.querySelectorAll('.js-reel-sound').forEach(function (b) {
      b.querySelector('i').className = 'bi ' + (muted ? 'bi-volume-mute-fill' : 'bi-volume-up-fill');
      b.setAttribute('aria-label', muted ? 'Turn sound on' : 'Turn sound off');
    });
  }

  // ------------------------------------------------------------------
  // Playing the video on screen
  // ------------------------------------------------------------------
  function play(reel) {
    var v = videoOf(reel);
    if (!v || reel.classList.contains('has-error')) { return; }
    if (window.UniVideo) { window.UniVideo.prepare(v); }
    v.muted = muted;
    reel.classList.remove('is-paused');
    if (v.readyState < 3) { reel._spinTimer = setTimeout(function () { reel.classList.add('is-loading'); }, 250); }
    var p = v.play();
    if (p && p.catch) {
      p.catch(function () {
        // Sound not allowed without a fresh tap (some browsers): play muted instead.
        if (!v.muted) { muted = true; setSoundButtons(); v.muted = true; v.play().catch(function () { reel.classList.add('is-paused'); }); }
        else { reel.classList.add('is-paused'); reel.classList.remove('is-loading'); }
      });
    }
  }
  function stop(reel) {
    var v = videoOf(reel);
    clearTimeout(reel._spinTimer);
    reel.classList.remove('is-loading', 'is-playing');
    if (v && !v.paused) { v.pause(); }
  }

  function activate(f, index) {
    if (f.active === index) { return; }
    f.active = index;
    f.reels.forEach(function (reel, i) {
      var v = videoOf(reel), d = Math.abs(i - index);
      reel.classList.toggle('is-active', i === index);
      if (i !== index) { stop(reel); }
      if (!v || !window.UniVideo) { return; }
      if (d <= 1) {
        // This one and its neighbours: get them ready so the next swipe starts quickly.
        if (v.preload === 'none') { v.preload = 'metadata'; }
        window.UniVideo.prepare(v);
      } else if (d >= 3 && v.getAttribute('src') && (v.readyState > 0 || v.dataset.streaming)) {
        window.UniVideo.release(v);
      }
    });
    if (shown(f.root)) { play(f.reels[index]); }
  }

  function wireVideo(reel) {
    var v = videoOf(reel);
    if (!v) { return; }
    function done() { clearTimeout(reel._spinTimer); reel.classList.remove('is-loading'); }
    v.addEventListener('playing', function () { done(); reel.classList.add('is-playing'); reel.classList.remove('is-paused'); syncProgress(reel); });
    ['seeked', 'loadedmetadata', 'ratechange', 'waiting', 'durationchange'].forEach(function (type) {
      v.addEventListener(type, function () { syncProgress(reel); });
    });
    v.addEventListener('waiting', function () { if (reel.classList.contains('is-active') && !v.paused) { reel.classList.add('is-loading'); } });
    v.addEventListener('canplay', done);
    v.addEventListener('pause', function () { reel.classList.remove('is-playing'); done(); syncProgress(reel); });
    v.addEventListener('loadedmetadata', function () {
      reel.classList.toggle('is-landscape', v.videoWidth > v.videoHeight * 1.05);
    });
    v.addEventListener('error', function () {
      if (!v.getAttribute('src')) { return; }   // released on purpose (far away in the feed)
      // A stream that fails falls back to the MP4 in video-player.js; this
      // is the MP4 itself failing (or no source at all).
      if (!v.dataset.stream || v.dataset.streaming === 'mp4') {
        done();
        reel.classList.add('has-error');
        reel.querySelector('.reel-error').hidden = false;
      }
    });
    // A landscape poster can be spotted before the video loads, so it is
    // letterboxed straight away rather than jumping later.
    if (v.poster) {
      var img = new Image();
      img.onload = function () { if (!v.videoWidth) { reel.classList.toggle('is-landscape', img.naturalWidth > img.naturalHeight * 1.05); } };
      img.src = v.poster;
    }
  }

  // Progress bar: one linear animation per video (the Web Animations API),
  // re-synced only when the video plays, pauses, seeks or loops. It runs
  // off the main thread, so nothing on the page changes while a swipe is
  // under way (changing anything inside a snapping list mid-swipe makes
  // Chrome re-snap and cuts the swipe short). An invisible range input on
  // top takes taps and drags to seek; dragging it sideways never scrolls
  // the feed.
  function syncProgress(reel, at) {
    var v = videoOf(reel), fill = reel.querySelector('.js-reel-progress-fill');
    if (!v || !fill || !fill.animate || !(v.duration > 0) || !isFinite(v.duration)) { return; }
    var a = reel._prog;
    if (!a || a._dur !== v.duration) {
      if (a) { a.cancel(); }
      a = fill.animate([{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }], { duration: v.duration * 1000, easing: 'linear', fill: 'both' });
      a._dur = v.duration;
      reel._prog = a;
    }
    a.currentTime = (at === undefined ? v.currentTime : at) * 1000;
    if (v.paused || v.readyState < 3 || reel.classList.contains('is-seeking')) { a.pause(); } else { a.playbackRate = v.playbackRate || 1; a.play(); }
  }

  function fitCaptions(root) {
    root.querySelectorAll('.reel-info:not(.is-expanded)').forEach(function (info) {
      var cap = info.querySelector('.js-reel-caption'), more = info.querySelector('.js-reel-more');
      if (cap && more) { more.hidden = cap.scrollHeight <= cap.clientHeight + 1; }
    });
  }

  // ------------------------------------------------------------------
  // Setting up / tearing down with the page (nav.js swaps pages in place)
  // ------------------------------------------------------------------
  function teardown() {
    if (!feed) { return; }
    feed.io.disconnect();
    feed.reels.forEach(function (reel) {
      stop(reel);
      var v = videoOf(reel);
      if (v && window.UniVideo && v.getAttribute('src') && (v.readyState > 0 || v.dataset.streaming)) { window.UniVideo.release(v); }
    });
    feed = null;
  }

  function init() {
    var root = document.getElementById('reels');
    if (feed && feed.root === root) { return; }
    teardown();
    if (!root) { return; }
    measureBar();
    var f = { root: root, reels: Array.prototype.slice.call(root.querySelectorAll('.reel')), active: -1 };
    f.reels.forEach(wireVideo);
    setSoundButtons();
    f.io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting && en.intersectionRatio >= 0.6) { activate(f, f.reels.indexOf(en.target)); }
      });
    }, { root: root, threshold: [0.6] });
    f.reels.forEach(function (r) { f.io.observe(r); });
    feed = f;
    fitCaptions(root);
  }

  // Taps --------------------------------------------------------------
  document.addEventListener('click', function (e) {
    if (!feed) { return; }
    var sound = e.target.closest('.js-reel-sound');
    if (sound) {
      muted = !muted;
      setSoundButtons();
      feed.reels.forEach(function (reel) { var v = videoOf(reel); if (v) { v.muted = muted; } });
      return;
    }
    var stage = e.target.closest('.js-reel-stage');
    if (stage) {
      var reel = stage.closest('.reel'), v = videoOf(reel);
      if (!v || reel.classList.contains('has-error')) { return; }
      if (v.paused) { play(reel); } else { v.pause(); reel.classList.add('is-paused'); }
      return;
    }
    var more = e.target.closest('.js-reel-more');
    if (more) {
      var info = more.closest('.reel-info');
      var open = info.classList.toggle('is-expanded');
      info.closest('.reel').classList.toggle('caption-open', open);   // darker backdrop behind the long text
      more.textContent = open ? 'less' : 'more';
      return;
    }
    if (e.target.closest('.js-reels-menu')) {
      var drawerBtn = document.getElementById('appDrawerOpenBtn');
      if (drawerBtn) { drawerBtn.click(); }
    }
  });

  document.addEventListener('input', function (e) {
    var bar = e.target.closest && e.target.closest('.js-reel-progress');
    if (!bar) { return; }
    var reel = bar.closest('.reel'), v = videoOf(reel);
    if (v && v.duration) { v.currentTime = bar.value / 1000 * v.duration; syncProgress(reel, v.currentTime); }
  });
  ['pointerdown', 'touchstart'].forEach(function (type) {
    document.addEventListener(type, function (e) {
      var bar = e.target.closest && e.target.closest('.js-reel-progress');
      if (bar) { bar._dragging = true; var r = bar.closest('.reel'); r.classList.add('is-seeking'); syncProgress(r); }
    }, { passive: true });
  });
  ['pointerup', 'pointercancel', 'touchend', 'change'].forEach(function (type) {
    document.addEventListener(type, function () {
      document.querySelectorAll('.js-reel-progress').forEach(function (bar) {
        if (bar._dragging) { bar._dragging = false; var r = bar.closest('.reel'); r.classList.remove('is-seeking'); syncProgress(r); }
      });
    }, { passive: true });
  });

  // Follow "+" on the avatar: the app's usual follow request (POST /follow/<id>/).
  // Every UniConnect follow needs approval, so it shows "requested" until then;
  // tapping again cancels the request.
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.js-reel-follow');
    if (!btn || btn.disabled) { return; }
    btn.disabled = true;
    var userId = btn.dataset.userId;
    fetch('/follow/' + userId + '/', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' },
    }).then(function (r) { return r.ok ? r.json() : Promise.reject(); }).then(function (data) {
      document.querySelectorAll('.js-reel-follow[data-user-id="' + userId + '"]').forEach(function (b) {
        var name = (b.closest('.reel').querySelector('.reel-name') || {}).textContent || '';
        var pending = data.status === 'pending';
        b.dataset.status = data.status;
        b.querySelector('i').className = 'bi ' + (pending ? 'bi-hourglass-split' : 'bi-plus-lg');
        b.setAttribute('aria-label', pending ? 'Cancel follow request to ' + name : 'Follow ' + name);
        b.classList.remove('follow-pop'); void b.offsetWidth; b.classList.add('follow-pop');
      });
    }).catch(function () {}).then(function () { btn.disabled = false; });
  });

  // Mouse wheel / touchpad: one video per scroll, like a swipe. (Touch
  // scrolling is left entirely to the browser and the CSS snapping.)
  document.addEventListener('wheel', function (e) {
    if (!feed || !shown(feed.root) || e.ctrlKey || !e.target.closest || !e.target.closest('#reels')) { return; }
    if (e.target.closest('.reel-info.is-expanded .reel-caption')) { return; }   // scrolling a long caption
    e.preventDefault();
    var now = Date.now();
    if (now < (feed.wheelLock || 0)) { return; }
    feed.wheelSum = (feed.wheelSum || 0) + e.deltaY;
    if (Math.abs(feed.wheelSum) < 30) { return; }
    var dir = feed.wheelSum > 0 ? 1 : -1;
    feed.wheelSum = 0;
    var next = Math.max(0, Math.min(feed.reels.length - 1, (feed.active < 0 ? 0 : feed.active) + dir));
    feed.wheelLock = now + 550;
    feed.root.scrollTo({ top: feed.reels[next].offsetTop, behavior: 'smooth' });
  }, { passive: false });

  // Keep things right as the screen changes ----------------------------
  function onLayoutChange() {
    if (!feed) { return; }
    measureBar();
    fitCaptions(feed.root);
    var reel = feed.reels[feed.active];
    if (!reel) { return; }
    if (shown(feed.root)) { if (videoOf(reel) && videoOf(reel).paused && !reel.classList.contains('is-paused')) { play(reel); } }
    else { stop(reel); }   // e.g. a tablet rotated to the desktop layout
  }
  if (PHONE.addEventListener) { PHONE.addEventListener('change', onLayoutChange); } else if (PHONE.addListener) { PHONE.addListener(onLayoutChange); }
  window.addEventListener('resize', function () { clearTimeout(onLayoutChange._t); onLayoutChange._t = setTimeout(onLayoutChange, 150); });
  document.addEventListener('visibilitychange', function () {
    if (!feed) { return; }
    var reel = feed.reels[feed.active];
    if (!reel) { return; }
    if (document.hidden) { stop(reel); } else if (shown(feed.root) && !reel.classList.contains('is-paused')) { play(reel); }
  });

  document.addEventListener('uc:page', init);
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();

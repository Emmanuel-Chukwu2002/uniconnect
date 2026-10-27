/* =====================================================================
   Post videos (.js-uc-video in templates/feed/_post_media.html)

   Streaming: a video stored on ImageKit has data-stream, an adaptive
   (HLS) stream that switches between 240p and 1080p to suit the
   viewer's connection. Safari plays HLS natively; other browsers use
   hls.js (loaded from the CDN only when such a video is on the page).
   If the stream can't be played, the video falls back to its plain
   MP4 (its src), so it always plays.

   Views: once a video has played for 3 seconds (or to the end, if it's
   shorter), it's counted once (POST /video/<post id>/view/) and every
   "N views" label for that post is updated.

   Only one video plays at a time: starting one pauses the others.
   ===================================================================== */
(function () {
  'use strict';

  var HLS_SRC = 'https://cdn.jsdelivr.net/npm/hls.js@1.5.17/dist/hls.min.js';
  var VIEW_AFTER = 3;   // seconds of playback before it counts as a view
  var hlsLoading = null;
  var counted = {};     // post ids already counted on this page

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function loadHls() {
    if (window.Hls) { return Promise.resolve(window.Hls); }
    if (!hlsLoading) {
      hlsLoading = new Promise(function (resolve, reject) {
        var s = document.createElement('script');
        s.src = HLS_SRC;
        s.async = true;
        s.onload = function () { window.Hls ? resolve(window.Hls) : reject(new Error('hls.js missing')); };
        s.onerror = reject;
        document.head.appendChild(s);
      });
    }
    return hlsLoading;
  }

  // ------------------------------------------------------------------
  // Adaptive streaming, with the MP4 as a safety net
  // ------------------------------------------------------------------
  function fallBackToMp4(video) {
    if (video._ucHls) { video._ucHls.destroy(); video._ucHls = null; }
    var mp4 = video.dataset.mp4;
    if (mp4 && video.getAttribute('src') !== mp4) {
      var wasPlaying = video.dataset.wantPlay === '1';
      var t = video.currentTime || 0;
      video.src = mp4;
      video.dataset.streaming = 'mp4';
      if (t) { try { video.currentTime = t; } catch (e) { /* not seekable yet */ } }
      if (wasPlaying) { video.play().catch(function () {}); }
    }
  }

  function attachStream(video) {
    var stream = video.dataset.stream;
    if (!stream || video.dataset.streaming) { return; }
    video.dataset.mp4 = video.getAttribute('src') || '';
    video.dataset.streaming = 'pending';
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      // Safari / iOS: native HLS.
      video.src = stream;
      video.dataset.streaming = 'native-hls';
      video.addEventListener('error', function onErr() {
        video.removeEventListener('error', onErr);
        fallBackToMp4(video);
      });
      return;
    }
    loadHls().then(function (Hls) {
      if (!Hls.isSupported()) { video.dataset.streaming = 'mp4'; return; }
      // autoStartLoad:false — nothing but the small playlist is fetched
      // until the student actually presses play (saves their data).
      // abrEwmaDefaultEstimate: assume a decent connection at first (5 Mbps)
      // so playback starts sharp instead of at the blurriest size; hls.js
      // still drops down quickly if the connection really is slow.
      var hls = new Hls({ capLevelToPlayerSize: true, startLevel: -1, autoStartLoad: false, abrEwmaDefaultEstimate: 5000000 });
      video._ucHls = hls;
      hls.on(Hls.Events.ERROR, function (ev, data) {
        if (data && data.fatal) { fallBackToMp4(video); }
      });
      hls.loadSource(stream);
      hls.attachMedia(video);
      video.dataset.streaming = 'hls';
      if (video.dataset.wantPlay === '1') { startLoading(video); }
    }).catch(function () { video.dataset.streaming = 'mp4'; });
  }

  function startLoading(video) {
    if (video._ucHls && !video._ucLoading) { video._ucLoading = true; video._ucHls.startLoad(-1); }
  }

  // Set up streaming as a video comes near the screen (not all at once).
  var io = 'IntersectionObserver' in window ? new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      if (en.isIntersecting) { attachStream(en.target); io.unobserve(en.target); }
    });
  }, { rootMargin: '300px 0px' }) : null;

  function setUp(video) {
    if (video._ucReady) { return; }
    video._ucReady = true;
    if (video.dataset.stream) {
      if (io) { io.observe(video); } else { attachStream(video); }
    }
  }
  function scan(root) {
    (root || document).querySelectorAll('video.js-uc-video').forEach(setUp);
  }

  // ------------------------------------------------------------------
  // Views + one-at-a-time playback (delegated, so new posts work too)
  // ------------------------------------------------------------------
  function countView(video) {
    var id = video.dataset.postId;
    if (!id || counted[id]) { return; }
    counted[id] = true;
    fetch('/video/' + id + '/view/', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' },
    }).then(function (r) { return r.ok ? r.json() : null; }).then(function (data) {
      if (!data) { counted[id] = false; return; }
      document.querySelectorAll('.js-video-views[data-post-id="' + id + '"]').forEach(function (el) { el.textContent = data.label; });
    }).catch(function () { counted[id] = false; });
  }

  document.addEventListener('play', function (e) {
    var video = e.target;
    if (!(video instanceof HTMLVideoElement)) { return; }
    video.dataset.wantPlay = '1';
    if (video.classList.contains('js-uc-video')) { attachStream(video); startLoading(video); }
    document.querySelectorAll('video').forEach(function (other) {
      if (other !== video && !other.paused) { other.pause(); }
    });
  }, true);
  document.addEventListener('pause', function (e) {
    if (e.target instanceof HTMLVideoElement) { e.target.dataset.wantPlay = '0'; }
  }, true);
  document.addEventListener('timeupdate', function (e) {
    var v = e.target;
    if (v.classList && v.classList.contains('js-uc-video') && v.currentTime >= VIEW_AFTER) { countView(v); }
  }, true);
  document.addEventListener('ended', function (e) {
    var v = e.target;
    if (v.classList && v.classList.contains('js-uc-video')) { countView(v); }
  }, true);

  // Posts can be added to the page later (comments panel, edits).
  if ('MutationObserver' in window) {
    new MutationObserver(function (records) {
      records.forEach(function (r) {
        r.addedNodes.forEach(function (n) {
          if (n.nodeType !== 1) { return; }
          if (n.matches && n.matches('video.js-uc-video')) { setUp(n); } else if (n.querySelectorAll) { scan(n); }
        });
      });
    }).observe(document.documentElement, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', function () { scan(); }); } else { scan(); }

  // The phone video feed (reels.js) gets the next video ready before it's
  // on screen, and frees videos far behind or ahead so a long feed doesn't
  // hold every video's buffer in memory.
  function prepare(video) {
    setUp(video);
    // A released video gets its source back first.
    if (!video.getAttribute('src') && video.dataset.mp4) { video.setAttribute('src', video.dataset.mp4); }
    if (video.dataset.stream) { attachStream(video); }
  }
  function release(video) {
    if (!video.paused) { video.pause(); }
    var mp4 = video.dataset.mp4 || video.getAttribute('src');
    if (video._ucHls) { video._ucHls.destroy(); video._ucHls = null; }
    video._ucLoading = false;
    delete video.dataset.streaming;
    if (!mp4) { return; }
    video.dataset.mp4 = mp4;
    video.preload = 'none';
    video.removeAttribute('src');
    video.load();   // empties it: what was buffered is dropped; prepare() puts the source back
  }

  window.UniVideo = { scan: scan, prepare: prepare, release: release };
})();

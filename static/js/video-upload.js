/* =====================================================================
   Composer: videos and their thumbnails (templates/feed/_compose_video_extras.html)

   - Once a video is attached, an optional "Add a thumbnail" picker shows.
     If none is picked, a thumbnail is grabbed from the video right here
     in the browser (makeThumbnail) — ImageKit doesn't have to make one.
   - With ImageKit configured (data-imagekit="1"), pressing Post first
     uploads the video (and thumbnail) straight from the browser to
     ImageKit with a progress bar, using a one-time signature from
     /imagekit/auth/ (the private key never reaches the browser). Then
     the form is posted with just the ImageKit file IDs; Django checks
     them with ImageKit (feed/imagekit.py) before saving the post.
   - Without ImageKit, the video and thumbnail are posted with the form
     as before.

   The composer's own list of picked files lives in app.js
   ($(form).data('pendingMediaFiles')); this file reads it and, after a
   successful ImageKit upload, takes the video out of it so the big
   file isn't sent to Django as well.
   ===================================================================== */
(function () {
  'use strict';

  function extras(form) { return form && form.querySelector('.js-compose-video'); }
  function pendingFiles(form) {
    return (window.jQuery && window.jQuery(form).data('pendingMediaFiles')) || [];
  }
  function isVideo(file) { return (file.type || '').indexOf('video/') === 0; }
  function pendingVideo(form) {
    var files = pendingFiles(form);
    for (var i = 0; i < files.length; i++) { if (isVideo(files[i])) { return files[i]; } }
    return null;
  }

  // ------------------------------------------------------------------
  // Thumbnail picker: visible only while a new video is attached.
  // ------------------------------------------------------------------
  function syncThumbRow(form) {
    var box = extras(form);
    if (!box) { return; }
    var row = box.querySelector('.js-compose-thumb');
    var hasVideo = !!pendingVideo(form);
    row.hidden = !hasVideo;
    if (!hasVideo) { clearThumb(box); }
  }
  function clearThumb(box) {
    var input = box.querySelector('.js-compose-thumb-input');
    var preview = box.querySelector('.js-compose-thumb-preview');
    input.value = '';
    if (preview.src) { URL.revokeObjectURL(preview.src); }
    preview.removeAttribute('src');
    preview.hidden = true;
    box.querySelector('.js-compose-thumb-remove').hidden = true;
    box.querySelector('.js-compose-thumb-label').textContent = 'Add a thumbnail';
  }

  document.addEventListener('change', function (e) {
    var input = e.target;
    if (input.matches && input.matches('.js-compose-thumb-input')) {
      var box = input.closest('.js-compose-video');
      var file = input.files && input.files[0];
      if (!file) { clearThumb(box); return; }
      if ((file.type || '').indexOf('image/') !== 0) {
        clearThumb(box);
        say(box, 'The thumbnail must be an image.', true);
        return;
      }
      var preview = box.querySelector('.js-compose-thumb-preview');
      if (preview.src) { URL.revokeObjectURL(preview.src); }
      preview.src = URL.createObjectURL(file);
      preview.hidden = false;
      box.querySelector('.js-compose-thumb-remove').hidden = false;
      box.querySelector('.js-compose-thumb-label').textContent = 'Change thumbnail';
      hideProgress(box);
    } else if (input.matches && input.matches('.compose-media-input')) {
      // app.js updates its pending list in its own (jQuery) handler first.
      var form = input.closest('form');
      setTimeout(function () { rejectTooBig(form); syncThumbRow(form); }, 0);
    }
  });
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('.js-compose-thumb-remove');
    if (btn) { clearThumb(btn.closest('.js-compose-video')); return; }
    // Removing a picked video from the preview (app.js) hides the picker again.
    var remove = e.target.closest && e.target.closest('.compose-remove-image');
    if (remove) {
      var form = remove.closest('form');
      setTimeout(function () { syncThumbRow(form); }, 0);
    }
  });

  /** A video over the size limit is taken out straight away (using the
   *  preview's own remove button, so app.js stays in step), with a note
   *  saying why — rather than failing only after pressing Post. */
  function rejectTooBig(form) {
    var box = extras(form);
    if (!box) { return; }
    var maxMb = parseFloat(box.dataset.maxVideoMb) || 50;
    var files = pendingFiles(form);
    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      if (isVideo(f) && f.size > maxMb * 1024 * 1024) {
        var grid = form.querySelector('.js-new-media-grid') || form.querySelector('.compose-media-preview-grid:not(.js-existing-media-grid)');
        var item = grid && grid.querySelectorAll('.compose-media-preview-item')[i];
        var remove = item && item.querySelector('.compose-remove-image');
        if (remove) { remove.click(); }
        say(box, 'That video is ' + Math.round(f.size / 1048576) + ' MB — videos can be up to ' + maxMb +
          ' MB. Please trim it or pick a shorter clip.', true);
        return;
      }
    }
    // Everything attached fits: clear an earlier "too big" note.
    if (pendingVideo(form) && progressEls(box).wrap.classList.contains('is-error')) { hideProgress(box); }
  }

  // ------------------------------------------------------------------
  // Progress / messages under the preview
  // ------------------------------------------------------------------
  function progressEls(box) {
    return {
      wrap: box.querySelector('.js-compose-progress'),
      bar: box.querySelector('.js-compose-progress-bar'),
      text: box.querySelector('.js-compose-progress-text'),
    };
  }
  function say(box, message, isError, percent) {
    var p = progressEls(box);
    p.wrap.hidden = false;
    p.wrap.classList.toggle('is-error', !!isError);
    p.wrap.classList.toggle('has-bar', percent !== undefined);
    p.bar.style.width = (percent || 0) + '%';
    p.text.textContent = message;
  }
  function hideProgress(box) { progressEls(box).wrap.hidden = true; }

  // ------------------------------------------------------------------
  // ImageKit upload
  // ------------------------------------------------------------------
  function getAuth(box) {
    return fetch(box.dataset.authUrl, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (!r.ok) { throw new Error('Video uploads are not available right now.'); }
      return r.json();
    });
  }

  function uploadToImageKit(box, file, kind, onProgress) {
    return getAuth(box).then(function (auth) {
      var limitMb = kind === 'video' ? auth.maxVideoMb : auth.maxThumbnailMb;
      if (file.size > limitMb * 1024 * 1024) {
        throw new Error((kind === 'video' ? 'Video' : 'Thumbnail') + ' must be smaller than ' + limitMb + 'MB.');
      }
      return new Promise(function (resolve, reject) {
        var data = new FormData();
        data.append('file', file);
        data.append('fileName', (file.name || kind).replace(/[^\w.\-]+/g, '_').slice(-100));
        data.append('publicKey', auth.publicKey);
        data.append('signature', auth.signature);
        data.append('expire', String(auth.expire));
        data.append('token', auth.token);
        data.append('folder', kind === 'video' ? auth.videoFolder : auth.thumbnailFolder);
        data.append('useUniqueFileName', 'true');
        var xhr = new XMLHttpRequest();
        xhr.open('POST', auth.uploadUrl);
        xhr.upload.onprogress = function (ev) { if (ev.lengthComputable && onProgress) { onProgress(ev.loaded / ev.total); } };
        xhr.onload = function () {
          var body = {};
          try { body = JSON.parse(xhr.responseText || '{}'); } catch (err) { /* not JSON */ }
          if (xhr.status >= 200 && xhr.status < 300 && body.fileId) { resolve(body); }
          else { reject(new Error(body.message || ('Upload failed (' + xhr.status + ').'))); }
        };
        xhr.onerror = function () { reject(new Error('Upload failed — check your connection and try again.')); };
        xhr.send(data);
      });
    });
  }

  /** A JPEG thumbnail grabbed from the video in the browser (about 1s in),
   *  used when the student doesn't pick one, so ImageKit doesn't have to
   *  make it (that would use video processing units). Resolves to null if
   *  the browser can't decode this video; the post then shows the video's
   *  first frame instead. */
  function makeThumbnail(videoFile) {
    return new Promise(function (resolve) {
      var url = URL.createObjectURL(videoFile);
      var v = document.createElement('video');
      var done = false;
      function finish(file) {
        if (done) { return; }
        done = true;
        URL.revokeObjectURL(url);
        v.removeAttribute('src');
        resolve(file);
      }
      setTimeout(function () { finish(null); }, 8000);
      v.muted = true;
      v.playsInline = true;
      v.preload = 'auto';
      v.onerror = function () { finish(null); };
      v.onloadedmetadata = function () {
        var t = isFinite(v.duration) && v.duration > 0 ? Math.min(1, v.duration / 4) : 0;
        try { v.currentTime = t; } catch (e) { finish(null); }
      };
      v.onseeked = function () {
        try {
          var w = v.videoWidth, h = v.videoHeight;
          if (!w || !h) { finish(null); return; }
          var scale = Math.min(1, 1920 / Math.max(w, h));  // sharp on big and retina screens
          var canvas = document.createElement('canvas');
          canvas.width = Math.round(w * scale);
          canvas.height = Math.round(h * scale);
          canvas.getContext('2d').drawImage(v, 0, 0, canvas.width, canvas.height);
          canvas.toBlob(function (blob) {
            finish(blob ? new File([blob], 'thumbnail.jpg', { type: 'image/jpeg' }) : null);
          }, 'image/jpeg', 0.92);
        } catch (e) { finish(null); }
      };
      v.src = url;
    });
  }

  /** Takes the uploaded video out of the composer's file list and input. */
  function dropVideoFromForm(form, video) {
    var files = pendingFiles(form).filter(function (f) { return f !== video; });
    if (window.jQuery) { window.jQuery(form).data('pendingMediaFiles', files); }
    var input = form.querySelector('.compose-media-input');
    var dt = new DataTransfer();
    files.forEach(function (f) { dt.items.add(f); });
    input.files = dt.files;
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    var box = extras(form);
    if (!box || box.dataset.imagekit !== '1' || form.dataset.ikReady === '1') { return; }
    var video = pendingVideo(form);
    if (!video) { return; }
    e.preventDefault();

    var postBtn = form.querySelector('.compose-post-btn, .js-quote-submit');
    var thumbInput = box.querySelector('.js-compose-thumb-input');
    var thumb = thumbInput.files && thumbInput.files[0];
    if (postBtn) { postBtn.disabled = true; }
    form.classList.add('is-uploading');

    var steps = Promise.resolve(thumb || null);
    if (!thumb) {
      say(box, 'Making a thumbnail…', false);
      steps = makeThumbnail(video);
    }
    steps = steps.then(function (thumbFile) {
      if (!thumbFile) { return; }
      say(box, 'Uploading thumbnail…', false, 0);
      return uploadToImageKit(box, thumbFile, 'thumbnail', function (f) { say(box, 'Uploading thumbnail… ' + Math.round(f * 100) + '%', false, f * 100); })
        .then(function (res) { box.querySelector('.js-ik-thumb-id').value = res.fileId; });
    });
    steps.then(function () {
      say(box, 'Uploading video… 0%', false, 0);
      return uploadToImageKit(box, video, 'video', function (f) { say(box, 'Uploading video… ' + Math.round(f * 100) + '%', false, f * 100); });
    }).then(function (res) {
      box.querySelector('.js-ik-video-id').value = res.fileId;
      dropVideoFromForm(form, video);
      thumbInput.value = '';          // it's on ImageKit now
      say(box, 'Video uploaded — posting…', false, 100);
      form.dataset.ikReady = '1';
      // A form that sends itself in the background (the quote composer:
      // data-ajax-submit) carries on from here; others post as normal.
      if (form.dataset.ajaxSubmit === '1') {
        form.dispatchEvent(new CustomEvent('uc:ik-uploaded'));
      } else {
        HTMLFormElement.prototype.submit.call(form);
      }
    }).catch(function (err) {
      box.querySelector('.js-ik-video-id').value = '';
      box.querySelector('.js-ik-thumb-id').value = '';
      say(box, err.message || 'Upload failed.', true);
      form.classList.remove('is-uploading');
      if (postBtn) { postBtn.disabled = false; }
      if (form.dataset.ajaxSubmit === '1') { form.dispatchEvent(new CustomEvent('uc:ik-failed')); }
    });
  }, true);
})();

// Clears a field's validation error the moment the student starts
// correcting it, instead of leaving the old error showing until the
// next full page reload/submission. Searches up to the field's crispy
// wrapper (div_id_<field>) rather than assuming the error is a direct
// sibling, since the password show/hide toggle below wraps password
// inputs in an extra div.
// Toast notifications — shown for Django messages rendered on page
// load (post created/edited/deleted, profile updated, ...) AND raised
// live from JS for actions that never reload the page (follow/unfollow,
// copy link, ...), so every action gets the same feedback instead of
// only the ones that happen to trigger a full page load.
//
// Auto-dismisses after a second, but hovering pauses the timer — click
// the X and it closes immediately either way, but a 1-second timer
// alone barely leaves time to read it, let alone click to dismiss.
function dismissToast($toast) {
  clearTimeout($toast.data('dismiss-timer'));
  $toast.addClass('toast-hide');
  setTimeout(function () { $toast.remove(); }, 200);
}

function scheduleToastDismiss($toast) {
  var timer = setTimeout(function () { dismissToast($toast); }, 1000);
  $toast.data('dismiss-timer', timer);
}

function showToast(text, tag) {
  tag = tag || 'success';
  var iconClass = 'bi-info-circle-fill';
  if (tag === 'success') { iconClass = 'bi-check-circle-fill'; }
  else if (tag === 'error' || tag === 'danger') { iconClass = 'bi-exclamation-circle-fill'; }

  var $stack = $('#toastStack');
  if ($stack.length === 0) {
    $stack = $('<div class="toast-stack" id="toastStack"></div>').appendTo('body');
  }

  var $toast = $(
    '<div class="toast-message toast-' + tag + '">' +
      '<i class="bi ' + iconClass + '"></i>' +
      '<span></span>' +
      '<button type="button" class="toast-close-btn" aria-label="Dismiss"><i class="bi bi-x"></i></button>' +
    '</div>'
  );
  $toast.find('span').text(text);
  $stack.append($toast);
  scheduleToastDismiss($toast);
}

$(function () {
  // Start the auto-dismiss timer for toasts the server already
  // rendered (Django messages, via base.html's {% if messages %}).
  $('.toast-message').each(function () {
    scheduleToastDismiss($(this));
  });
  $(document).on('mouseenter', '.toast-message', function () {
    clearTimeout($(this).data('dismiss-timer'));
  });
  $(document).on('mouseleave', '.toast-message', function () {
    scheduleToastDismiss($(this));
  });
  $(document).on('click', '.toast-close-btn', function () {
    dismissToast($(this).closest('.toast-message'));
  });

  $(document).on('input change', '.is-invalid', function () {
    $(this).removeClass('is-invalid');
    $(this).closest('[id^="div_id_"]').find('.invalid-feedback').remove();
  });

  // Password show/hide toggle (Bootstrap Icons eye / eye-slash).
  // Runs for every page shown (nav.js loads pages in place).
  UC.onPage(function () { $('input[type="password"]').each(function () {
    var $input = $(this);
    if ($input.parent().hasClass('password-field-wrapper')) { return; }
    $input.wrap('<div class="password-field-wrapper"></div>');
    var $toggle = $(
      '<button type="button" class="password-toggle-btn" tabindex="-1" aria-label="Show password">' +
        '<i class="bi bi-eye"></i>' +
      '</button>'
    );
    $input.after($toggle);

    $toggle.on('click', function () {
      var isHidden = $input.attr('type') === 'password';
      $input.attr('type', isHidden ? 'text' : 'password');
      $toggle.find('i').toggleClass('bi-eye bi-eye-slash');
      $toggle.attr('aria-label', isHidden ? 'Hide password' : 'Show password');
    });
  }); });

  // -----------------------------------------------------------
  // Light / dark mode toggle (persisted in localStorage). There can
  // be more than one switch on the page at once — the desktop
  // sidebar's and the small-screen drawer's — so this targets every
  // ".js-theme-toggle-switch"/".js-theme-toggle-label" instead of a
  // single id, and keeps them all in sync with each other.
  // -----------------------------------------------------------
  function syncModeLabel() {
    var label = document.body.classList.contains('light-mode') ? 'Dark Mode' : 'Light Mode';
    document.querySelectorAll('.js-theme-toggle-label').forEach(function (el) {
      el.textContent = label;
    });
  }
  syncModeLabel();

  document.querySelectorAll('.js-theme-toggle-switch').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.body.classList.toggle('light-mode');
      var isLight = document.body.classList.contains('light-mode');
      localStorage.setItem('theme', isLight ? 'light' : 'dark');
      syncModeLabel();
    });
  });

  // -----------------------------------------------------------
  // Follow / unfollow toggle (Who to follow widget, and the profile
  // page's own Follow button). Every follow on UniConnect needs the
  // other person's approval, so the server never reports an instant
  // "following" — the response status is one of:
  //   'none'     — no relationship (any longer)
  //   'pending'  — a follow request was just sent (or cancelled from here)
  //   'accepted' — only reachable by unfollowing down to 'none'; a
  //                viewer can never click their way INTO 'accepted'
  // -----------------------------------------------------------
  function bumpFollowerCount(userId, delta) {
    // Live-updates the "X Followers" number on that user's own profile
    // page stats row, if it happens to be on screen (desktop + mobile
    // stat blocks both carry the same data-profile-user-id marker).
    $('[data-profile-user-id="' + userId + '"] .js-followers-count').each(function () {
      var $el = $(this);
      var next = Math.max(0, (parseInt($el.text(), 10) || 0) + delta);
      $el.text(next);
    });
  }

  $(document).on('click', '.follow-btn', function () {
    var $btn = $(this);
    var userId = $btn.data('user-id');
    var wasAccepted = $btn.data('status') === 'accepted';
    $.ajax({
      url: '/follow/' + userId + '/',
      type: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
      success: function (data) {
        $btn.data('status', data.status).attr('data-status', data.status);
        $btn.removeClass('btn-primary btn-outline-secondary follow-btn-pending');
        if (data.status === 'pending') {
          $btn.text('Requested').addClass('btn-outline-secondary follow-btn-pending');
          showToast('Follow request sent.');
        } else {
          $btn.text('Follow').addClass('btn-primary');
          if (wasAccepted) {
            bumpFollowerCount(userId, -1);
            showToast('Unfollowed successfully.');
          } else {
            showToast('Follow request cancelled.');
          }
        }
      }
    });
  });

  // Follow / unfollow from a post card's "..." menu — same endpoint as
  // the widget above, but this one keeps its icon and reads "Follow
  // @username" / "Requested" / "Unfollow @username" instead of a plain
  // button label.
  $(document).on('click', '.post-card-follow-btn', function () {
    var $btn = $(this);
    var userId = $btn.data('user-id');
    var username = $btn.data('username');
    var wasAccepted = $btn.data('status') === 'accepted';
    $.ajax({
      url: '/follow/' + userId + '/',
      type: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
      success: function (data) {
        var $icon = $btn.find('i');
        var $label = $btn.find('.post-card-follow-label');
        $btn.data('status', data.status).attr('data-status', data.status);
        if (data.status === 'pending') {
          $icon.attr('class', 'bi bi-hourglass-split');
          $label.text('Cancel request to @' + username);
          showToast('Follow request sent.');
        } else {
          $icon.attr('class', 'bi bi-person-plus');
          $label.text('Follow @' + username);
          if (wasAccepted) {
            bumpFollowerCount(userId, -1);
            showToast('Unfollowed successfully.');
          } else {
            showToast('Follow request cancelled.');
          }
        }
      }
    });
  });

  // -----------------------------------------------------------
  // Accept / decline a pending follow request (Follow Requests page).
  // -----------------------------------------------------------
  $(document).on('click', '.js-follow-request-accept', function () {
    var $btn = $(this);
    var $row = $btn.closest('.follow-request-row');
    $.ajax({
      url: '/follow-requests/' + $btn.data('follow-id') + '/accept/',
      type: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
      success: function (data) {
        $row.fadeOut(150, function () { $row.remove(); });
        showToast('Follow request accepted.');
      }
    });
  });

  $(document).on('click', '.js-follow-request-decline', function () {
    var $btn = $(this);
    var $row = $btn.closest('.follow-request-row');
    $.ajax({
      url: '/follow-requests/' + $btn.data('follow-id') + '/decline/',
      type: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
      success: function (data) {
        $row.fadeOut(150, function () { $row.remove(); });
        showToast('Follow request declined.');
      }
    });
  });

  // -----------------------------------------------------------
  // Like / unlike a post. Toggles the heart icon + "liked" class
  // right away, and swaps in the server-rendered "Liked by ..."
  // row (avatars + text) so it never drifts from what the database
  // actually has — simpler and safer than re-deriving that text in
  // JS from a handful of numbers.
  // -----------------------------------------------------------
  function compactCount(n) {
    n = Number(n) || 0;
    if (n < 1000) { return String(n); }
    var size = n >= 1e6 ? 1e6 : 1e3, v = n / size;
    return (v < 10 ? v.toFixed(1) : String(Math.floor(v))).replace(/\.0$/, '') + (size === 1e6 ? 'M' : 'K');
  }

  $(document).on('click', '.js-like-btn', function () {
    var $btn = $(this);
    var postId = $btn.data('post-id');
    $.ajax({
      url: '/like/' + postId + '/toggle/',
      type: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
      success: function (data) {
        var $icon = $btn.find('i');
        if (data.liked) {
          $icon.attr('class', 'bi bi-heart-fill');
          $btn.addClass('liked').attr('title', 'Unlike');
          // The little heart "pop" — only on the like-ON moment, like
          // every other app's like animation.
          $btn.removeClass('like-pop');
          requestAnimationFrame(function () {
            $btn.addClass('like-pop');
          });
        } else {
          $icon.attr('class', 'bi bi-heart');
          $btn.removeClass('liked').attr('title', 'Like');
        }
        $btn.closest('.post-card').find('.js-liked-by-slot').html(data.liked_by_html);
        // The phone video feed shows the count beside the heart (1.2K style).
        $btn.find('.js-like-count').text(compactCount(data.likes_count));
      }
    });
  });

  // Clear the one-shot pop class once its animation finishes, so it's
  // ready to replay next time (re-adding the same class name with no
  // change in between wouldn't restart the animation).
  $(document).on('animationend', '.like-pop', function () {
    $(this).removeClass('like-pop');
  });

  // -----------------------------------------------------------
  // Bookmark / un-bookmark a post. Same toggle pattern as like above:
  // flip the icon + "bookmarked" class right away from the AJAX
  // response, with the same pop animation on the save-ON moment.
  // On the Bookmarks page,
  // removing a bookmark also fades the whole post card out of the list, since
  // that page's entire point is "posts I've saved" — an unsaved post
  // doesn't belong in it anymore, unlike the main feed where
  // unbookmarking should only change the icon.
  // -----------------------------------------------------------
  $(document).on('click', '.js-bookmark-btn', function () {
    var $btn = $(this);
    var postId = $btn.data('post-id');
    $.ajax({
      url: '/bookmark/' + postId + '/toggle/',
      type: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
      success: function (data) {
        var $icon = $btn.find('i');
        if (data.bookmarked) {
          $icon.attr('class', 'bi bi-bookmark-fill');
          $btn.addClass('bookmarked').attr('title', 'Remove bookmark');
          // "Add to folder" note (static/js/bookmark-folders.js).
          document.dispatchEvent(new CustomEvent('uc:bookmarked', { detail: { postId: String(postId) } }));
          $btn.removeClass('like-pop');
          requestAnimationFrame(function () {
            $btn.addClass('like-pop');
          });
        } else {
          $icon.attr('class', 'bi bi-bookmark');
          $btn.removeClass('bookmarked').attr('title', 'Bookmark');

          var $bookmarksTab = $btn.closest('.js-bookmarks-tab');
          if ($bookmarksTab.length) {
            var $card = $btn.closest('.post-card');
            $card.fadeOut(200, function () {
              $card.remove();
              var left = $bookmarksTab.find('.post-card').length;
              // Bookmarks page: keep "N saved posts" under the heading right.
              $('.js-bookmarks-count').text(left + ' saved post' + (left === 1 ? '' : 's'));
              if (left === 0) {
                $bookmarksTab.html(
                  '<div class="center-card bookmarks-empty"><i class="bi bi-bookmark"></i><h4>No bookmarks yet.</h4><p>Posts you save will appear here.</p></div>'
                );
              }
            });
          }
        }
      }
    });
  });

  // -----------------------------------------------------------
  // Delete post — a custom modal confirmation instead of the
  // browser's native confirm() popup, styled to match the app. The
  // same confirm modal is reused for deleting a comment (see the
  // Comments section below), so each flow clears the other's pending
  // state and resets the modal's title before showing it.
  // -----------------------------------------------------------
  var $pendingDeleteForm = null;

  $(document).on('click', '.js-confirm-delete-post', function () {
    $pendingDeleteForm = $(this).closest('.post-card-delete-form');
    $pendingDeleteCommentBtn = null;
    $pendingDeleteReplyCommentId = null;
    var modalEl = document.getElementById('confirmDeleteModal');
    if (modalEl) {
      // The first post of a thread takes the thread with it (feed/threads.py).
      $(modalEl).find('.confirm-modal-title').text($(this).data('confirmTitle') || ($(this).data('confirmText') ? 'Delete this thread?' : 'Delete this post?'));
      $(modalEl).find('.confirm-modal-text').text($(this).data('confirmText') || "This can't be undone.");
    }
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  });

  // Same shared confirm modal, for deleting an event (Events tab) or a
  // venue (Venues tab) — the submit handler on #confirmDeleteModalBtn
  // above already just submits whatever $pendingDeleteForm is, so
  // these two only need to point it at the right hidden form.
  $(document).on('click', '.js-confirm-delete-event', function () {
    $pendingDeleteForm = $(this).closest('.events-card-banner').find('.event-delete-form');
    $pendingDeleteCommentBtn = null;
    $pendingDeleteReplyCommentId = null;
    var modalEl = document.getElementById('confirmDeleteModal');
    if (modalEl) {
      $(modalEl).find('.confirm-modal-title').text('Delete this event?');
      $(modalEl).find('.confirm-modal-text').text("This can't be undone, and any registrations for it will be removed too.");
    }
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  });

  // Block @user (post menus, profile menu): the same confirm modal,
  // with the button saying "Block" instead of "Delete".
  $(document).on('submit', '.js-block-form', function (e) {
    var modalEl = document.getElementById('confirmDeleteModal');
    if (!modalEl || !window.bootstrap) { return; }   // no modal: just block
    e.preventDefault();
    $pendingDeleteForm = $(this);
    $pendingDeleteCommentBtn = null;
    $pendingDeleteReplyCommentId = null;
    var name = $(this).data('name') || 'this person';
    $(modalEl).find('.confirm-modal-title').text('Block ' + name + '?');
    $(modalEl).find('.confirm-modal-text').text("You won't see each other's posts or profiles, can't message each other, and any follows between you are removed. You can unblock any time in Settings.");
    $('#confirmDeleteModalBtn').text('Block');
    $(modalEl).one('hidden.bs.modal', function () { $('#confirmDeleteModalBtn').text('Delete'); });
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  });

  // "Not interested in this post": the card folds into a one-line note
  // with Undo (feed/post_settings.py hide_post toggles it back).
  $(document).on('submit', '.js-hide-post-form', function (e) {
    var $card = $(this).closest('.post-card');
    if (!$card.length) { return; }   // Post Details page: a normal submit
    e.preventDefault();
    var form = this, url = this.action, token = $(this).find('[name=csrfmiddlewaretoken]').val();
    $.ajax({ url: url, type: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': token } })
      .done(function () {
        var $note = $('<div class="post-hidden-note"><i class="bi bi-eye-slash"></i><span>Thanks — you won\'t see this post any more.</span><button type="button">Undo</button></div>');
        $card.hide().after($note);
        $note.find('button').on('click', function () {
          $.ajax({ url: url, type: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': token } })
            .done(function () { $note.remove(); $card.show(); })
            .fail(function () { showToast('Could not bring the post back.', 'error'); });
        });
      })
      .fail(function () { form.submit(); });
  });

  $(document).on('click', '.js-confirm-delete-venue', function () {
    $pendingDeleteForm = $(this).closest('.events-list-item').find('.venue-delete-form');
    $pendingDeleteCommentBtn = null;
    $pendingDeleteReplyCommentId = null;
    var modalEl = document.getElementById('confirmDeleteModal');
    if (modalEl) {
      $(modalEl).find('.confirm-modal-title').text('Delete this venue?');
      $(modalEl).find('.confirm-modal-text').text("This can't be undone.");
    }
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  });

  // Same shared confirm modal again, for deleting a marketplace
  // listing (Marketplace "Mine" tab).
  $(document).on('click', '.js-confirm-delete-listing', function () {
    $pendingDeleteForm = $(this).closest('.events-card-banner').find('.listing-delete-form');
    $pendingDeleteCommentBtn = null;
    $pendingDeleteReplyCommentId = null;
    var modalEl = document.getElementById('confirmDeleteModal');
    if (modalEl) {
      $(modalEl).find('.confirm-modal-title').text('Delete this listing?');
      $(modalEl).find('.confirm-modal-text').text("This can't be undone.");
    }
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  });

  // Marking a listing sold/available is reversible, so it just submits
  // its hidden form directly — no confirm modal needed.
  $(document).on('click', '.js-confirm-toggle-sold', function () {
    $(this).closest('.events-card-banner').find('.listing-toggle-sold-form').submit();
  });

  // Register-for-event modal (Events tab card) — clicking "Register"
  // opens a small modal, centered on that event, to pick a role
  // instead of registering immediately as a plain attendee.
  $(document).on('click', '.js-open-register-modal', function () {
    var $btn = $(this);
    var $card = $btn.closest('.events-card');
    var eventId = $btn.data('event-id');
    var eventTitle = $btn.data('event-title');
    $('#eventRegisterEventId').val(eventId);
    $('#eventRegisterEventTitle').text(eventTitle);
    $('#eventRegisterNext').val(window.location.pathname + window.location.search);
    $('#eventRegisterRoleSelect').val('attendee');

    // Pin the modal over the exact card that was clicked — centered on
    // it both ways, sized smaller than the card itself (see
    // .event-register-modal-dialog's fixed width in app.css) — instead
    // of Bootstrap's default viewport-centered placement, so it reads
    // as "this event's" popup rather than a generic one floating over
    // the whole page.
    var $dialog = $('#eventRegisterModal .event-register-modal-dialog');
    var modalEl = document.getElementById('eventRegisterModal');
    if ($card.length && modalEl) {
      var rect = $card[0].getBoundingClientRect();
      var dialogWidth = Math.min(340, rect.width - 24);
      var left = rect.left + (rect.width - dialogWidth) / 2;
      // .modal-dialog-centered forces a flex box tall enough to vertically
      // center its content within the whole viewport (min-height: calc(100%
      // - 3.5rem)) — harmless when Bootstrap is also centering it, but once
      // we pin top/left ourselves that invisible box balloons past the
      // card underneath. Drop it so the dialog sizes to its own content.
      $dialog.removeClass('modal-dialog-centered').css({
        position: 'fixed', left: left + 'px', width: dialogWidth + 'px', margin: 0,
      });
      // Setting display:block ourselves, before Bootstrap's own show()
      // runs, renders the dialog synchronously — so its real height
      // (title + event field + role field + footer, set by app.css) is
      // measurable right away instead of only after Bootstrap's fade-in
      // finishes a frame or two later. Centering on a guessed height
      // left more gap on one side than the other.
      modalEl.style.display = 'block';
      var dialogHeight = $dialog.outerHeight();
      var idealTop = rect.top + (rect.height / 2) - (dialogHeight / 2);
      var top = Math.max(16, Math.min(idealTop, window.innerHeight - dialogHeight - 16));
      $dialog.css('top', top + 'px');
    } else {
      $dialog.addClass('modal-dialog-centered').removeAttr('style');
    }

    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  });

  // Clear the pinned position once closed, so a stale position never
  // shows for a split second before the next card's position is set.
  $('#eventRegisterModal').on('hidden.bs.modal', function () {
    $('#eventRegisterModal .event-register-modal-dialog').removeAttr('style').addClass('modal-dialog-centered');
  });

  // Events search — the search icon in the Events page topbar opens a
  // bar that live-filters the already-rendered cards (name, location,
  // description) as you type, entirely client-side since the current
  // category tab's events are all already in the DOM. No page reload,
  // and it narrows whatever category is currently selected rather than
  // replacing it.
  $(document).on('click', '.js-toggle-events-search', function () {
    var $bar = $('#eventsSearchBar');
    $bar.toggleClass('is-open');
    if ($bar.hasClass('is-open')) {
      $('#eventsSearchInput').trigger('focus');
    } else {
      $('#eventsSearchInput').val('');
      filterEventCards('');
    }
  });

  $(document).on('click', '#eventsSearchClose', function () {
    $('#eventsSearchBar').removeClass('is-open');
    $('#eventsSearchInput').val('');
    filterEventCards('');
  });

  $(document).on('input', '#eventsSearchInput', function () {
    filterEventCards($(this).val());
  });

  function filterEventCards(query) {
    query = (query || '').trim().toLowerCase();
    var visibleCount = 0;
    $('.js-event-card').each(function () {
      var $card = $(this);
      var haystack = [
        $card.data('event-title'), $card.data('event-location'), $card.data('event-description'),
      ].join(' ').toLowerCase();
      var matches = !query || haystack.indexOf(query) !== -1;
      $card.toggle(matches);
      if (matches) visibleCount++;
    });
    // Only show the "no matches" empty state while actively searching —
    // the server already renders its own empty state (no events in this
    // category at all) for a blank query.
    $('#eventsSearchNoResults').toggle(!!query && visibleCount === 0);
  }

  // Same live-search pattern, for the Marketplace "Browse" tab's
  // listing cards — a separate class/id set from the Events page's
  // (.js-listing-card vs .js-event-card) so the two pages' handlers
  // never collide with each other's elements.
  $(document).on('click', '.js-toggle-marketplace-search', function () {
    var $bar = $('#marketplaceSearchBar');
    $bar.toggleClass('is-open');
    if ($bar.hasClass('is-open')) {
      $('#marketplaceSearchInput').trigger('focus');
    } else {
      $('#marketplaceSearchInput').val('');
      filterListingCards('');
    }
  });

  $(document).on('click', '#marketplaceSearchClose', function () {
    $('#marketplaceSearchBar').removeClass('is-open');
    $('#marketplaceSearchInput').val('');
    filterListingCards('');
  });

  $(document).on('input', '#marketplaceSearchInput', function () {
    filterListingCards($(this).val());
  });

  function filterListingCards(query) {
    query = (query || '').trim().toLowerCase();
    var visibleCount = 0;
    $('.js-listing-card').each(function () {
      var $card = $(this);
      var haystack = [
        $card.data('event-title'), $card.data('event-location'), $card.data('event-description'),
      ].join(' ').toLowerCase();
      var matches = !query || haystack.indexOf(query) !== -1;
      $card.toggle(matches);
      if (matches) visibleCount++;
    });
    $('#marketplaceSearchNoResults').toggle(!!query && visibleCount === 0);
    // While searching, the results are what matter — tuck the
    // "Recommended for you" row away until the search is cleared.
    $('#marketplaceRecs').toggle(!query);
  }

  // Edit-event modal (Events tab card's 3-dot menu) — pre-fills the
  // shared form from the clicked menu item's data-event-* attributes
  // (already in the page from the card render, no extra fetch needed)
  // and points the form at that event's edit URL.
  $(document).on('click', '.js-open-edit-event-modal', function () {
    var $btn = $(this);
    var eventId = $btn.data('event-id');
    var $form = $('#eventEditForm');
    var urlTemplate = $form.data('url-template');
    $form.attr('action', urlTemplate.replace('0', eventId));

    $('#eventEditTitle').val($btn.data('event-title'));
    $('#eventEditCategory').val($btn.data('event-category'));
    $('#eventEditDate').val($btn.data('event-date'));
    $('#eventEditTime').val($btn.data('event-time'));
    $('#eventEditLocation').val($btn.data('event-location'));
    $('#eventEditCapacity').val($btn.data('event-capacity'));
    $('#eventEditPrice').val($btn.data('event-price'));
    $('#eventEditDescription').val($btn.data('event-description'));
    // Image isn't pre-filled — file inputs can't be set from script, so
    // the field starts empty and the view keeps the current image
    // unless a new one is chosen.
    $('#eventEditImage').val('');

    var modalEl = document.getElementById('eventEditModal');
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  });

  // Edit-listing modal (Marketplace "Mine" tab card's 3-dot menu) —
  // same shared-modal-with-URL-template pattern as the event edit
  // modal above.
  $(document).on('click', '.js-open-edit-listing-modal', function () {
    var $btn = $(this);
    var listingId = $btn.data('listing-id');
    var $form = $('#listingEditForm');
    var urlTemplate = $form.data('url-template');
    $form.attr('action', urlTemplate.replace('0', listingId));

    $('#listingEditTitle').val($btn.data('listing-title'));
    $('#listingEditCategory').val($btn.data('listing-category'));
    $('#listingEditCondition').val($btn.data('listing-condition'));
    $('#listingEditPrice').val($btn.data('listing-price'));
    $('#listingEditQuantity').val($btn.data('listing-quantity'));
    $('#listingEditLocation').val($btn.data('listing-location'));
    $('#listingEditDescription').val($btn.data('listing-description'));
    $('#listingEditImages').val('');

    var modalEl = document.getElementById('listingEditModal');
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  });

  // Event details modal — clicking anywhere on an event card (except
  // its own controls: the 3-dot menu, the register/attend button)
  // opens a bigger view of everything about it, including the cover
  // photo, read straight from the card's own data-event-* attributes
  // (a "See more" link on a truncated description is just another
  // descendant of the card, so clicking it bubbles up and opens the
  // same modal — no separate handler needed).
  $(document).on('click', '.js-event-card', function (e) {
    if ($(e.target).closest('.events-card-menu, .btn-events-attend, .events-card-attend-form, .ev-details').length) {
      return;
    }
    var $card = $(this);
    // Cards now open the event's own page (feed/details.py event_detail);
    // the pop-up below is only the fallback for cards without a link.
    var pageUrl = $card.data('event-url');
    if (pageUrl) {
      if (window.UC && UC.navigate) { UC.navigate(pageUrl); } else { window.location.href = pageUrl; }
      return;
    }

    var $banner = $('#eventDetailsBanner');
    var imageUrl = $card.data('event-image');
    // Drop whichever events-card-banner-<color> class the last card
    // shown in this modal left behind, before deciding this card's own
    // look (photo vs gradient+icon).
    $banner.removeClass(function (i, cls) {
      return (cls.match(/(^|\s)events-card-banner-\S+/g) || []).join(' ');
    });
    if (imageUrl) {
      $banner.css({
        'background-image': "url('" + imageUrl + "')",
        'background-size': 'cover', 'background-position': 'center', 'background-repeat': 'no-repeat',
      });
      $('#eventDetailsBannerIcon').hide();
    } else {
      $banner.removeAttr('style').addClass('events-card-banner-' + $card.data('event-category-color'));
      $('#eventDetailsBannerIcon').show().attr('class', 'bi ' + $card.data('event-icon'));
    }

    $('#eventDetailsTitle').text($card.data('event-title'));
    $('#eventDetailsCategoryPill')
      .attr('class', 'event-badge-' + $card.data('event-category-color') + ' events-card-category-pill')
      .text($card.data('event-category-label'));
    $('#eventDetailsLocation').text($card.data('event-location'));
    $('#eventDetailsDateTime').html($card.data('event-datetime'));
    var organizer = $card.data('event-organizer');
    $('#eventDetailsOrganizer').text(organizer || '');
    $('#eventDetailsOrganizerRow').toggle(!!organizer);
    $('#eventDetailsDescription').text($card.data('event-description') || '');
    $('#eventDetailsPrice').html($card.data('event-price'));
    $('#eventDetailsAttending').text($card.data('event-attending'));

    var modalEl = document.getElementById('eventDetailsModal');
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  });

  $(document).on('click', '#confirmDeleteModalBtn', function () {
    if ($pendingDeleteForm) {
      $pendingDeleteForm[0].submit();
      $pendingDeleteForm = null;
      return;
    }
    if ($pendingDeleteCommentBtn) {
      var $btn = $pendingDeleteCommentBtn;
      $pendingDeleteCommentBtn = null;
      var commentId = $btn.data('comment-id');
      var postId = $('#commentsModal').data('post-id');
      $.ajax({
        url: '/comment/' + commentId + '/delete/',
        type: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
        success: function (data) {
          var $item = $('#comment-' + commentId);
          var $parentReplies = $item.closest('.comment-replies');
          $item.remove();
          if ($parentReplies.length) {
            var remaining = $parentReplies.children('.comment-item').length;
            var $toggle = $parentReplies.prev('.js-toggle-replies');
            if (remaining === 0) {
              // No replies left at all — drop the toggle and the
              // (now-empty) container together.
              $toggle.remove();
              $parentReplies.remove();
            } else if (!$parentReplies.is(':visible')) {
              $toggle.find('.js-reply-toggle-text').text('View ' + remaining + ' repl' + (remaining === 1 ? 'y' : 'ies'));
            }
          }
          updateCommentCountUI(postId, data.comments_count);
          showToast('Comment deleted successfully.');
        }
      });
      return;
    }
    if ($pendingDeleteReplyCommentId) {
      var replyCommentId = $pendingDeleteReplyCommentId;
      $pendingDeleteReplyCommentId = null;
      $.ajax({
        url: '/comment/' + replyCommentId + '/delete/',
        type: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
        success: function () {
          $('.profile-reply-card[data-comment-id="' + replyCommentId + '"]').remove();
          showToast('Reply deleted successfully.');
          // No reply cards left anywhere on the page (desktop or
          // mobile layout) — reload so the tab's own empty state
          // (rendered server-side) shows instead of a blank list.
          if ($('.profile-reply-card').length === 0) {
            UC.reload();
          }
        }
      });
    }
  });

  // -----------------------------------------------------------
  // Photo lightbox — click a post's photo to view it large, with
  // that same post's like/comment/repost/share/bookmark row still
  // reachable underneath (the actions bar is cloned from the post
  // card that was clicked, so its Share button still has the right
  // link). A multi-photo post gets left/right navigation between its
  // own photos. Videos are left alone — they already play inline with
  // their own controls, which a click-to-open-modal would fight with.
  // -----------------------------------------------------------
  function renderLightbox() {
    var $modal = $('#mediaLightboxModal');
    var items = $modal.data('lightbox-items') || [];
    var index = $modal.data('lightbox-index') || 0;
    if (!items.length) {
      return;
    }
    $modal.find('.lightbox-media').empty().append($('<img alt="">').attr('src', items[index]));
    $modal.find('.lightbox-nav').toggle(items.length > 1);
    $modal.find('.lightbox-counter').text(items.length > 1 ? (index + 1) + ' / ' + items.length : '');
  }

  // Sizes and positions the photo-lightbox dialog to sit over the post
  // that was clicked — never larger than that post's own rendered box
  // — and centers it on that box, clamped so it never runs off the
  // viewport. Same idea as the comments panel's own post-anchoring.
  // Only used for a post's own photo (there's no "post" to anchor to
  // for a profile/cover photo, which keep their own fixed framing).
  function applyLightboxAnchor($modal, anchorRect) {
    var $dialog = $modal.find('.lightbox-dialog');
    if (!anchorRect || !anchorRect.width || !anchorRect.height) {
      $dialog.removeClass('lightbox-anchored');
      $dialog.css({ width: '', height: '', left: '', top: '' });
      return;
    }
    $dialog.addClass('lightbox-anchored');
    var vw = window.innerWidth, vh = window.innerHeight;
    var margin = 24;
    var maxW = Math.min(vw - margin * 2, 900);
    var maxH = Math.min(vh - margin * 2, 900);
    var w = Math.min(anchorRect.width, maxW);
    var h = Math.min(anchorRect.height, maxH);
    var cx = anchorRect.left + anchorRect.width / 2;
    var cy = anchorRect.top + anchorRect.height / 2;
    var left = Math.max(margin, Math.min(vw - margin - w, cx - w / 2));
    var top = Math.max(margin, Math.min(vh - margin - h, cy - h / 2));
    $dialog.css({ width: w + 'px', height: h + 'px', left: left + 'px', top: top + 'px' });
  }

  $(window).on('resize', function () {
    var $modal = $('#mediaLightboxModal');
    if ($modal.hasClass('show') && $modal.find('.lightbox-dialog').hasClass('lightbox-anchored')) {
      applyLightboxAnchor($modal, $modal.data('lightbox-anchor-rect'));
    }
  });

  // Post photos (.js-lightbox-img) now open the full-screen media
  // viewer in static/js/media-viewer.js. This lightbox is still used for
  // profile and cover photos below.

  $(document).on('click', '.lightbox-prev', function () {
    var $modal = $('#mediaLightboxModal');
    var items = $modal.data('lightbox-items') || [];
    if (!items.length) {
      return;
    }
    var index = (($modal.data('lightbox-index') || 0) - 1 + items.length) % items.length;
    $modal.data('lightbox-index', index);
    renderLightbox();
  });

  $(document).on('click', '.lightbox-next', function () {
    var $modal = $('#mediaLightboxModal');
    var items = $modal.data('lightbox-items') || [];
    if (!items.length) {
      return;
    }
    var index = (($modal.data('lightbox-index') || 0) + 1) % items.length;
    $modal.data('lightbox-index', index);
    renderLightbox();
  });

  $(document).on('keydown', function (e) {
    var modalEl = document.getElementById('mediaLightboxModal');
    if (!modalEl || !modalEl.classList.contains('show')) {
      return;
    }
    if (e.key === 'ArrowLeft') {
      $('.lightbox-prev').trigger('click');
    } else if (e.key === 'ArrowRight') {
      $('.lightbox-next').trigger('click');
    }
  });

  // Profile/cover photo — same lightbox as a post's photos, but a
  // single image with no prev/next and no like/comment/etc. actions
  // row underneath it (there's no post to act on here). Only wired up
  // when a .has-photo element actually has one (the "add a photo"
  // fallback — a plain person icon or empty cover gradient — isn't
  // clickable since there's nothing to view).
  $(document).on('click', '.js-view-profile-photo, .js-view-cover-photo', function (e) {
    // The mobile cover photo also hosts the back-button overlay;
    // don't open the lightbox when that's what was actually clicked.
    if ($(e.target).closest('.profile-back-btn-overlay').length) {
      return;
    }
    var url = $(this).data('photo-url');
    if (!url) {
      return;
    }
    var $modal = $('#mediaLightboxModal');
    var isAvatar = $(this).hasClass('js-view-profile-photo');
    // The profile photo itself is round on the page, so its "magnified"
    // view stays round too — a circular, cropped-to-fill frame. The
    // cover photo isn't round, but it is already shown edge-to-edge,
    // cropped to fill (background-size:cover) on the page itself, so
    // its own magnified view fills the whole modal the same way
    // (object-fit:cover) instead of letterboxing down to fit like a
    // regular post photo does.
    $modal.toggleClass('lightbox-avatar-mode', isAvatar);
    $modal.toggleClass('lightbox-cover-mode', !isAvatar);
    // No post to anchor to here — clear any leftover anchored sizing
    // from a previous post-photo open so these keep their own fixed
    // framing (circular avatar / edge-to-edge cover).
    $modal.data('lightbox-anchor-rect', null);
    applyLightboxAnchor($modal, null);
    $modal.data('lightbox-items', [url]);
    $modal.data('lightbox-index', 0);
    $modal.find('.lightbox-actions').empty();
    renderLightbox();
    if (window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance($modal[0]).show();
    }
  });

  // -----------------------------------------------------------
  // Home feed "What's happening?" prompt card — one card serves
  // both screen sizes: on a wide screen it opens the desktop
  // compose modal, on a narrow screen it navigates to the
  // dedicated full-page composer instead.
  // -----------------------------------------------------------
  $(document).on('click', '#composePromptCard', function () {
    var composeUrl = $(this).data('compose-url');
    if ($(window).width() <= 768) {
      UC.navigate(composeUrl);
    } else {
      var modalEl = document.getElementById('composePostModal');
      if (modalEl && window.bootstrap) {
        var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        modal.show();
      }
    }
  });

  // -----------------------------------------------------------
  // Bottom sheets: the comments sheet and the share sheet. Only one is
  // ever open at a time. uiSheets is the single record of which one is
  // open, kept up to date by each modal's own shown/hidden events, so
  // every opener can check it instead of guessing from the DOM.
  // -----------------------------------------------------------
  var uiSheets = { commentsOpen: false, shareOpen: false };
  window.uniconnectSheets = uiSheets; // readable from the browser console when debugging

  function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  // Runs `next` once `modalEl` has finished closing, or straight away
  // if it isn't open. Used to swap one sheet for another cleanly.
  function afterModalHidden(modalEl, next) {
    if (!modalEl || !modalEl.classList.contains('show') || !window.bootstrap) {
      next();
      return;
    }
    $(modalEl).one('hidden.bs.modal', function () { setTimeout(next, 0); });
    bootstrap.Modal.getOrCreateInstance(modalEl).hide();
  }

  // Copies text, falling back to a hidden textarea where the async
  // clipboard API isn't available. The textarea goes inside the open
  // sheet so Bootstrap's focus trap doesn't pull focus away from it.
  function copyText(text, container) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;';
      (container || document.body).appendChild(ta);
      ta.select();
      try {
        if (document.execCommand('copy')) { resolve(); } else { reject(new Error('copy failed')); }
      } catch (err) {
        reject(err);
      } finally {
        ta.remove();
      }
    });
  }

  // -----------------------------------------------------------
  // Share sheet (#shareSheet in base.html) — opened by a post's Share
  // icon. Slides up from the bottom over a dimmed feed; closes with
  // the X, a tap on the dimmed area, Esc, or a downward drag.
  //
  // Bootstrap still does the modal work (focus, Esc, locking page
  // scroll); the motion is our own: the modal has no "fade" class and
  // no Bootstrap backdrop, the .is-open class drives the CSS
  // transitions, and hide is intercepted once so the sheet can slide
  // down before Bootstrap actually removes it.
  // -----------------------------------------------------------
  var SHARE_SHEET_MS = 320;
  var shareSheet = { url: '', text: '', closing: false, allowHide: false, drag: null };

  function shareSheetEl() {
    return document.getElementById('shareSheet');
  }

  function shareLinks(url, text) {
    var u = encodeURIComponent(url);
    var t = encodeURIComponent(text);
    return {
      whatsapp: 'https://wa.me/?text=' + encodeURIComponent(text + ' ' + url),
      telegram: 'https://t.me/share/url?url=' + u + '&text=' + t,
      facebook: 'https://www.facebook.com/sharer/sharer.php?u=' + u,
      x: 'https://twitter.com/intent/tweet?url=' + u + '&text=' + t,
      email: 'mailto:?subject=' + t + '&body=' + encodeURIComponent(text + '\n\n' + url)
    };
  }

  function resetShareSearch() {
    var $sheet = $(shareSheetEl());
    $sheet.find('.share-sheet-search').prop('hidden', true);
    $sheet.find('.js-share-search-toggle').attr('aria-expanded', 'false');
    $sheet.find('.js-share-search-input').val('');
    $sheet.find('.js-share-person').prop('hidden', false);
    $sheet.find('.js-share-invite').prop('hidden', false);
    $sheet.find('.js-share-people-empty').prop('hidden', true);
  }

  function openShareSheet(trigger) {
    var modalEl = shareSheetEl();
    if (!modalEl || !window.bootstrap) { return; }
    var card = trigger.closest('.post-card, .reel');   // .reel: the phone video feed
    var author = card ? $.trim($(card).find('.post-card-name, .reel-name').first().text()) : '';
    shareSheet.url = $(trigger).data('share-url');
    shareSheet.text = author ? 'Check out this post by ' + author + ' on UniConnect' : 'Check out this post on UniConnect';

    var $sheet = $(modalEl);
    var links = shareLinks(shareSheet.url, shareSheet.text);
    $sheet.find('.js-share-out').each(function () {
      this.href = links[this.getAttribute('data-network')];
    });
    $sheet.find('.js-share-native').prop('hidden', !navigator.share);
    $sheet.find('.js-share-stitch').prop('hidden', !(card && card.querySelector('video')));
    $sheet.find('.js-share-copy-label').text('Copy link');
    $sheet.find('.share-sheet-scroll').scrollTop(0);
    resetShareSearch();

    // One sheet at a time: close comments (or a photo lightbox) first.
    afterModalHidden(document.getElementById('commentsModal'), function () {
      afterModalHidden(document.getElementById('mediaLightboxModal'), function () {
        shareSheet.closing = false;
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
      });
    });
  }

  function closeShareSheet() {
    var modalEl = shareSheetEl();
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).hide();
    }
  }

  $(document).on('click', '.js-share-post', function () {
    openShareSheet(this);
  });

  $('#shareSheet').on('shown.bs.modal', function () {
    uiSheets.shareOpen = true;
    var el = this;
    // Two frames so the off-screen start position is painted before
    // the class that slides it up is added (otherwise no transition).
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { el.classList.add('is-open'); });
    });
  });

  $('#shareSheet').on('hide.bs.modal', function (e) {
    if (shareSheet.allowHide) { // second pass: the slide-down has finished
      shareSheet.allowHide = false;
      return;
    }
    e.preventDefault();
    if (shareSheet.closing) { return; }
    shareSheet.closing = true;
    var el = this;
    var dialog = el.querySelector('.share-sheet-dialog');
    dialog.style.transition = '';
    dialog.style.transform = '';      // from wherever a drag left it...
    el.classList.remove('is-open');   // ...to fully off-screen
    setTimeout(function () {
      shareSheet.allowHide = true;
      bootstrap.Modal.getOrCreateInstance(el).hide();
    }, prefersReducedMotion() ? 0 : SHARE_SHEET_MS);
  });

  $('#shareSheet').on('hidden.bs.modal', function () {
    uiSheets.shareOpen = false;
    shareSheet.closing = false;
    this.querySelector('.share-sheet-dialog').style.transform = '';
  });

  // A tap on the dimmed area above the sheet (the modal element itself,
  // not anything inside the sheet) closes it.
  $('#shareSheet').on('click', function (e) {
    if (e.target === this) { closeShareSheet(); }
  });

  // Drag the handle or header down to dismiss. Released past a quarter
  // of the sheet's height, or flicked down quickly, it closes;
  // otherwise it springs back.
  $(document).on('pointerdown', '#shareSheet .js-share-sheet-handle, #shareSheet .share-sheet-header', function (e) {
    if ($(e.target).closest('button, input').length) { return; }
    var dialog = shareSheetEl().querySelector('.share-sheet-dialog');
    shareSheet.drag = {
      id: e.originalEvent.pointerId,
      startY: e.originalEvent.clientY,
      lastY: e.originalEvent.clientY,
      lastT: performance.now(),
      velocity: 0,
      height: dialog.getBoundingClientRect().height,
      dialog: dialog
    };
    dialog.style.transition = 'none';
  });
  document.addEventListener('pointermove', function (e) {
    var d = shareSheet.drag;
    if (!d || e.pointerId !== d.id) { return; }
    var now = performance.now();
    d.velocity = (e.clientY - d.lastY) / Math.max(1, now - d.lastT);
    d.lastY = e.clientY;
    d.lastT = now;
    var dy = Math.max(0, e.clientY - d.startY);
    d.dialog.style.transform = 'translateY(' + dy + 'px)';
  }, { passive: true });
  function endShareDrag(e) {
    var d = shareSheet.drag;
    if (!d || e.pointerId !== d.id) { return; }
    shareSheet.drag = null;
    var dy = Math.max(0, e.clientY - d.startY);
    d.dialog.style.transition = '';
    if (dy > d.height * 0.25 || d.velocity > 0.6) {
      closeShareSheet();
    } else {
      d.dialog.style.transform = '';
    }
  }
  document.addEventListener('pointerup', endShareDrag);
  document.addEventListener('pointercancel', endShareDrag);

  // Search: filters the "people you follow" row by name or username.
  $(document).on('click', '.js-share-search-toggle', function () {
    var $sheet = $(shareSheetEl());
    var $search = $sheet.find('.share-sheet-search');
    var opening = $search.prop('hidden');
    if (!opening) { resetShareSearch(); return; }
    $search.prop('hidden', false);
    $(this).attr('aria-expanded', 'true');
    $sheet.find('.js-share-search-input').trigger('focus');
  });
  $(document).on('input', '.js-share-search-input', function () {
    var q = $.trim($(this).val()).toLowerCase();
    var $sheet = $(shareSheetEl());
    var shown = 0;
    $sheet.find('.js-share-person').each(function () {
      var hay = (String($(this).data('name')) + ' ' + String($(this).data('username'))).toLowerCase();
      var match = !q || hay.indexOf(q) !== -1;
      $(this).prop('hidden', !match);
      if (match) { shown++; }
    });
    $sheet.find('.js-share-invite').prop('hidden', !!q);
    $sheet.find('.js-share-people-empty').prop('hidden', !q || shown > 0);
  });

  // Direct messages don't exist yet, so "send to a person" copies the
  // link for them and says so plainly, rather than pretending to send.
  $(document).on('click', '.js-share-person', function () {
    var name = $(this).data('name');
    copyText(shareSheet.url, shareSheetEl()).then(function () {
      showToast('Messages are coming soon. Link copied, so you can send it to ' + name + ' yourself.');
      closeShareSheet();
    }, function () {
      showToast('Could not copy the link.', 'error');
    });
  });

  $(document).on('click', '.js-share-invite', function () {
    var inviteUrl = $(shareSheetEl()).data('invite-url');
    var invite = { title: 'Join me on UniConnect', text: 'Join me on UniConnect, the social network for our university.', url: inviteUrl };
    if (navigator.share) {
      navigator.share(invite).then(closeShareSheet, function () {});
      return;
    }
    copyText(inviteUrl, shareSheetEl()).then(function () {
      showToast('Invite link copied.');
      closeShareSheet();
    }, function () {
      showToast('Could not copy the invite link.', 'error');
    });
  });

  $(document).on('click', '.js-share-copy', function () {
    var $label = $(this).find('.js-share-copy-label');
    copyText(shareSheet.url, shareSheetEl()).then(function () {
      $label.text('Copied');
      showToast('Link copied successfully.');
      setTimeout(closeShareSheet, 500);
    }, function () {
      showToast('Could not copy the link.', 'error');
    });
  });

  // WhatsApp, Telegram, Facebook, X and Email are plain links (opened
  // in a new tab, or the mail app); the sheet just gets out of the way.
  $(document).on('click', '.js-share-out', function () {
    setTimeout(closeShareSheet, 150);
  });

  // The phone's own share menu, where the browser supports it (the
  // button stays hidden otherwise).
  $(document).on('click', '.js-share-native', function () {
    if (!navigator.share) { return; }
    navigator.share({ title: 'UniConnect', text: shareSheet.text, url: shareSheet.url })
      .then(closeShareSheet, function () {});
  });

  // -----------------------------------------------------------
  // Post composer / editor — up to 4 photos, or a single video,
  // attached to one post. A plain <input type=file multiple> only
  // ever grows or replaces its whole FileList, so a per-form list of
  // picked files is kept here (in jQuery's .data()) and written back
  // into the input via a DataTransfer every time it changes — that's
  // what lets one thumbnail be removed without clearing everything
  // and reselecting. Delegated handlers so the same code works for
  // the desktop modal, the full-page composer, and the edit page.
  // -----------------------------------------------------------
  function mediaIsVideo(file) {
    return (file.type || '').indexOf('video/') === 0;
  }

  function renderMediaPreview($grid, files, onRemove) {
    $grid.empty().removeClass('count-1 count-2 count-3 count-4');
    if (files.length) {
      $grid.addClass('count-' + files.length);
    }
    files.forEach(function (file, index) {
      var url = URL.createObjectURL(file);
      var $media = mediaIsVideo(file)
        ? $('<video controls></video>').attr('src', url)
        : $('<img alt="">').attr('src', url);
      var $remove = $('<button type="button" class="compose-remove-image" aria-label="Remove media"><i class="bi bi-x-lg"></i></button>');
      $remove.on('click', function () { onRemove(index); });
      var $item = $('<div class="compose-media-preview-item"></div>').append($media).append($remove);
      $grid.append($item);
      // A small photo will look blurry in a post (and is shown smaller, at
      // its true size) — say so now, while a bigger copy can still be picked.
      // Same limit as PostMedia.SMALL on the server.
      if (!mediaIsVideo(file)) {
        $media.on('load', function () {
          var w = this.naturalWidth, h = this.naturalHeight;
          if (w && h && (w < 560 || h < 280)) {
            $item.addClass('is-small-photo').append(
              $('<div class="compose-small-photo-note" role="note"></div>')
                .append('<i class="bi bi-exclamation-triangle-fill" aria-hidden="true"></i> ')
                .append(document.createTextNode('Small photo (' + w + '×' + h + ') — it may look blurry. Try a larger version.'))
            );
          }
        });
      }
    });
  }

  function syncInputFiles(input, files) {
    var dt = new DataTransfer();
    files.forEach(function (file) { dt.items.add(file); });
    input.files = dt.files;
  }

  function newMediaGrid($form) {
    var $grid = $form.find('.js-new-media-grid');
    return $grid.length ? $grid : $form.find('.compose-media-preview-grid').not('.js-existing-media-grid').first();
  }

  function refreshNewMediaPreview($form, input) {
    var pending = $form.data('pendingMediaFiles') || [];
    renderMediaPreview(newMediaGrid($form), pending, function (index) {
      pending.splice(index, 1);
      $form.data('pendingMediaFiles', pending);
      syncInputFiles(input, pending);
      refreshNewMediaPreview($form, input);
      updatePostButtonState($form);
    });
  }

  function updatePostButtonState($form) {
    var hasText = $.trim($form.find('.compose-textarea').val()).length > 0;
    var $existingGrid = $form.find('.js-existing-media-grid');
    var hasExistingMedia = $existingGrid.children('.compose-media-preview-item').length > 0;
    var pendingCount = ($form.data('pendingMediaFiles') || []).length;
    $form.find('.compose-post-btn').prop('disabled', !(hasText || hasExistingMedia || pendingCount > 0));
  }

  $(document).on('input', '.compose-textarea', function () {
    updatePostButtonState($(this).closest('form'));
  });

  $(document).on('change', '.compose-media-input', function () {
    var input = this;
    var $form = $(input).closest('form');
    var newFiles = input.files ? Array.prototype.slice.call(input.files) : [];
    if (!newFiles.length) {
      return;
    }
    var pending = ($form.data('pendingMediaFiles') || []).concat(newFiles);
    $form.data('pendingMediaFiles', pending);
    syncInputFiles(input, pending);
    refreshNewMediaPreview($form, input);
    updatePostButtonState($form);
  });

  // Removing an already-saved attachment (edit page only) — records
  // its id in the hidden remove_media_ids input so edit_post() deletes
  // it server-side, and takes the thumbnail out of the grid right away.
  $(document).on('click', '.js-remove-existing-media', function () {
    var $item = $(this).closest('.compose-media-preview-item');
    var $form = $(this).closest('form');
    var $hidden = $form.find('.js-remove-media-ids');
    var ids = ($hidden.val() || '').split(',').filter(function (v) { return v; });
    ids.push(String($item.data('existing-id')));
    $hidden.val(ids.join(','));
    $item.remove();

    var $grid = $form.find('.js-existing-media-grid');
    $grid.removeClass('count-1 count-2 count-3 count-4');
    var remaining = $grid.children('.compose-media-preview-item').length;
    if (remaining) {
      $grid.addClass('count-' + remaining);
    }
    updatePostButtonState($form);
  });

  // If the composer re-renders with an error (server-side validation
  // failed) but the textarea already has content from a previous
  // attempt — or, on the edit page, already has existing media — make
  // sure the Post/Save button reflects that on load.
  UC.onPage(function () {
    $('.compose-textarea').each(function () {
      updatePostButtonState($(this).closest('form'));
    });
  });

  function getCookie(name) {
    var cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      var cookies = document.cookie.split(';');
      for (var i = 0; i < cookies.length; i++) {
        var cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  // -----------------------------------------------------------
  // Small-screen navigation drawer (hamburger menu) — mirrors the
  // desktop left sidebar's links, settings, theme toggle, profile
  // row and logout. Opens as an overlay with a dimmed backdrop;
  // closes via its own X button, clicking the backdrop, or Escape.
  // Shown on every page built from base_app.html except Profile,
  // which already has its own dedicated mobile header/nav.
  // -----------------------------------------------------------
  function closeAppDrawer() {
    $('#appDrawer').removeClass('open');
    $('#appDrawerBackdrop').removeClass('open');
  }

  $(document).on('click', '#appDrawerOpenBtn', function () {
    $('#appDrawer').addClass('open');
    $('#appDrawerBackdrop').addClass('open');
  });

  $(document).on('click', '#appDrawerCloseBtn, #appDrawerBackdrop', function () {
    closeAppDrawer();
  });

  $(document).on('keydown', function (e) {
    if (e.key === 'Escape') {
      closeAppDrawer();
    }
  });

  // -----------------------------------------------------------
  // Small-screen bottom bar "more" overflow menu — the quicklinks
  // that don't fit as their own icon collapse behind a "➕" button.
  // -----------------------------------------------------------
  $(document).on('click', '#bottomNavMoreBtn', function (e) {
    e.stopPropagation();
    $('#bottomNavMoreMenu').toggleClass('open');
  });

  $(document).on('click', function (e) {
    if (!$(e.target).closest('.app-mobile-bottomnav-more').length) {
      $('#bottomNavMoreMenu').removeClass('open');
    }
  });

  // -----------------------------------------------------------
  // Comments modal — opened from a post's comment icon. On a wide
  // screen the post content and the comment thread sit side by side
  // (see app.css) so you can read the thread while still seeing
  // what's being discussed; on a narrow screen they stack, same modal
  // either way. The thread is loaded lazily over AJAX each time the
  // modal opens, rather than baked into every post card on the feed.
  // -----------------------------------------------------------
  var $pendingDeleteCommentBtn = null;

  // -----------------------------------------------------------
  // Comments sheet — on mobile/tablet the comments modal IS a
  // TikTok-style draggable bottom sheet instead of a plain popup (see
  // .comments-modal-dialog etc. in app.css, under the matching
  // max-width:900px query). This block owns everything about that:
  // dragging the handle or the comment list to resize the sheet
  // between its snap points, telling a "scroll the list" gesture
  // apart from a "resize the sheet" gesture (nested scrolling), and
  // swiping down far enough to dismiss the whole sheet.
  //
  // The sheet's height lives in one place — the --sheet-height custom
  // property on .comments-modal-body — which a drag sets directly
  // (as a px value, for 1:1 finger tracking) and a snap sets as a
  // percentage (so its CSS transition animates to it smoothly). It's
  // always read back from the DOM (getBoundingClientRect), never
  // tracked separately in JS state, so there's only ever one source
  // of truth for "how tall is the sheet right now".
  //
  // touch-action:none on the handle AND the comment list (see app.css)
  // hands ALL pointer handling here instead of leaving any of it to
  // the browser's native scrolling — the one thing that reliably
  // avoids the sheet-drag and the browser's own scroll fighting each
  // other over the same gesture, on both Android and iOS. Pointer
  // Events (not touch/mouse events separately) cover mouse, touch and
  // pen the same way, so the sheet works identically with a mouse on
  // a desktop screen and a finger on a phone — one design, one input
  // model, no extra library, and no separate mobile-vs-desktop code
  // path to keep in sync.
  var SHEET_SNAP_POINTS = [0.55, 0.78, 0.94];
  var sheetSnapIndex = 0;
  var sheetDrag = null;

  // On a big screen, "cover the whole page" reads as broken rather than
  // TikTok-like — there's no reason a mouse-driven comments panel needs
  // to eat the entire viewport the way a phone sheet does. From this
  // width up, the panel is instead sized to (and centered on) the exact
  // post card that was clicked: see applyDesktopAnchor. Below it, the
  // full-screen draggable sheet from isSheetMode's old behavior still
  // applies unconditionally, unchanged.
  var DESKTOP_ANCHOR_BREAKPOINT = 900;
  function isDesktopMode() {
    return window.matchMedia('(min-width:' + (DESKTOP_ANCHOR_BREAKPOINT + 1) + 'px)').matches;
  }

  // Sizes and positions .comments-modal-dialog to sit over the post
  // that triggered it — never larger than that post's own rendered box
  // — and centers the panel on that box, clamped so it never runs off
  // the viewport. anchorRect is the triggering post card's own
  // getBoundingClientRect(), captured at click time by the handlers
  // below; it's re-applied on window resize while the modal is open so
  // rotating a window or DevTools' responsive mode doesn't leave a
  // stale size/position behind.
  function applyDesktopAnchor($modal) {
    var $dialog = $modal.find('.comments-modal-dialog');
    if (!isDesktopMode()) {
      $dialog.removeClass('comments-anchored');
      $dialog.css({ width: '', height: '', left: '', top: '' });
      return;
    }
    var anchorRect = $modal.data('anchor-rect');
    $dialog.addClass('comments-anchored');

    var vw = window.innerWidth, vh = window.innerHeight;
    var margin = 24;
    var maxW = Math.min(vw - margin * 2, 860);
    var maxH = Math.min(vh - margin * 2, 760);
    // The panel's size is capped strictly to the clicked post's own
    // rendered box, per spec: it must never exceed that post's
    // width/height — even if that makes it compact for a short,
    // text-only post, since the thread list and composer inside it
    // still scroll to fit whatever room that leaves.
    var w, h, cx, cy;
    if (anchorRect && anchorRect.width > 0 && anchorRect.height > 0) {
      w = Math.min(anchorRect.width, maxW);
      h = Math.min(anchorRect.height, maxH);
      cx = anchorRect.left + anchorRect.width / 2;
      cy = anchorRect.top + anchorRect.height / 2;
    } else {
      w = maxW;
      h = maxH;
      cx = vw / 2;
      cy = vh / 2;
    }
    // ...but never smaller than a comfortable reading size: a text-only
    // post's card is only ~200px tall, which left the comments a sliver.
    // The panel still opens over the post, clamped to the screen below.
    w = Math.max(w, Math.min(600, maxW));
    h = Math.max(h, Math.min(640, maxH));

    var left = Math.max(margin, Math.min(vw - margin - w, cx - w / 2));
    var top = Math.max(margin, Math.min(vh - margin - h, cy - h / 2));
    $dialog.css({ width: w + 'px', height: h + 'px', left: left + 'px', top: top + 'px' });
  }

  $(window).on('resize', function () {
    var $modal = $('#commentsModal');
    if ($modal.hasClass('show') || $modal.find('.comments-modal-dialog').hasClass('comments-anchored')) {
      applyDesktopAnchor($modal);
    }
  });

  function sheetEls() {
    var $modal = $('#commentsModal');
    return {
      $body: $modal.find('.comments-modal-body'),
      $pane: $modal.find('.comments-modal-thread-pane')
    };
  }

  // Always measured live off the DOM rather than kept in a variable —
  // the sheet's actual rendered height is the one source of truth,
  // whether it got there via a snap (%) or an in-progress drag (px).
  function currentSheetHeightFraction() {
    var els = sheetEls();
    var bodyH = els.$body[0].getBoundingClientRect().height;
    var paneH = els.$pane[0].getBoundingClientRect().height;
    return bodyH ? (paneH / bodyH) : SHEET_SNAP_POINTS[0];
  }

  function setSheetHeightPx(px) {
    sheetEls().$body[0].style.setProperty('--sheet-height', px + 'px');
  }

  function setSheetHeightPct(pct) {
    sheetEls().$body[0].style.setProperty('--sheet-height', pct + '%');
  }

  function closeCommentsSheet() {
    var modalEl = document.getElementById('commentsModal');
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).hide();
    }
  }

  function snapSheetToNearest(fraction) {
    var nearestIdx = 0, nearestDist = Infinity;
    for (var i = 0; i < SHEET_SNAP_POINTS.length; i++) {
      var dist = Math.abs(SHEET_SNAP_POINTS[i] - fraction);
      if (dist < nearestDist) { nearestDist = dist; nearestIdx = i; }
    }
    sheetSnapIndex = nearestIdx;
    setSheetHeightPct(SHEET_SNAP_POINTS[nearestIdx] * 100);
  }

  // mode: 'handle' (the grab bar — always resizes) or 'list' (the
  // comment list — resizes or scrolls depending on the first few
  // pixels of movement; see onSheetPointerMove).
  function beginSheetDrag(mode, nativeEvent, listEl) {
    var els = sheetEls();
    var containerH = els.$body[0].getBoundingClientRect().height;
    sheetDrag = {
      mode: mode,
      pointerId: nativeEvent.pointerId,
      startY: nativeEvent.clientY,
      lastY: nativeEvent.clientY,
      startHeightPx: els.$pane[0].getBoundingClientRect().height,
      containerH: containerH,
      decided: mode === 'handle',
      resizing: mode === 'handle',
      listEl: listEl || null
    };
    if (mode === 'handle') {
      els.$pane.addClass('is-dragging');
    }
  }

  function onSheetPointerMove(e) {
    if (!sheetDrag || e.pointerId !== sheetDrag.pointerId) return;
    var totalDeltaY = e.clientY - sheetDrag.startY; // + = finger moved down
    var stepDeltaY = e.clientY - sheetDrag.lastY;
    sheetDrag.lastY = e.clientY;

    if (sheetDrag.mode === 'list' && !sheetDrag.decided) {
      // Nested scrolling: wait for a few pixels of real movement, then
      // decide once whether this particular gesture resizes the sheet
      // or scrolls the list, same way TikTok's own sheet reads it —
      // pulling down from the very top of the list collapses the
      // sheet; pulling up anywhere expands it first, before the list
      // itself starts scrolling once the sheet is fully open.
      if (Math.abs(totalDeltaY) < 6) return;
      var atTop = sheetDrag.listEl.scrollTop <= 0;
      var atMaxSnap = currentSheetHeightFraction() >= SHEET_SNAP_POINTS[SHEET_SNAP_POINTS.length - 1] - 0.01;
      sheetDrag.decided = true;
      sheetDrag.resizing = (totalDeltaY > 0 && atTop) || (totalDeltaY < 0 && !atMaxSnap);
      if (sheetDrag.resizing) {
        sheetEls().$pane.addClass('is-dragging');
        // Re-baseline from here so the sheet doesn't jump by the few
        // pixels of dead zone just used to tell the gesture apart.
        sheetDrag.startY = e.clientY;
        sheetDrag.startHeightPx = currentSheetHeightFraction() * sheetDrag.containerH;
        totalDeltaY = 0;
      }
    }

    e.preventDefault();

    if (sheetDrag.resizing) {
      var newHeightPx = sheetDrag.startHeightPx - totalDeltaY;
      var minPx = sheetDrag.containerH * 0.12;
      var maxPx = sheetDrag.containerH * SHEET_SNAP_POINTS[SHEET_SNAP_POINTS.length - 1];
      setSheetHeightPx(Math.max(minPx, Math.min(maxPx, newHeightPx)));
    } else if (sheetDrag.mode === 'list') {
      var list = sheetDrag.listEl;
      var maxScroll = list.scrollHeight - list.clientHeight;
      list.style.scrollBehavior = 'auto';   // follows the finger, not animated
      list.scrollTop = Math.max(0, Math.min(maxScroll, list.scrollTop - stepDeltaY));
      list.style.scrollBehavior = '';
    }
  }

  function onSheetPointerUp(e) {
    if (!sheetDrag || e.pointerId !== sheetDrag.pointerId) return;
    var drag = sheetDrag;
    sheetDrag = null;
    sheetEls().$pane.removeClass('is-dragging');
    if (!drag.resizing) return; // a list-scroll drag needs no snap/dismiss

    var fraction = currentSheetHeightFraction();
    var dismissThreshold = SHEET_SNAP_POINTS[0] * 0.5;
    if (fraction < dismissThreshold) {
      closeCommentsSheet();
      return;
    }
    snapSheetToNearest(fraction);
  }

  // The drag-to-expand/collapse sheet mechanics apply the same way at
  // every screen size — on a big screen they just play out inside the
  // smaller, post-sized box applyDesktopAnchor sizes/positions, rather
  // than across the full viewport.
  $(document).on('pointerdown', '.js-comments-sheet-handle', function (e) {
    beginSheetDrag('handle', e.originalEvent);
  });
  $(document).on('pointerdown', '.comments-modal-thread-list', function (e) {
    beginSheetDrag('list', e.originalEvent, this);
  });
  // Bound on document (not the handle/list themselves) since a drag
  // that starts on one of them can move the pointer anywhere on
  // screen — pointerId is what ties later events back to this drag.
  document.addEventListener('pointermove', onSheetPointerMove, { passive: false });
  document.addEventListener('pointerup', onSheetPointerUp);
  document.addEventListener('pointercancel', onSheetPointerUp);

  function updateCommentCountUI(postId, count) {
    var $btn = $('.js-open-comments[data-post-id="' + postId + '"]');
    $btn.find('.post-card-action-count').remove();
    if (count > 0) {
      $btn.append($('<span class="post-card-action-count"></span>').text(count));
    }

    // If this post's comments are the ones currently open in the
    // modal, keep its "{N} comments" header title (TikTok-style) in
    // sync too.
    var $modal = $('#commentsModal');
    if ($modal.data('post-id') === postId) {
      var label = count > 0 ? (count === 1 ? '1 comment' : count + ' comments') : 'Comments';
      $modal.find('.js-comments-count-title').text(label);
    }
  }

  // When opened with a specific comment in mind (e.g. from the
  // profile page's Replies tab), expands any collapsed "View N
  // replies" the comment is nested under, scrolls it into view, and
  // flashes it so it's easy to spot in a long thread.
  function revealComment($modal, commentId) {
    var $target = $modal.find('#comment-' + commentId);
    if (!$target.length) return;

    $target.parents('.comment-replies').each(function () {
      var $replies = $(this);
      if ($replies.is(':visible')) return;
      $replies.show();
      var $toggle = $replies.prev('.js-toggle-replies');
      $toggle.find('.js-reply-chevron').removeClass('bi-chevron-down').addClass('bi-chevron-up');
      $toggle.find('.js-reply-toggle-text').text('Hide replies');
    });

    setTimeout(function () {
      $target[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
      $target.addClass('comment-highlight');
      setTimeout(function () { $target.removeClass('comment-highlight'); }, 1600);
    }, 50);
  }

  // -----------------------------------------------------------
  // Comments on a post with a video, a photo or a GIF ("media mode").
  //
  // Instead of loading a second copy of the post into the top of the
  // comments view, the post's own media goes there:
  //   - a <video> is moved there itself, so it keeps playing (moving an
  //     element within the page in one step doesn't pause it);
  //   - a photo or GIF is shown there as an identical <img>, while the
  //     original stays in its card, hidden. Chrome restarts a GIF's
  //     animation whenever its element is moved or copied, so up top a
  //     GIF plays from its first frame; leaving the original untouched
  //     means it isn't restarted a second time when the comments close.
  // It then animates, FLIP-style, from where it was in the feed card to
  // the top of the screen while the sheet rises underneath it:
  //
  //   First  — measure it in the feed card.
  //   Last   — move it into the top "stage" and let it lay out there.
  //   Invert — apply a transform + clip so it looks exactly like it did
  //            in the card again (same spot, same crop, same corners).
  //   Play   — remove them with a CSS transition, while the sheet's
  //            own transition grows it from 0 to its first snap point.
  //
  // A post with 2-4 photos gets a swipeable row of them at the top
  // (with dots); the first one does the flight in, and whichever one is
  // showing when the sheet closes flies back to its own spot in the
  // card. Closing always plays the opening backwards, then puts every
  // element back in its card. The feed's scroll position never changes,
  // because the page behind the modal never moves.
  //
  // Every screen size. On a phone or tablet the comments view fills the
  // screen; on a laptop/desktop it's the panel applyDesktopAnchor sizes
  // and places over the clicked post, so the same flight happens inside
  // that panel, with the page around it dimmed. Text-only posts keep
  // the original behavior.
  // -----------------------------------------------------------
  var MEDIA_SHEET_MS = 350;
  // { items: [{ el, original, slot }], multi, track, dots, $header, headerHome, closing, closed }
  //   el: what's shown up top; original: the element in the card (the
  //   same element for a video); slot: placeholder left in the card
  //   while a video is away (null for photos, which never leave)
  var commentsMedia = null;
  var commentsModalMode = null; // 'media' | 'default': which Bootstrap config the instance was built with

  // The post's video, or its photos/GIFs, in display order — or null.
  // (A post is either one video or 1-4 photos, never a mix.)
  function feedMediaFor(trigger) {
    var card = trigger.closest('.post-card');
    if (!card || card.closest('#commentsModal') || card.classList.contains('profile-reply-card')) { return null; }
    // The card's own media only — not the copy of a quoted post inside it.
    var own = function (el) { return !el.closest('.quote-embed'); };
    var video = Array.prototype.slice.call(card.querySelectorAll('.post-card-media-item video, .post-card-photo video')).filter(own)[0];
    if (video) { return [video]; }
    var photos = Array.prototype.slice.call(card.querySelectorAll('.post-card-media-item img, .post-card-photo img')).filter(own);
    return photos.length ? photos : null;
  }

  // The picture's real pixel size (video or image); falls back to the
  // card box's own proportions if it hasn't loaded yet.
  function mediaSize(el, fallbackBox) {
    var w = el.videoWidth || el.naturalWidth;
    var h = el.videoHeight || el.naturalHeight;
    return w && h ? { w: w, h: h } : { w: fallbackBox.width, h: fallbackBox.height };
  }

  // The rectangle the picture itself fills inside `box`, as
  // object-fit: contain lays it out (letterboxed, nothing cropped).
  function containRect(box, w, h) {
    var k = Math.min(box.width / w, box.height / h);
    var pw = w * k, ph = h * k;
    return { left: box.left + (box.width - pw) / 2, top: box.top + (box.height - ph) / 2, width: pw, height: ph };
  }

  // Which corners of a cell are rounded: only the ones it shares with
  // the rounded frame around it (in a 2-4 photo grid, a cell's inner
  // corners are square). Returns [top-left, top-right, bottom-right, bottom-left].
  function cellRadii(cellBox, frame) {
    if (!frame) { return [0, 0, 0, 0]; }
    var r = parseFloat(getComputedStyle(frame).borderTopLeftRadius) || 0;
    var f = frame.getBoundingClientRect();
    var near = function (a, b) { return Math.abs(a - b) < 1.5; };
    var top = near(cellBox.top, f.top), bottom = near(cellBox.bottom, f.bottom);
    var left = near(cellBox.left, f.left), right = near(cellBox.right, f.right);
    return [top && left ? r : 0, top && right ? r : 0, bottom && right ? r : 0, bottom && left ? r : 0];
  }

  // The transform and clip-path that make the media — laid out in
  // `stageBox` with object-fit: contain — look exactly like it did in
  // the feed card at `cardBox` (object-fit: cover, rounded corners).
  // Needs transform-origin: 0 0 on the element (set in app.css).
  function mediaFlip(stageBox, cardBox, size, radii) {
    var pic = containRect(stageBox, size.w, size.h);
    // Uniform scale, big enough for the picture to cover the card (like
    // object-fit: cover did there) — never stretched.
    var s = Math.max(cardBox.width / pic.width, cardBox.height / pic.height);
    var picCx = pic.left - stageBox.left + pic.width / 2;
    var picCy = pic.top - stageBox.top + pic.height / 2;
    var tx = cardBox.left + cardBox.width / 2 - stageBox.left - s * picCx;
    var ty = cardBox.top + cardBox.height / 2 - stageBox.top - s * picCy;
    // The card's rectangle in the element's own (untransformed) pixels:
    // everything outside it is clipped, recreating the card's crop.
    var l = (cardBox.left - stageBox.left - tx) / s;
    var t = (cardBox.top - stageBox.top - ty) / s;
    var r = stageBox.width - (l + cardBox.width / s);
    var b = stageBox.height - (t + cardBox.height / s);
    var round = radii.map(function (x) { return (x / s) + 'px'; }).join(' ');
    return {
      transform: 'translate(' + tx + 'px, ' + ty + 'px) scale(' + s + ')',
      clip: 'inset(' + t + 'px ' + r + 'px ' + b + 'px ' + l + 'px round ' + round + ')'
    };
  }

  // The comments modal needs a different Bootstrap setup in media mode
  // (no fade, no backdrop, so it appears instantly and the motion is
  // all ours) than in the original mode. Bootstrap reads those options
  // once, when the instance is created, so swap the instance when the
  // mode changes. Only ever done while the modal is closed.
  function prepareCommentsModalInstance(modalEl, mode) {
    if (commentsModalMode === mode) { return; }
    var existing = bootstrap.Modal.getInstance(modalEl);
    if (existing) { existing.dispose(); }
    modalEl.classList.toggle('fade', mode !== 'media');
    new bootstrap.Modal(modalEl, mode === 'media' ? { backdrop: false } : {});
    commentsModalMode = mode;
  }

  function updateMediaDots() {
    var cm = commentsMedia;
    if (!cm || !cm.multi) { return; }
    var index = Math.round(cm.track.scrollLeft / Math.max(1, cm.track.clientWidth));
    $(cm.dots).children().each(function (i) { this.classList.toggle('is-active', i === index); });
  }

  // Step 1 (before the modal is shown): measure the first item in its
  // card, put the media in the top stage (moving a video, leaving a
  // slot in its place; copying photos and hiding the originals), and
  // move the "N comments / X" header onto the sheet.
  function moveMediaIntoComments($modal, els) {
    var first = els[0];
    var cardBox = first.getBoundingClientRect();
    var radii = cellRadii(cardBox, first.closest('.post-card-photo, .post-card-media-grid'));
    var multi = els.length > 1;

    var stage = document.createElement('div');
    stage.className = 'comments-media-stage';
    var track = null, dots = null;
    if (multi) {
      track = document.createElement('div');
      track.className = 'comments-media-track';
      dots = document.createElement('div');
      dots.className = 'comments-media-dots';
      dots.setAttribute('aria-hidden', 'true');
      stage.appendChild(track);
      stage.appendChild(dots);
    }
    $modal.find('.js-comments-post-pane').empty().append(stage);

    var items = els.map(function (original, i) {
      var el, slot = null;
      if (original.tagName === 'VIDEO') {
        el = original; // the same element: playback carries on
        slot = document.createElement('div');
        slot.className = 'post-card-media-slot';
        original.parentNode.insertBefore(slot, original);
      } else {
        el = original.cloneNode(false); // the original stays put, hidden
        original.classList.add('is-in-comments');
      }
      if (multi) {
        var slide = document.createElement('div');
        slide.className = 'comments-media-slide';
        slide.appendChild(el);
        track.appendChild(slide);
        var dot = document.createElement('span');
        if (i === 0) { dot.className = 'is-active'; }
        dots.appendChild(dot);
      } else {
        stage.appendChild(el);
      }
      return { el: el, original: original, slot: slot };
    });
    if (track) { track.addEventListener('scroll', updateMediaDots, { passive: true }); }

    var $header = $modal.find('.comments-modal-header');
    var headerHome = { parent: $header.parent()[0], next: $header.next()[0] };
    $header.insertAfter($modal.find('.js-comments-sheet-handle'));

    commentsMedia = {
      items: items, multi: multi, track: track, dots: dots,
      $header: $header, headerHome: headerHome, closing: false, closed: false
    };
    $modal.addClass('comments-media-mode');
    return { cardBox: cardBox, radii: radii };
  }

  // Step 2 (modal now on screen, sheet still collapsed): invert, then play.
  function animateMediaIn($modal, start) {
    var el = commentsMedia.items[0].el;
    var stageBox = el.getBoundingClientRect();
    var flip = mediaFlip(stageBox, start.cardBox, mediaSize(el, start.cardBox), start.radii);
    el.style.transition = 'none';
    el.style.transform = flip.transform;
    el.style.clipPath = flip.clip;
    el.getBoundingClientRect(); // commit this as the starting frame
    // Same two-frame wait as the shown.bs.modal handler that starts the
    // sheet's rise, so the media and the sheet move together.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        el.style.transition = '';
        el.style.transform = '';
        el.style.clipPath = '';
        $modal.addClass('is-media-active');
      });
    });
  }

  // Closing: the sheet sinks while the media flies back to its card
  // (for several photos, whichever one is showing). Runs in place of
  // Bootstrap's hide, then lets the real hide happen.
  function animateMediaOut($modal) {
    var cm = commentsMedia;
    cm.closing = true;
    var index = cm.multi ? Math.round(cm.track.scrollLeft / Math.max(1, cm.track.clientWidth)) : 0;
    var item = cm.items[Math.min(index, cm.items.length - 1)];
    var el = item.el;
    var $body = $modal.find('.comments-modal-body');
    $modal.find('.comments-modal-thread-pane').removeClass('is-dragging');
    // Once the sheet has collapsed, the stage fills the whole body:
    // that's the box the transform is relative to when it ends.
    var stageBox = $body[0].getBoundingClientRect();
    var home = item.slot || item.original; // where it lands in the card
    var cardBox = home.getBoundingClientRect();
    var radii = cellRadii(cardBox, home.closest('.post-card-photo, .post-card-media-grid'));
    var flip = mediaFlip(stageBox, cardBox, mediaSize(el, cardBox), radii);

    $body.addClass('is-closing');
    $modal.removeClass('is-media-active');
    el.style.transform = flip.transform;
    el.style.clipPath = flip.clip;

    setTimeout(function () {
      putMediaBack();
      cm.closed = true;
      bootstrap.Modal.getOrCreateInstance($modal[0]).hide();
    }, prefersReducedMotion() ? 0 : MEDIA_SHEET_MS + 30);
  }

  function putMediaBack() {
    var cm = commentsMedia;
    if (!cm || cm.restored) { return; }
    cm.restored = true;
    if (cm.track) { cm.track.removeEventListener('scroll', updateMediaDots); }
    cm.items.forEach(function (item) {
      if (item.slot) {
        // A video: clear the animation styles and put it back in its
        // card, still playing.
        var el = item.el;
        el.style.transition = 'none';
        el.style.transform = '';
        el.style.clipPath = '';
        if (item.slot.parentNode) { item.slot.parentNode.replaceChild(el, item.slot); }
        el.getBoundingClientRect();
        el.style.transition = '';
      } else {
        // A photo: the original never left — show it again; the copy up
        // top goes when the stage is emptied.
        item.original.classList.remove('is-in-comments');
      }
    });
    if (cm.headerHome.next) {
      cm.$header.insertBefore(cm.headerHome.next);
    } else {
      cm.$header.appendTo(cm.headerHome.parent);
    }
  }

  // opts (optional):
  //   openReplyFor    — comment id whose own inline reply box should
  //                      open (and get focus) once the thread loads,
  //                      so replying to it from the Replies tab is a
  //                      single click.
  //   expandChildrenOf — comment id whose own "View N replies" should
  //                      auto-expand once the thread loads, so its
  //                      nested replies are visible without a second
  //                      click (used by the Replies tab's own "View N
  //                      replies" row, which has no nested replies of
  //                      its own to expand in place).
  function openCommentsModal(postId, highlightCommentId, opts) {
    opts = opts || {};
    var $modal = $('#commentsModal');

    // One sheet at a time: if the share sheet is open, close it first.
    var shareEl = document.getElementById('shareSheet');
    if (shareEl && shareEl.classList.contains('show')) {
      afterModalHidden(shareEl, function () { openCommentsModal(postId, highlightCommentId, opts); });
      return;
    }
    if ($modal.hasClass('show')) { return; }

    $modal.data('post-id', postId);
    $modal.find('.js-comments-post-pane').html('<div class="comments-modal-loading">Loading…</div>');
    $modal.find('.js-comments-thread-list').empty();

    // TikTok-style open (mobile/tablet): start from the "expanded
    // post, no comment sheet yet" frame. shown.bs.modal below removes
    // this once the modal is actually visible, which is what makes
    // the post shrink and the rounded comment sheet slide up as a
    // transition instead of just appearing already-shrunk. Also drop
    // any --sheet-height a previous drag left inline, so this open
    // starts fresh at the sheet's first (default) snap point rather
    // than wherever the sheet happened to be dragged to last time.
    var $body = $modal.find('.comments-modal-body');
    $body.addClass('is-opening');
    $body[0].style.removeProperty('--sheet-height');
    sheetSnapIndex = 0;
    // A post without photos/video needs little room above the comments,
    // so the sheet opens at its second (taller) snap point.
    var postCard = document.querySelector('.post-card[data-post-id="' + postId + '"]');
    var postHasMedia = postCard && postCard.querySelector('.post-card-media-item, .post-card-photo');
    if (!(opts.media && opts.media.length) && !postHasMedia) {
      sheetSnapIndex = 1;
      $body[0].style.setProperty('--sheet-height', (SHEET_SNAP_POINTS[1] * 100) + '%');
    }

    // Desktop: size/position the panel from the clicked post's own
    // rect instead of taking over the whole screen (see
    // applyDesktopAnchor). Mobile/tablet: clears any leftover anchor
    // styling so the full-screen sheet applies untouched.
    $modal.data('anchor-rect', opts.anchorRect || null);
    applyDesktopAnchor($modal);

    var media = opts.media && opts.media.length && window.bootstrap ? opts.media : null;
    if (window.bootstrap) {
      prepareCommentsModalInstance($modal[0], media ? 'media' : 'default');
      var start = media ? moveMediaIntoComments($modal, media) : null;
      bootstrap.Modal.getOrCreateInstance($modal[0]).show(); // synchronous in media mode (no fade)
      if (media) { animateMediaIn($modal, start); }
    }

    $.ajax({
      url: '/post/' + postId + '/comments/',
      type: 'GET',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      success: function (data) {
        // In media mode the top of the screen is the post's own media,
        // so the post's copy isn't needed there.
        if (!commentsMedia) { $modal.find('.js-comments-post-pane').html(data.post_html); }
        $modal.find('.js-comments-thread-list').html(data.comments_html);
        // "Who can reply" (feed/post_settings.py): swap the comment box
        // for a note when this viewer isn't allowed to reply.
        var locked = data.can_reply === false;
        $modal.toggleClass('is-reply-locked', locked);
        $modal.find('.js-comment-composer').prop('hidden', locked);
        $modal.find('.js-comments-reply-note').remove();
        if (locked) {
          $('<div class="comments-reply-note js-comments-reply-note"><i class="bi bi-chat-dots"></i><span></span></div>')
            .find('span').text(data.reply_note).end()
            .insertAfter($modal.find('.js-comment-composer'));
        }
        updateCommentCountUI(postId, data.comments_count);
        if (highlightCommentId) { revealComment($modal, highlightCommentId); }
        if (opts.expandChildrenOf) {
          var $ownToggle = $modal.find('#comment-' + opts.expandChildrenOf)
            .children('.comment-body').children('.js-toggle-replies');
          if ($ownToggle.length && !$ownToggle.next('.comment-replies').is(':visible')) {
            $ownToggle.trigger('click');
          }
        }
        if (opts.openReplyFor) {
          // Opens the box now (so it's there even if the modal's own
          // transition already finished) — but Bootstrap focuses the
          // modal shell itself once ITS transition finishes, which
          // typically lands after this and steals focus right back.
          // The 'shown.bs.modal' handler below re-focuses the input
          // once that's actually settled, using this data flag.
          $modal.find('.js-reply-toggle[data-comment-id="' + opts.openReplyFor + '"]').first().trigger('click');
          $modal.data('pending-reply-focus', opts.openReplyFor);
        }
      }
    });
  }

  $(document).on('click', '.js-open-comments', function () {
    var postCard = this.closest('.post-card');
    var anchorRect = postCard ? postCard.getBoundingClientRect() : null;
    openCommentsModal($(this).data('post-id'), $(this).data('comment-id'), { anchorRect: anchorRect, media: feedMediaFor(this) });
  });
  // A Replies-tab reply card is itself a .js-open-comments (clicking
  // anywhere on it opens the thread) but it also carries its own
  // like/comment/repost/share/bookmark action row, same as a post
  // card, plus its own 3-dot menu (comment-menu) and inline edit form.
  // Clicks inside any of those must not also re-trigger the whole
  // card's click — jQuery resolves delegated handlers innermost-first
  // for one event, so stopping it here (closer to the target) keeps
  // it from ever reaching the outer card handler above. Bootstrap's
  // own dropdown open/close listener is a separate, non-jQuery
  // listener on document, so stopping propagation here doesn't
  // interfere with it.
  $(document).on('click', '.profile-reply-card .post-card-actions, .profile-reply-card .post-card-menu, .profile-reply-card .reply-edit-form, .profile-reply-card .js-reply-view-children', function (e) {
    e.stopPropagation();
  });
  // The row's own comment icon opens the same thread, but — unlike
  // clicking the card itself — also opens this reply's own inline
  // reply box as soon as the thread loads, so the user can comment on
  // it in one click instead of having to find it in the thread first.
  $(document).on('click', '.js-reply-open-comments', function () {
    var commentId = $(this).data('comment-id');
    var postCard = this.closest('.post-card');
    var anchorRect = postCard ? postCard.getBoundingClientRect() : null;
    openCommentsModal($(this).data('post-id'), commentId, { openReplyFor: commentId, anchorRect: anchorRect });
  });
  // "View N replies" on a Replies-tab card — there's no nested copy of
  // the thread to expand in place here, so this opens the real thread,
  // scrolls to this reply, and expands its own children there.
  $(document).on('click', '.js-reply-view-children', function () {
    var commentId = $(this).data('comment-id');
    var postCard = this.closest('.post-card');
    var anchorRect = postCard ? postCard.getBoundingClientRect() : null;
    openCommentsModal($(this).data('post-id'), commentId, { expandChildrenOf: commentId, anchorRect: anchorRect });
  });
  // The Replies-tab reply card is a div (it can contain a photo/video,
  // which a <button> can't host cleanly) acting as a button, so give
  // it the keyboard behavior a real button would have for free.
  $(document).on('keydown', '.js-open-comments[role="button"]', function (e) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      $(this).trigger('click');
    }
  });

  // Edit/delete a reply right from its card on the profile's Replies
  // tab. Same /comment/<id>/edit|delete/ endpoints the full thread's
  // own Edit/Delete use, but this card isn't a .comment-item (it's a
  // post-card look-alike), so it gets its own small handlers rather
  // than reusing js-edit-comment-btn/js-delete-comment-btn, which
  // assume that other DOM shape. Both desktop and mobile layouts
  // render the same reply (CSS just hides one), so edits/deletes are
  // applied to every card sharing that comment id, not just the one
  // clicked.
  $(document).on('click', '.js-reply-edit-btn', function () {
    var commentId = $(this).data('comment-id');
    var $cards = $('.profile-reply-card[data-comment-id="' + commentId + '"]');
    $cards.each(function () {
      var $card = $(this);
      var currentText = $.trim($card.find('.js-reply-text').text());
      $card.find('.js-reply-edit-form textarea').val(currentText);
      $card.find('.js-reply-text').hide();
      $card.find('.js-reply-edit-form').addClass('open');
    });
  });

  $(document).on('click', '.js-cancel-reply-edit', function () {
    var $card = $(this).closest('.profile-reply-card');
    $card.find('.js-reply-edit-form').removeClass('open');
    $card.find('.js-reply-text').show();
  });

  $(document).on('click', '.js-save-reply-edit', function () {
    var $btn = $(this);
    var commentId = $btn.data('comment-id');
    var $form = $btn.closest('.js-reply-edit-form');
    var content = $.trim($form.find('textarea').val());
    if (!content) { return; }
    $.ajax({
      url: '/comment/' + commentId + '/edit/',
      type: 'POST',
      data: { content: content },
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
      success: function (data) {
        var $cards = $('.profile-reply-card[data-comment-id="' + commentId + '"]');
        $cards.each(function () {
          var $card = $(this);
          $card.find('.js-reply-text').text(data.content).show();
          $card.find('.js-reply-edit-form').removeClass('open');
          if (data.is_edited && $card.find('.js-reply-edited-label').length === 0) {
            $card.find('.post-card-meta .post-card-time').after(
              '<span class="post-card-dot">&middot;</span><span class="post-card-edited js-reply-edited-label">Edited</span>'
            );
          }
        });
        showToast('Reply updated successfully.');
      },
      error: function (xhr) {
        var msg = (xhr.responseJSON && xhr.responseJSON.error) || 'Could not update your reply.';
        showToast(msg, 'error');
      }
    });
  });

  var $pendingDeleteReplyCommentId = null;

  $(document).on('click', '.js-reply-delete-btn', function () {
    $pendingDeleteReplyCommentId = $(this).data('comment-id');
    $pendingDeleteForm = null;
    $pendingDeleteCommentBtn = null;
    var modalEl = document.getElementById('confirmDeleteModal');
    if (modalEl) {
      $(modalEl).find('.confirm-modal-title').text('Delete this reply?');
      $(modalEl).find('.confirm-modal-text').text("This can't be undone.");
    }
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  });

  // Kick off the shrink/slide-up transition only once the modal is
  // actually on screen (Bootstrap's own fade-in has finished), and
  // reset it on close so the next open starts from the same frame.
  $('#commentsModal').on('shown.bs.modal', function () {
    var $modal = $(this);
    uiSheets.commentsOpen = true;
    var $body = $modal.find('.comments-modal-body');
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        $body.removeClass('is-opening');
      });
    });

    // Bootstrap just focused the modal shell itself as part of this
    // same show sequence (before this event fires) — if we were
    // asked to land the user in a reply box (see openCommentsModal's
    // openReplyFor), take focus back from it now that that's done.
    var replyFocusId = $modal.data('pending-reply-focus');
    if (replyFocusId) {
      $modal.removeData('pending-reply-focus');
      $modal.find('.js-reply-form[data-parent-id="' + replyFocusId + '"] .comment-reply-input').first().focus();
    }
  });
  $('#commentsModal').on('hidden.bs.modal', function () {
    var $modal = $(this);
    $modal.find('.comments-modal-body').addClass('is-opening').removeClass('is-closing');
    uiSheets.commentsOpen = false;
    if (commentsMedia) {
      putMediaBack(); // no-op if the close animation already did it
      commentsMedia = null;
      $modal.removeClass('comments-media-mode is-media-active');
      $modal.find('.js-comments-post-pane').empty();
    }
  });

  // Media mode has no Bootstrap backdrop (see prepareCommentsModalInstance),
  // so a click on the dimmed page around the desktop panel — the modal
  // element itself, not anything inside the panel — closes it, as the
  // backdrop did before. (On a phone the panel fills the screen, so
  // there's nothing outside it to click.)
  $('#commentsModal').on('click', function (e) {
    if (e.target === this && commentsMedia) { closeCommentsSheet(); }
  });

  // Media mode: run the reverse animation first; the real hide follows
  // it (see animateMediaOut). Covers the X, Esc and drag-to-dismiss,
  // since all of them go through Bootstrap's hide.
  $('#commentsModal').on('hide.bs.modal', function (e) {
    if (!commentsMedia || commentsMedia.closed) { return; }
    e.preventDefault();
    if (!commentsMedia.closing) { animateMediaOut($(this)); }
  });

  // The photo/video picker — pick a file, show a small thumbnail (with
  // a way to back out) above the input, same idea as attaching a file
  // to an email. Nothing uploads yet; that happens on actual submit.
  function clearComposerMedia($form) {
    var $fileInput = $form.find('.js-comment-media-input');
    $fileInput.val('');
    $form.find('.js-comment-media-preview').empty().removeClass('open');
  }

  $(document).on('change', '.js-comment-media-input', function () {
    var $form = $(this).closest('.js-comment-composer');
    var $preview = $form.find('.js-comment-media-preview');
    var file = this.files && this.files[0];
    if (!file) {
      $preview.empty().removeClass('open');
      return;
    }
    var isVideo = file.type.indexOf('video') === 0;
    var url = URL.createObjectURL(file);
    var $thumb = $('<div class="comment-media-preview-thumb"></div>');
    $thumb.append(isVideo ? $('<video muted></video>').attr('src', url) : $('<img alt="">').attr('src', url));
    var $remove = $('<button type="button" class="comment-media-preview-remove" aria-label="Remove photo/video"><i class="bi bi-x-lg"></i></button>');
    $preview.empty().addClass('open').append($thumb, $remove);
  });

  $(document).on('click', '.comment-media-preview-remove', function () {
    clearComposerMedia($(this).closest('.js-comment-composer'));
  });

  // New top-level comment, from the composer at the bottom of the modal.
  // A comment can be text, a photo/video, or both, so FormData (not a
  // plain object) is required here once a file might be attached.
  $(document).on('submit', '.js-comment-composer', function (e) {
    e.preventDefault();
    var $form = $(this);
    var postId = $('#commentsModal').data('post-id');
    var $input = $form.find('.js-comment-composer-input');
    var $fileInput = $form.find('.js-comment-media-input');
    var content = $.trim($input.val());
    var file = $fileInput[0] && $fileInput[0].files[0];
    if ((!content && !file) || !postId) {
      return;
    }

    var formData = new FormData();
    formData.append('content', content);
    if (file) {
      formData.append('media', file);
    }

    $.ajax({
      url: '/post/' + postId + '/comments/add/',
      type: 'POST',
      data: formData,
      processData: false,
      contentType: false,
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
      success: function (data) {
        $('#commentsModal .comments-empty-state').remove();
        $('#commentsModal .js-comments-thread-list').append(data.comment_html);
        $input.val('');
        clearComposerMedia($form);
        updateCommentCountUI(postId, data.comments_count);
      },
      error: function (xhr) {
        var msg = (xhr.responseJSON && xhr.responseJSON.error) || 'Could not post your comment.';
        showToast(msg, 'error');
      }
    });
  });

  // Reply — toggles a small inline reply box open/closed under the
  // comment being replied to.
  $(document).on('click', '.js-reply-toggle', function () {
    var commentId = $(this).data('comment-id');
    $('.js-reply-form[data-parent-id="' + commentId + '"]').first().toggleClass('open').find('.comment-reply-input').focus();
  });

  $(document).on('click', '.js-submit-reply', function () {
    var $btn = $(this);
    var $form = $btn.closest('.js-reply-form');
    var postId = $btn.data('post-id');
    var parentId = $btn.data('parent-id');
    var $input = $form.find('.comment-reply-input');
    var content = $.trim($input.val());
    if (!content) {
      return;
    }

    $.ajax({
      url: '/post/' + postId + '/comments/add/',
      type: 'POST',
      data: { content: content, parent_id: parentId },
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
      success: function (data) {
        var $parentBody = $('#comment-' + parentId).children('.comment-body').first();
        var $toggle = $parentBody.children('.js-toggle-replies');
        var $replies = $parentBody.children('.comment-replies');
        if ($replies.length === 0) {
          // First reply ever on this comment — build the toggle +
          // container together, already expanded since the user just
          // asked to see this reply by writing it.
          $toggle = $(
            '<button type="button" class="js-toggle-replies comment-view-replies" data-comment-id="' + parentId + '">' +
            '<i class="bi bi-chevron-up js-reply-chevron"></i> ' +
            '<span class="js-reply-toggle-text">Hide replies</span>' +
            '</button>'
          );
          $replies = $('<div class="comment-replies"></div>');
          $parentBody.children('.js-reply-form').first().after($toggle, $replies);
        } else if (!$replies.is(':visible')) {
          // Already had replies, but collapsed — expand so the new
          // one is actually visible instead of silently hidden.
          $replies.show();
          $toggle.find('.js-reply-chevron').removeClass('bi-chevron-down').addClass('bi-chevron-up');
          $toggle.find('.js-reply-toggle-text').text('Hide replies');
        }
        $replies.append(data.comment_html);
        $input.val('');
        $form.removeClass('open');
        updateCommentCountUI($('#commentsModal').data('post-id'), data.comments_count);
      },
      error: function (xhr) {
        var msg = (xhr.responseJSON && xhr.responseJSON.error) || 'Could not post your reply.';
        showToast(msg, 'error');
      }
    });
  });

  $(document).on('keydown', '.comment-reply-input', function (e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      $(this).closest('.comment-reply-form').find('.js-submit-reply').trigger('click');
    }
  });

  // Edit a comment in place — swaps the comment's text for a textarea
  // pre-filled with its current content.
  $(document).on('click', '.js-edit-comment-btn', function () {
    var commentId = $(this).data('comment-id');
    var $bubble = $('#comment-' + commentId).children('.comment-body').children('.comment-bubble').first();
    $bubble.find('.js-comment-text').first().hide();
    $bubble.find('.js-comment-edit-form').first().addClass('open').find('.comment-edit-textarea').focus();
  });

  $(document).on('click', '.js-cancel-edit-comment', function () {
    var $bubble = $(this).closest('.comment-bubble');
    $bubble.find('.js-comment-edit-form').removeClass('open');
    $bubble.find('.js-comment-text').show();
  });

  $(document).on('click', '.js-save-edit-comment', function () {
    var $btn = $(this);
    var commentId = $btn.data('comment-id');
    var $bubble = $btn.closest('.comment-bubble');
    var content = $.trim($bubble.find('.comment-edit-textarea').val());
    if (!content) {
      return;
    }

    $.ajax({
      url: '/comment/' + commentId + '/edit/',
      type: 'POST',
      data: { content: content },
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
      success: function (data) {
        $bubble.find('.js-comment-text').text(data.content).show();
        $bubble.find('.js-comment-edit-form').removeClass('open');
        var $head = $bubble.find('.comment-bubble-head').first();
        if (data.is_edited && $head.find('.comment-edited').length === 0) {
          $head.append(' <span class="comment-dot">&middot;</span> <span class="comment-edited">Edited</span>');
        }
        showToast('Comment updated successfully.');
      },
      error: function (xhr) {
        var msg = (xhr.responseJSON && xhr.responseJSON.error) || 'Could not update your comment.';
        showToast(msg, 'error');
      }
    });
  });

  // Delete a comment — reuses the same confirm modal as delete-post
  // (see that handler above, which checks $pendingDeleteCommentBtn too).
  $(document).on('click', '.js-delete-comment-btn', function () {
    $pendingDeleteCommentBtn = $(this);
    $pendingDeleteForm = null;
    $pendingDeleteReplyCommentId = null;
    var modalEl = document.getElementById('confirmDeleteModal');
    if (modalEl) {
      $(modalEl).find('.confirm-modal-title').text('Delete this comment?');
      $(modalEl).find('.confirm-modal-text').text("This can't be undone, and any replies to it will be deleted too.");
    }
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  });

  // Like / unlike a comment (or a reply) — TikTok-style: just the
  // icon plus a plain count next to it, not the post's avatars-and-
  // names "Liked by ..." row.
  $(document).on('click', '.js-like-comment-btn', function () {
    var $btn = $(this);
    var commentId = $btn.data('comment-id');
    $.ajax({
      url: '/comment/' + commentId + '/like/toggle/',
      type: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
      success: function (data) {
        var $icon = $btn.find('i');
        if (data.liked) {
          $icon.attr('class', 'bi bi-heart-fill');
          $btn.addClass('liked').attr('title', 'Unlike');
          $btn.removeClass('like-pop');
          requestAnimationFrame(function () {
            $btn.addClass('like-pop');
          });
        } else {
          $icon.attr('class', 'bi bi-heart');
          $btn.removeClass('liked').attr('title', 'Like');
        }
        var $count = $btn.siblings('.comment-like-count');
        if (data.likes_count > 0) {
          if ($count.length === 0) {
            $btn.after($('<span class="comment-like-count"></span>').text(data.likes_count));
          } else {
            $count.text(data.likes_count);
          }
        } else {
          $count.remove();
        }
      }
    });
  });

  // "View N replies" — replies are collapsed by default (TikTok-
  // style) and only rendered into view on request, with a smooth
  // jQuery slide rather than an instant show/hide.
  $(document).on('click', '.js-toggle-replies', function () {
    var $btn = $(this);
    var $replies = $btn.next('.comment-replies');
    if ($replies.is(':visible')) {
      var count = $replies.children('.comment-item').length;
      $replies.slideUp(200);
      $btn.find('.js-reply-chevron').removeClass('bi-chevron-up').addClass('bi-chevron-down');
      $btn.find('.js-reply-toggle-text').text('View ' + count + ' repl' + (count === 1 ? 'y' : 'ies'));
    } else {
      $replies.slideDown(200);
      $btn.find('.js-reply-chevron').removeClass('bi-chevron-down').addClass('bi-chevron-up');
      $btn.find('.js-reply-toggle-text').text('Hide replies');
    }
  });
});

// =============================================================
// Stories/Status carousel + viewer (Home feed).
//
// The carousel row (#storiesRow) scrolls horizontally with the mouse
// wheel/trackpad (vertical wheel delta is redirected sideways) and
// supports click-and-drag with the mouse; touch scrolling needs no JS
// since the row is a plain overflow-x:auto strip. A drag is only
// treated as a drag (and the click it would otherwise end on
// suppressed) once the pointer has moved a few pixels — otherwise an
// ordinary tap on a card would never open it.
//
// Clicking a card with active stories opens the full-screen viewer
// (#storyViewer); clicking "Your stories" with none yet, or its "+"
// badge, opens the upload modal (#storyUploadModal) instead. Each
// user's stories data comes from the `storiesData` JSON script tag
// feed/views.py renders — see _serialize_stories_for_js().
// =============================================================
// Set up for every page shown (nav.js loads pages in place); listeners
// on window/document use the page's `signal`, so leaving the page
// removes them.
UC.onPage(function (_doc, signal) {
  var row = document.getElementById('storiesRow');
  var dataEl = document.getElementById('storiesData');
  if (!row || !dataEl) return;

  var storiesData = JSON.parse(dataEl.textContent);

  // Same cookie reader app.js already uses elsewhere for CSRF —
  // duplicated locally since the original is scoped inside the
  // document-ready closure above this one.
  function getCookie(name) {
    var cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      var cookies = document.cookie.split(';');
      for (var i = 0; i < cookies.length; i++) {
        var cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  function openUploadModal() {
    var modalEl = document.getElementById('storyUploadModal');
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  }

  // -----------------------------------------------------------
  // Horizontal scroll: wheel/trackpad + mouse drag.
  // -----------------------------------------------------------
  row.addEventListener('wheel', function (e) {
    if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
    e.preventDefault();
    row.scrollLeft += e.deltaY;
  }, { passive: false });

  var isDown = false;
  var didDrag = false;
  var startX = 0;
  var startScrollLeft = 0;

  row.addEventListener('mousedown', function (e) {
    isDown = true;
    didDrag = false;
    startX = e.pageX;
    startScrollLeft = row.scrollLeft;
  });

  window.addEventListener('mousemove', function (e) {
    if (!isDown) return;
    var delta = e.pageX - startX;
    if (Math.abs(delta) > 4) {
      didDrag = true;
      row.classList.add('is-dragging');
    }
    if (didDrag) {
      row.scrollLeft = startScrollLeft - delta;
    }
  }, { signal: signal });

  function endDrag() {
    if (!isDown) return;
    isDown = false;
    row.classList.remove('is-dragging');
  }
  window.addEventListener('mouseup', endDrag, { signal: signal });
  row.addEventListener('mouseleave', endDrag);

  // -----------------------------------------------------------
  // Opening a card: the "+" badge always opens the uploader; the
  // rest of a card opens the viewer if it has active stories, or the
  // uploader if it's "Your stories" with none yet. Swallowed after a
  // drag so a drag-release never also opens something.
  // -----------------------------------------------------------
  function activateCard(card) {
    var userId = parseInt(card.getAttribute('data-user-id'), 10);
    var group = storiesData.filter(function (g) { return g.userId === userId; })[0];
    if (!group) return;
    if (group.stories.length === 0) {
      openUploadModal();
    } else {
      openViewer(userId);
    }
  }

  row.addEventListener('click', function (e) {
    if (didDrag) { didDrag = false; return; }
    var addBtn = e.target.closest('.js-open-story-upload');
    if (addBtn) {
      e.stopPropagation();
      openUploadModal();
      return;
    }
    var card = e.target.closest('.story-card');
    if (card) activateCard(card);
  });

  row.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var card = e.target.closest('.story-card');
    if (!card) return;
    e.preventDefault();
    activateCard(card);
  });

  // -----------------------------------------------------------
  // Upload modal — live preview of the chosen photo, and the submit
  // button only enables once a file is actually picked.
  // -----------------------------------------------------------
  var uploadModalEl = document.getElementById('storyUploadModal');
  var fileInput = document.querySelector('.js-story-upload-input');
  var preview = document.querySelector('.js-story-upload-preview');
  var placeholder = document.querySelector('.js-story-upload-placeholder');
  var submitBtn = document.querySelector('.js-story-upload-submit');
  var captionInput = document.querySelector('.story-upload-caption-input');

  if (fileInput) {
    fileInput.addEventListener('change', function () {
      var file = fileInput.files && fileInput.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function (e) {
        preview.src = e.target.result;
        preview.hidden = false;
        placeholder.hidden = true;
        if (submitBtn) submitBtn.disabled = false;
      };
      reader.readAsDataURL(file);
    });
  }
  if (uploadModalEl) {
    uploadModalEl.addEventListener('hidden.bs.modal', function () {
      if (fileInput) fileInput.value = '';
      if (preview) { preview.src = ''; preview.hidden = true; }
      if (placeholder) placeholder.hidden = false;
      if (submitBtn) submitBtn.disabled = true;
      if (captionInput) captionInput.value = '';
    });
  }

  // -----------------------------------------------------------
  // Story viewer — one group (a user's stories) at a time, auto-
  // advancing through that group's stories then on to the next
  // group, with a segmented progress bar like Instagram/TikTok
  // stories. Holding the image down pauses it; releasing resumes.
  // -----------------------------------------------------------
  var viewerEl = document.getElementById('storyViewer');
  if (!viewerEl) return;

  var progressEl = viewerEl.querySelector('.js-story-viewer-progress');
  var avatarEl = viewerEl.querySelector('.js-story-viewer-avatar');
  var usernameEl = viewerEl.querySelector('.js-story-viewer-username');
  var timeEl = viewerEl.querySelector('.js-story-viewer-time');
  var imageEl = viewerEl.querySelector('.js-story-viewer-image');
  var captionEl = viewerEl.querySelector('.js-story-viewer-caption');
  var viewsEl = viewerEl.querySelector('.js-story-viewer-views');
  var deleteBtn = viewerEl.querySelector('.js-story-viewer-delete');
  var prevBtn = viewerEl.querySelector('.js-story-viewer-prev');
  var nextBtn = viewerEl.querySelector('.js-story-viewer-next');
  var closeEls = viewerEl.querySelectorAll('.js-story-viewer-close');

  var STORY_DURATION_MS = 5000;
  var viewerList = [];
  var groupIdx = -1;
  var storyIdx = 0;
  var rafId = null;
  var segmentStart = 0;
  var remainingMs = STORY_DURATION_MS;
  var paused = false;
  var viewedStoryIds = {};

  function usersWithStories() {
    return storiesData.filter(function (g) { return g.stories.length > 0; });
  }

  function openViewer(userId) {
    viewerList = usersWithStories();
    groupIdx = -1;
    for (var i = 0; i < viewerList.length; i++) {
      if (viewerList[i].userId === userId) { groupIdx = i; break; }
    }
    if (groupIdx === -1) return;
    storyIdx = 0;
    viewerEl.classList.add('is-open');
    viewerEl.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    renderGroup();
  }

  function closeViewer() {
    stopTimer();
    viewerEl.classList.remove('is-open');
    viewerEl.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  }

  function currentGroup() { return viewerList[groupIdx]; }
  function currentStory() {
    var g = currentGroup();
    return g ? g.stories[storyIdx] : null;
  }

  function buildProgressBars(count) {
    progressEl.innerHTML = '';
    for (var i = 0; i < count; i++) {
      var seg = document.createElement('div');
      seg.className = 'story-viewer-progress-seg';
      var fill = document.createElement('span');
      fill.className = 'story-viewer-progress-seg-fill';
      seg.appendChild(fill);
      progressEl.appendChild(seg);
    }
  }

  function renderGroup() {
    var g = currentGroup();
    if (!g) { closeViewer(); return; }
    buildProgressBars(g.stories.length);
    avatarEl.style.backgroundImage = g.avatarUrl ? 'url(' + g.avatarUrl + ')' : '';
    usernameEl.textContent = g.isSelf ? 'Your story' : g.displayName;
    renderStory();
  }

  function renderStory() {
    var g = currentGroup();
    var story = currentStory();
    if (!g || !story) { closeViewer(); return; }

    imageEl.src = story.imageUrl;
    captionEl.textContent = story.caption || '';
    timeEl.textContent = story.createdDisplay;
    deleteBtn.hidden = !g.isSelf;
    deleteBtn.setAttribute('data-story-id', story.id);
    if (g.isSelf && story.viewsCount !== null && story.viewsCount !== undefined) {
      viewsEl.textContent = story.viewsCount + (story.viewsCount === 1 ? ' view' : ' views');
    } else {
      viewsEl.textContent = '';
    }

    markSegments(storyIdx);
    recordView(story.id);
    startTimer();
  }

  function markSegments(activeIdx) {
    var segs = progressEl.querySelectorAll('.story-viewer-progress-seg');
    segs.forEach(function (seg, i) {
      seg.classList.toggle('is-done', i < activeIdx);
      if (i >= activeIdx) {
        var fill = seg.querySelector('.story-viewer-progress-seg-fill');
        if (fill) fill.style.width = '0%';
      }
    });
  }

  function startTimer() {
    stopTimer();
    remainingMs = STORY_DURATION_MS;
    segmentStart = Date.now();
    paused = false;
    rafId = requestAnimationFrame(tick);
  }

  function tick() {
    if (paused) return;
    var elapsed = Date.now() - segmentStart;
    var pct = Math.min(100, (elapsed / STORY_DURATION_MS) * 100);
    var segs = progressEl.querySelectorAll('.story-viewer-progress-seg');
    var fill = segs[storyIdx] && segs[storyIdx].querySelector('.story-viewer-progress-seg-fill');
    if (fill) fill.style.width = pct + '%';
    if (elapsed >= STORY_DURATION_MS) {
      goNext();
      return;
    }
    rafId = requestAnimationFrame(tick);
  }

  function stopTimer() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
  }

  function pauseTimer() {
    if (paused || !viewerEl.classList.contains('is-open')) return;
    paused = true;
    remainingMs = STORY_DURATION_MS - (Date.now() - segmentStart);
    stopTimer();
  }

  function resumeTimer() {
    if (!paused) return;
    paused = false;
    segmentStart = Date.now() - (STORY_DURATION_MS - remainingMs);
    rafId = requestAnimationFrame(tick);
  }

  function goNext() {
    var g = currentGroup();
    if (!g) return;
    if (storyIdx < g.stories.length - 1) {
      storyIdx++;
      renderStory();
    } else if (groupIdx < viewerList.length - 1) {
      groupIdx++;
      storyIdx = 0;
      renderGroup();
    } else {
      closeViewer();
    }
  }

  function goPrev() {
    if (storyIdx > 0) {
      storyIdx--;
      renderStory();
    } else if (groupIdx > 0) {
      groupIdx--;
      storyIdx = currentGroup().stories.length - 1;
      renderGroup();
    }
  }

  // Recorded once per story per page load client-side too, just to
  // skip a pointless repeat request — the server already enforces
  // "once per viewer per story" regardless (see StoryView's
  // UniqueConstraint).
  function recordView(storyId) {
    if (viewedStoryIds[storyId]) return;
    viewedStoryIds[storyId] = true;
    fetch('/stories/' + storyId + '/view/', {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
    }).catch(function () {});
  }

  if (nextBtn) nextBtn.addEventListener('click', function (e) { e.stopPropagation(); goNext(); });
  if (prevBtn) prevBtn.addEventListener('click', function (e) { e.stopPropagation(); goPrev(); });
  closeEls.forEach(function (el) { el.addEventListener('click', closeViewer); });

  if (deleteBtn) {
    deleteBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var storyId = deleteBtn.getAttribute('data-story-id');
      if (!storyId || !window.confirm('Delete this story?')) return;
      fetch('/stories/' + storyId + '/delete/', {
        method: 'POST',
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
      }).then(function () {
        UC.reload();
      });
    });
  }

  imageEl.addEventListener('mousedown', pauseTimer);
  imageEl.addEventListener('touchstart', pauseTimer, { passive: true });
  document.addEventListener('mouseup', resumeTimer, { signal: signal });
  document.addEventListener('touchend', resumeTimer, { signal: signal });

  // Messages -> Updates opens the same viewer and uploader.
  window.UniStories = { open: openViewer, upload: openUploadModal, data: storiesData };

  // Leaving the page with a story open closes it (stops its timer, unlocks scrolling).
  if (signal) { signal.addEventListener('abort', function () { if (viewerEl.classList.contains('is-open')) closeViewer(); }); }

  document.addEventListener('keydown', function (e) {
    if (!viewerEl.classList.contains('is-open')) return;
    if (e.key === 'Escape') closeViewer();
    else if (e.key === 'ArrowRight') goNext();
    else if (e.key === 'ArrowLeft') goPrev();
  }, { signal: signal });
});

// =====================================================================
// Notifications
//
//   - The unread badge on the existing bell(s): rendered by the server
//     on page load (context processor), then kept current here by
//     polling /notifications/count/ every 30s and whenever the tab
//     comes back into view. Every notifications action also returns
//     the new count, so the badge updates the moment something changes.
//   - Hovering the left sidebar's Notifications link shows a popup
//     with the latest notifications beside it (a preview only).
//     Clicking the link goes to the Notifications page (it
//     fades/slides in, see app.css).
//   - Opening the Notifications page is what marks the shown
//     notifications read — server-side, in the database — so the
//     badge is gone there and after any refresh.
//   - Each entry's three-dot menu: mark read/unread, remove. Pending
//     follow requests get Confirm / Delete buttons.
// =====================================================================
(function ($) {
  if (!$) { return; }

  var POLL_MS = 30000;
  var PANEL_MIN_WIDTH = 993; // the left sidebar is a side column from here up (app.css: max-width 992px)

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function post(url, data) {
    return $.ajax({
      url: url, type: 'POST', data: data || {},
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrf() },
    });
  }

  // ---------------- The badge ----------------
  var baseTitle = document.title.replace(/^\(\d+\+?\)\s*/, '');

  function setUnread(count, text) {
    count = parseInt(count, 10) || 0;
    text = text || (count > 99 ? '99+' : String(count));
    $('.js-notif-badge').each(function () {
      this.textContent = text;
      this.hidden = count === 0;
      this.setAttribute('aria-label', count + ' unread notification' + (count === 1 ? '' : 's'));
    });
    $('.js-notif-dot').prop('hidden', count === 0);
    document.title = (count ? '(' + text + ') ' : '') + baseTitle;
  }

  function applyCountFrom(data) {
    if (data && typeof data.unread !== 'undefined') { setUnread(data.unread, data.badge); }
    if (data && data.reminders && data.reminders.length) { data.reminders.forEach(showClassReminder); }
    if (data && data.chat_since) { chatSince = data.chat_since; }
    if (data && data.chats && data.chats.length) { data.chats.slice().reverse().forEach(showChatPop); }
  }

  // "New message" pop-ups (chat/services.py new_message_popups): not for the
  // chat you're looking at, and not inside Messages (it shows them itself).
  var chatSince = '';
  function viewingChat(conv) {
    if (document.getElementById('waApp')) { return true; }
    var cfg = document.getElementById('gcConfig');
    if (cfg) { try { if (JSON.parse(cfg.textContent).conversation === conv) { return true; } } catch (e) { /* ignore */ } }
    return false;
  }
  function showChatPop(c) {
    if (viewingChat(c.conversation)) { return; }
    var $stack = $('#toastStack');
    if (!$stack.length) { $stack = $('<div class="toast-stack" id="toastStack"></div>').appendTo('body'); }
    $stack.find('.chat-pop[data-conv="' + c.conversation + '"]').remove();
    var $pop = $('<div class="class-reminder-pop chat-pop" role="status">' +
      '<span class="chat-pop-avatar"></span>' +
      '<a class="class-reminder-text"><b></b><span></span></a>' +
      '<button type="button" class="toast-close-btn js-reminder-close" aria-label="Dismiss"><i class="bi bi-x"></i></button></div>');
    $pop.attr('data-conv', c.conversation);
    var $av = $pop.find('.chat-pop-avatar');
    if (c.sender && c.sender.photo) { $av.css('background-image', 'url("' + c.sender.photo.replace(/"/g, '%22') + '")'); }
    else if (c.sender) { $av.text(c.sender.initials).css('background-color', c.sender.colour); }
    $pop.find('.class-reminder-text').attr('href', c.url).find('span').text(c.text);
    $pop.find('.class-reminder-text b').text(c.title);
    $stack.append($pop);
    setTimeout(function () { $pop.fadeOut(300, function () { $pop.remove(); }); }, 9000);
  }

  // "Class starting soon" pop-up (courses/reminders.py). Stays until it's
  // closed or tapped (unlike ordinary toasts), since it's time-sensitive.
  function showClassReminder(r) {
    var $stack = $('#toastStack');
    if (!$stack.length) { $stack = $('<div class="toast-stack" id="toastStack"></div>').appendTo('body'); }
    var $pop = $('<div class="class-reminder-pop" role="alert">' +
      '<span class="class-reminder-ico"><i class="bi bi-alarm-fill"></i></span>' +
      '<a class="class-reminder-text"><b></b><span></span></a>' +
      '<button type="button" class="toast-close-btn js-reminder-close" aria-label="Dismiss"><i class="bi bi-x"></i></button></div>');
    $pop.find('.class-reminder-text').attr('href', r.url).find('span').text(r.text);
    $pop.find('.class-reminder-text b').text(r.title || 'Class starting soon');
    $stack.append($pop);
  }
  $(document).on('click', '.js-reminder-close', function (e) {
    e.stopImmediatePropagation();
    $(this).closest('.class-reminder-pop').remove();
  });

  // A page loaded in place (nav.js) has its own title: keep the "(3) "
  // unread prefix on it, and use it from now on.
  document.addEventListener('uc:page', function () {
    baseTitle = document.title.replace(/^\(\d+\+?\)\s*/, '');
    var $b = $('.js-notif-badge').first();
    setUnread($b.prop('hidden') ? 0 : (parseInt($b.text(), 10) || 100), $b.text());
  });

  function refreshCount() {
    $.ajax({
      url: '/notifications/count/' + (chatSince ? '?chat_since=' + encodeURIComponent(chatSince) : ''), type: 'GET', cache: false,
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      success: applyCountFrom,
    });
  }

  // Only on signed-in app pages (where the bell exists).
  if (!$('.js-notif-badge').length) { return; }
  // Server-rendered count -> also show it in the tab title.
  var $firstBadge = $('.js-notif-badge').first();
  if (!$firstBadge.prop('hidden')) { setUnread(parseInt($firstBadge.text(), 10) || 100, $firstBadge.text()); }

  refreshCount();   // straight away: also starts the clock for "new message" pop-ups
  setInterval(function () {
    if (document.visibilityState === 'visible') { refreshCount(); }
  }, POLL_MS);
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') { refreshCount(); }
  });

  // ---------------- Hover popup on the sidebar bell ----------------
  // Hovering the left sidebar's Notifications link shows the latest
  // notifications in a popup beside it (the design from the
  // social-media project). It's only a preview: it doesn't mark
  // anything read. Clicking the link goes to the Notifications page,
  // which does. Only on screens with a real mouse and room for the
  // sidebar; phones and tablets just use the link.
  var popup = document.getElementById('notifPopup');
  var $bell = $('.js-notif-bell');
  var showTimer = null, hideTimer = null, lastLoad = 0, loading = false;
  var canHover = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;

  function popupAllowed() {
    var sidebar = document.querySelector('.app-sidebar');
    // Not on the Notifications page itself: the full list is already there.
    if (document.querySelector('.notif-page')) { return false; }
    return popup && canHover && window.innerWidth >= PANEL_MIN_WIDTH && sidebar && sidebar.offsetParent !== null;
  }

  function positionPopup() {
    var link = $bell[0].getBoundingClientRect();
    var card = $bell[0].closest('.sidebar-main-card') || $bell[0];
    var cardRight = card.getBoundingClientRect().right;
    var top = Math.max(12, link.top - 8);
    var maxH = window.innerHeight - top - 12;
    popup.style.left = Math.round(cardRight + 18) + 'px';
    popup.style.top = Math.round(top) + 'px';
    popup.style.maxHeight = Math.round(maxH) + 'px';
    // Arrow points at the middle of the Notifications link.
    popup.style.setProperty('--arrow-top', Math.round(link.top + link.height / 2 - top - 9) + 'px');
  }

  function loadPopup() {
    // Refresh at most every 15s while hovering in and out.
    if (loading || Date.now() - lastLoad < 15000) { return; }
    loading = true;
    $.ajax({
      url: '/notifications/?preview=1', type: 'GET', cache: false,
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      success: function (data) {
        $(popup).find('.js-notif-popup-body').html(data.html);
        lastLoad = Date.now();
        applyCountFrom(data);
      },
      complete: function () { loading = false; },
    });
  }

  function showPopup() {
    clearTimeout(hideTimer);
    if (!popupAllowed()) { return; }
    positionPopup();
    if (popup.hidden) {
      popup.hidden = false;
      popup.getBoundingClientRect();
      popup.classList.add('is-open');
    }
    loadPopup();
  }

  function hidePopup(now) {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    hideTimer = setTimeout(function () {
      popup.classList.remove('is-open');
      setTimeout(function () { if (!popup.classList.contains('is-open')) { popup.hidden = true; } }, 150);
    }, now ? 0 : 180);
  }

  if (popup) {
    // A short delay so just sweeping the mouse past the link doesn't flash it.
    $bell.on('mouseenter', function () { clearTimeout(hideTimer); showTimer = setTimeout(showPopup, 120); });
    $bell.on('mouseleave', function () { hidePopup(); });
    $(popup).on('mouseenter', function () { clearTimeout(hideTimer); });
    $(popup).on('mouseleave', function () { hidePopup(); });
    $bell.on('click', function () { hidePopup(true); }); // clicking goes to the page
    $(document).on('keydown', function (e) { if (e.key === 'Escape' && !popup.hidden) { hidePopup(true); } });
    $(window).on('resize scroll', function () { if (!popup.hidden) { hidePopup(true); } });
  }

  // ---------------- Entry actions (Notifications page) ----------------
  function tidyList($list) {
    // Drop a "New"/"Earlier" title left with nothing under it, and show
    // the empty state once the last entry is gone.
    $list.find('.notif-section-title').each(function () {
      var $next = $(this).nextAll('.notif-item, .notif-section-title').first();
      if (!$next.length || $next.hasClass('notif-section-title')) { $(this).remove(); }
    });
    if (!$list.find('.js-notif-item').length) { $list.find('.js-notif-empty').removeClass('d-none'); }
  }

  function removeItem($item) {
    var $list = $item.closest('.js-notif-list');
    $item.addClass('is-removing');
    setTimeout(function () { $item.remove(); tidyList($list); }, 200);
  }

  $(document).on('click', '.js-notif-mark', function () {
    var $item = $(this).closest('.js-notif-item');
    // data-read is the database state. (Right after opening the list,
    // the "New" entries are still highlighted but already read.)
    var toState = $item.attr('data-read') === '1' ? 'unread' : 'read';
    post('/notifications/mark/', { ids: $item.data('ids'), state: toState }).done(function (data) {
      $item.attr('data-read', toState === 'read' ? '1' : '0');
      $item.toggleClass('is-unread', toState === 'unread');
      $item.find('.js-notif-mark-label').text(toState === 'unread' ? 'Mark as read' : 'Mark as unread');
      applyCountFrom(data);
    }).fail(function () { showToast('Could not update that notification.', 'error'); });
  });

  $(document).on('click', '.js-notif-delete', function () {
    var $item = $(this).closest('.js-notif-item');
    post('/notifications/delete/', { ids: $item.data('ids') }).done(function (data) {
      removeItem($item);
      applyCountFrom(data);
    }).fail(function () { showToast('Could not remove that notification.', 'error'); });
  });

  $(document).on('click', '.js-notif-follow-accept', function () {
    var $btn = $(this);
    var $item = $btn.closest('.js-notif-item');
    $btn.prop('disabled', true);
    post('/follow-requests/' + $btn.data('follow-id') + '/accept/').done(function () {
      $item.find('.js-notif-follow-actions').replaceWith('<div class="notif-actions-done"><i class="bi bi-check2"></i> Request confirmed</div>');
      $item.find('.notif-text').html(function (i, html) { return html.replace('requested to follow you.', 'started following you.'); });
      refreshCount();
    }).fail(function () { $btn.prop('disabled', false); showToast('Could not confirm that request.', 'error'); });
  });

  $(document).on('click', '.js-notif-follow-decline', function () {
    var $btn = $(this);
    var $item = $btn.closest('.js-notif-item');
    $btn.prop('disabled', true);
    post('/follow-requests/' + $btn.data('follow-id') + '/decline/').done(function () {
      removeItem($item); // declining also removes the request's notification server-side
      refreshCount();
      showToast('Follow request deleted.');
    }).fail(function () { $btn.prop('disabled', false); showToast('Could not delete that request.', 'error'); });
  });

  // ---------------- Opening a comment from a notification ----------------
  // A comment/reply/mention notification goes to /post/<id>/?comment=<id>:
  // open that post's comments with the comment scrolled to and
  // highlighted (the same thing the Replies tab does).
  UC.onPage(function () {
    var params = new URLSearchParams(window.location.search);
    var commentId = params.get('comment');
    if (!commentId || !/^\d+$/.test(commentId)) { return; }
    var $btn = $('.app-main .post-card .js-open-comments').first();
    if (!$btn.length) { return; }
    params.delete('comment');
    var rest = params.toString();
    history.replaceState(history.state, '', window.location.pathname + (rest ? '?' + rest : '') + window.location.hash);
    setTimeout(function () {
      $btn.data('comment-id', parseInt(commentId, 10));
      $btn.trigger('click');
      $btn.removeData('comment-id');
    }, 150);
  });
})(window.jQuery);

// =====================================================================
// Sidebar / drawer navigation: exactly one active item.
// Clicking a link (Home, Bookmarks, Profile, Notifications, ...) makes
// it the active one immediately, instead of the old item staying
// highlighted until the next page has loaded. The page that loads then
// renders the same item active itself (base_app.html).
// =====================================================================
(function ($) {
  if (!$) { return; }
  function setActive(link) {
    var $all = $('.app-sidebar .app-nav-link, .app-mobile-drawer .app-nav-link');
    $all.filter('.active').each(function () {
      $(this).removeClass('active');
      $(this).find('i.bi').each(function () { this.className = this.className.replace(/-fill\b/, ''); });
    });
    // Mark every copy of this link (sidebar + phone drawer) active.
    var href = link.getAttribute('href');
    $all.filter(function () { return this.getAttribute('href') === href; }).each(function () {
      $(this).addClass('active');
      $(this).find('i.bi').first().each(function () {
        // Icons with a filled version (house-door, people, bookmark, person,
        // chat-dots, bell) switch to it, like the server-rendered active state.
        if (/bi-(house-door|people|bookmark|person|chat-dots|bell)(\s|$)/.test(this.className)) {
          this.className = this.className.replace(/bi-(house-door|people|bookmark|person|chat-dots|bell)(\s|$)/, 'bi-$1-fill$2');
        }
      });
    });
  }
  $(document).on('click', '.app-sidebar a.app-nav-link, .app-mobile-drawer a.app-nav-link', function (e) {
    var href = this.getAttribute('href');
    // Ordinary left-clicks to another page only (not new-tab clicks, not Logout).
    if (!href || href === '#' || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) { return; }
    if (/logout/.test(href)) { return; }
    setActive(this);
  });
})(window.jQuery);

/* -----------------------------------------------------------
   Right sidebar "Top stories": "Show more" opens the extra
   stories in place; "Show less" folds them away again.
   ----------------------------------------------------------- */
(function () {
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.js-top-stories-toggle');
    if (!btn) { return; }
    var card = btn.closest('.js-top-stories');
    var open = !card.classList.contains('is-expanded');
    card.classList.toggle('is-expanded', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    btn.querySelector('.js-top-stories-label').textContent = open ? 'Show less' : 'Show more';
  });
})();

// =====================================================================
// Repost & Quote (X-style)
//
// The repost icon on every post card (.js-repost-btn, _post_card.html)
// opens a small menu beside it: "Repost" (or "Undo repost") and
// "Quote". Repost / undo is one POST to /post/<id>/repost/; the icon's
// state and the count come back from the server (the database is the
// source of truth) and every copy of that post on the page follows.
// "Quote" opens the shared quote composer (#quoteComposerModal,
// base.html) with the post embedded; posting it creates a new post
// (/post/<id>/quote/) that's dropped into the feed without a reload.
// =====================================================================
(function ($) {
  if (!$) { return; }

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  function toast(text, tag) { if (typeof window.showToast === 'function') { window.showToast(text, tag); } }
  function postForm(url, data) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin', body: data,
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrf() },
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, error: 'Something went wrong. Please try again.' }; })
        .then(function (body) { if (!r.ok || !body.ok) { throw new Error(body.error || 'Something went wrong. Please try again.'); } return body; });
    });
  }
  var quoteModalEl = document.getElementById('quoteComposerModal');
  var me = quoteModalEl ? { id: quoteModalEl.dataset.meId, url: quoteModalEl.dataset.meUrl } : {};
  function currentTab() { return new URLSearchParams(location.search).get('tab'); }
  function onOwnProfile() { return /^\/profile\/?$/.test(location.pathname) || (!!me.url && location.pathname === me.url); }

  // ---------------- every copy of a post follows the server ----------------
  function applyRepostState(postId, reposted, count) {
    document.querySelectorAll('.js-repost-btn[data-post-id="' + postId + '"]').forEach(function (btn) {
      btn.classList.toggle('reposted', reposted);
      btn.dataset.reposted = reposted ? '1' : '0';
      btn.title = reposted ? 'Undo repost or quote' : 'Repost or quote';
      var n = btn.querySelector('.js-repost-count');
      if (n) { n.textContent = count; n.hidden = !count; }
    });
  }
  // "You reposted" above the card: added when you repost, removed when you undo.
  function applyRepostLabel(postId, reposted) {
    document.querySelectorAll('.post-card[data-post-id="' + postId + '"]').forEach(function (card) {
      var label = card.querySelector(':scope > .js-repost-label');
      if (reposted && !label) {
        label = document.createElement('div');
        label.className = 'post-card-repost-label js-repost-label is-new';
        label.dataset.reposterId = me.id;
        label.innerHTML = '<i class="bi bi-repeat"></i> <a href="' + me.url + '">You</a> reposted';
        card.insertBefore(label, card.firstChild);
      } else if (!reposted && label && label.dataset.reposterId === String(me.id)) {
        // On your own profile's Repost tab the post itself leaves the list
        // (unless it's a quote you wrote — that stays, it's yours).
        var myQuote = card.dataset.authorUrl === me.url && card.querySelector(':scope > .quote-embed');
        // (Your Posts tab shows your reposts too; someone else's post leaves it.)
        var mine = card.dataset.authorUrl === me.url;
        var tab = currentTab() || 'posts';
        var listed = (tab === 'repost' && !myQuote) || (tab === 'posts' && !mine);
        if (onOwnProfile() && listed && card.closest('.profile-empty-state')) {
          card.classList.add('is-leaving');
          setTimeout(function () { card.remove(); }, 220);
        } else {
          label.remove();
        }
      }
    });
  }

  // ---------------- the menu ----------------
  var menu = null, menuFor = null, closeTimer = null;
  function buildMenu() {
    menu = document.createElement('div');
    menu.className = 'repost-menu';
    menu.setAttribute('role', 'menu');
    menu.innerHTML =
      '<button type="button" class="repost-menu-item js-repost-do" role="menuitem"><i class="bi bi-repeat"></i><span class="js-repost-do-label">Repost</span></button>' +
      '<button type="button" class="repost-menu-item js-quote-do" role="menuitem"><i class="bi bi-quote"></i><span>Quote</span></button>';
    document.body.appendChild(menu);
  }
  function openMenu(btn) {
    if (!menu) { buildMenu(); }
    clearTimeout(closeTimer);
    if (menuFor && menuFor !== btn) { menuFor.setAttribute('aria-expanded', 'false'); }
    menuFor = btn;
    var reposted = btn.dataset.reposted === '1';
    menu.querySelector('.js-repost-do-label').textContent = reposted ? 'Undo repost' : 'Repost';
    menu.querySelector('.js-repost-do').classList.toggle('is-undo', reposted);
    // Measure, then place it under the icon (or above, if there's no room),
    // kept inside the screen on narrow phones.
    menu.classList.remove('open', 'above');
    menu.style.display = 'block';
    menu.style.left = '0px'; menu.style.top = '0px';
    var r = btn.getBoundingClientRect();
    var mw = menu.offsetWidth, mh = menu.offsetHeight, gap = 6, pad = 8;
    var left = Math.min(Math.max(pad, r.left + r.width / 2 - mw / 2), window.innerWidth - mw - pad);
    var top = r.bottom + gap;
    if (top + mh > window.innerHeight - pad && r.top - gap - mh > pad) { top = r.top - gap - mh; menu.classList.add('above'); }
    menu.style.left = Math.round(left) + 'px';
    menu.style.top = Math.round(top) + 'px';
    menu.style.transformOrigin = (r.left + r.width / 2 - left) + 'px ' + (menu.classList.contains('above') ? 'bottom' : 'top');
    void menu.offsetWidth;
    menu.classList.add('open');
    menuOpenedAt = Date.now();
    btn.setAttribute('aria-expanded', 'true');
    menu.querySelector('.repost-menu-item').focus({ preventScroll: true });
  }
  function closeMenu(returnFocus) {
    if (!menu || !menu.classList.contains('open')) { return; }
    menu.classList.remove('open');
    var btn = menuFor;
    if (btn) { btn.setAttribute('aria-expanded', 'false'); if (returnFocus) { btn.focus({ preventScroll: true }); } }
    closeTimer = setTimeout(function () { if (!menu.classList.contains('open')) { menu.style.display = 'none'; } }, 180);
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.js-repost-btn');
    if (btn) {
      e.preventDefault();
      if (menu && menu.classList.contains('open') && menuFor === btn) { closeMenu(); } else { openMenu(btn); }
      return;
    }
    if (menu && menu.classList.contains('open') && !menu.contains(e.target)) { closeMenu(); }
  });
  document.addEventListener('keydown', function (e) {
    if (!menu || !menu.classList.contains('open')) { return; }
    if (e.key === 'Escape') { e.preventDefault(); closeMenu(true); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      var items = Array.prototype.slice.call(menu.querySelectorAll('.repost-menu-item'));
      var i = items.indexOf(document.activeElement);
      items[(i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length].focus();
    }
  });
  // Scrolling closes the menu — but not the tiny nudge the browser can
  // make in the instant the menu opens (e.g. tapping a post that's still
  // gliding into place), which used to shut it straight away.
  var menuOpenedAt = 0;
  window.addEventListener('scroll', function () { if (Date.now() - menuOpenedAt > 300) { closeMenu(); } }, { capture: true, passive: true });
  window.addEventListener('resize', function () { closeMenu(); });
  document.addEventListener('uc:page', function () { closeMenu(); });

  // ---------------- Opening a post (X-style) ----------------
  // Tapping a post in a feed — its text or any empty part of the card —
  // opens its Post Details page. Links, buttons, menus, photos, videos,
  // quoted posts and selected text keep doing their own thing.
  var NOT_A_POST_TAP = 'a, button, input, textarea, select, label, video, audio, img.js-lightbox-img, .dropdown, .dropdown-menu, .quote-embed, .js-liked-by-slot, .post-card-media-item.is-small';
  document.addEventListener('click', function (e) {
    var card = e.target.closest('.post-card[data-post-url]');
    if (!card || card.classList.contains('post-detail') || card.closest('#commentsModal') || card.classList.contains('profile-reply-card')) { return; }
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) { return; }
    if (e.target.closest(NOT_A_POST_TAP)) { return; }
    var sel = window.getSelection && window.getSelection();
    if (sel && String(sel).length) { return; }   // they were selecting text, not tapping
    var url = card.getAttribute('data-post-url');
    if (window.UC && UC.navigate) { UC.navigate(url); } else { location.href = url; }
  });

  // Post Details: the post's time in the viewer's own time zone,
  // "4:05 pm · 13 Oct 26" (the server writes it in UTC as a fallback).
  var MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function localizePostTimes(root) {
    (root || document).querySelectorAll('time.js-local-time[datetime]').forEach(function (el) {
      var d = new Date(el.getAttribute('datetime'));
      if (isNaN(d)) { return; }
      var h = d.getHours(), m = d.getMinutes();
      el.textContent = (h % 12 || 12) + ':' + (m < 10 ? '0' : '') + m + ' ' + (h < 12 ? 'am' : 'pm') +
        ' · ' + d.getDate() + ' ' + MONTHS_SHORT[d.getMonth()] + ' ' + String(d.getFullYear()).slice(2);
    });
  }
  localizePostTimes();
  document.addEventListener('uc:page', function () { localizePostTimes(); });

  // ---------------- A quoted post opens when clicked ----------------
  // (except on its video, which plays right there, or a link inside it)
  function openQuoted(box) {
    var href = box.dataset.href;
    if (window.UC && UC.navigate) { UC.navigate(href); } else { location.href = href; }
  }
  document.addEventListener('click', function (e) {
    var box = e.target.closest('.quote-embed[data-href]');
    if (!box || e.defaultPrevented || e.target.closest('video, a, button')) { return; }
    openQuoted(box);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && e.target.matches && e.target.matches('.quote-embed[data-href]')) { openQuoted(e.target); }
  });

  // ---------------- Repost / Undo repost ----------------
  document.addEventListener('click', function (e) {
    var item = e.target.closest('.js-repost-do');
    if (!item || !menuFor) { return; }
    var btn = menuFor;
    var postId = btn.dataset.postId;
    var undo = btn.dataset.reposted === '1';
    closeMenu(true);
    if (btn.classList.contains('is-busy')) { return; }
    btn.classList.add('is-busy');
    var data = new FormData();
    data.append('action', undo ? 'undo' : 'repost');
    postForm('/post/' + postId + '/repost/', data).then(function (res) {
      applyRepostState(postId, res.reposted, res.reposts_count);
      applyRepostLabel(postId, res.reposted);
      if (res.reposted) {
        document.querySelectorAll('.js-repost-btn[data-post-id="' + postId + '"]').forEach(function (b) {
          b.classList.remove('repost-pop'); void b.offsetWidth; b.classList.add('repost-pop');
        });
      }
      toast(res.message);
    }).catch(function (err) {
      toast(err.message, 'error');
    }).then(function () { btn.classList.remove('is-busy'); });
  });
  document.addEventListener('animationend', function (e) {
    if (e.target.classList && e.target.classList.contains('repost-pop')) { e.target.classList.remove('repost-pop'); }
  });

  // ---------------- Quote composer ----------------
  if (!quoteModalEl) { return; }
  var form = quoteModalEl.querySelector('.js-quote-form');
  var text = quoteModalEl.querySelector('.js-quote-text');
  var preview = quoteModalEl.querySelector('.js-quote-preview');
  var counter = quoteModalEl.querySelector('.js-quote-counter');
  var submit = quoteModalEl.querySelector('.js-quote-submit');
  var errorEl = quoteModalEl.querySelector('.js-quote-error');
  var MAX = parseInt(text.getAttribute('maxlength'), 10) || 500;
  var quotingId = null, previewReady = false, sending = false;

  var mediaInput = quoteModalEl.querySelector('.js-quote-media-input');
  var mediaGrid = quoteModalEl.querySelector('.js-new-media-grid');
  var videoBox = quoteModalEl.querySelector('.js-compose-video');

  function showError(msg) { errorEl.textContent = msg || ''; errorEl.hidden = !msg; }
  // Photos/videos picked for the quote — the composer code above keeps
  // this list on the form (same as the main post composer).
  function pendingMedia() { return $(form).data('pendingMediaFiles') || []; }
  function refresh() {
    var len = text.value.length, trimmed = text.value.trim().length;
    counter.textContent = len + ' / ' + MAX;
    counter.classList.toggle('is-near', len > MAX - 50 && len <= MAX);
    counter.classList.toggle('is-over', len > MAX);
    submit.disabled = sending || !previewReady || (!trimmed && !pendingMedia().length) || len > MAX;
  }
  // A fresh composer every time: no leftover photos, video, thumbnail or upload.
  function resetMedia() {
    $(form).data('pendingMediaFiles', []);
    mediaInput.value = '';
    mediaGrid.innerHTML = '';
    mediaGrid.classList.remove('count-1', 'count-2', 'count-3', 'count-4');
    delete form.dataset.ikReady;
    form.classList.remove('is-uploading');
    if (videoBox) {
      videoBox.querySelectorAll('.js-ik-video-id, .js-ik-thumb-id').forEach(function (i) { i.value = ''; });
      var thumbInput = videoBox.querySelector('.js-compose-thumb-input');
      if (thumbInput) { thumbInput.value = ''; }
      var preview = videoBox.querySelector('.js-compose-thumb-preview');
      if (preview) { preview.removeAttribute('src'); preview.hidden = true; }
      var row = videoBox.querySelector('.js-compose-thumb');
      if (row) { row.hidden = true; }
      var progress = videoBox.querySelector('.js-compose-progress');
      if (progress) { progress.hidden = true; }
    }
  }
  // Adding or removing a photo/video updates the Quote button.
  mediaInput.addEventListener('change', function () { showError(''); setTimeout(refresh, 0); });
  form.addEventListener('click', function (e) {
    if (e.target.closest('.compose-remove-image')) { setTimeout(refresh, 0); }
  });
  function modal() { return window.bootstrap.Modal.getOrCreateInstance(quoteModalEl); }

  document.addEventListener('click', function (e) {
    var item = e.target.closest('.js-quote-do');
    if (!item || !menuFor) { return; }
    quotingId = menuFor.dataset.postId;
    closeMenu();
    text.value = '';
    text.style.height = '';
    resetMedia();
    showError('');
    previewReady = false;
    sending = false;
    submit.textContent = 'Quote';
    preview.innerHTML = '<div class="quote-embed quote-embed-loading"><span class="spinner-border spinner-border-sm"></span> Loading post…</div>';
    refresh();
    modal().show();
    var forId = quotingId;
    fetch('/post/' + forId + '/quote/preview/', { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { if (!r.ok) { throw new Error(); } return r.text(); })
      .then(function (html) {
        if (forId !== quotingId) { return; }
        preview.innerHTML = html;
        previewReady = true;
        refresh();
      })
      .catch(function () {
        if (forId !== quotingId) { return; }
        preview.innerHTML = '<div class="quote-embed quote-embed-gone"><i class="bi bi-eye-slash"></i> This post is unavailable.</div>';
        showError("You can't quote this post right now.");
      });
  });
  quoteModalEl.addEventListener('shown.bs.modal', function () { text.focus(); });
  quoteModalEl.addEventListener('hidden.bs.modal', function () { quotingId = null; preview.innerHTML = ''; });
  function grow() { text.style.height = 'auto'; text.style.height = Math.min(text.scrollHeight + 2, window.innerHeight * 0.4) + 'px'; }
  text.addEventListener('input', function () { showError(''); refresh(); grow(); });
  text.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !submit.disabled) { e.preventDefault(); form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', { cancelable: true })); }
  });

  // Where a new quote shows up straight away: your Home feed (For You /
  // Following), or your own profile's Posts / Repost tab.
  function dropIntoFeed(html) {
    var path = location.pathname, tab = currentTab();
    var ownProfile = onOwnProfile();
    var targets = [];
    if (/^\/home\/?$/.test(path) && tab !== 'media') {
      var tabs = document.querySelector('.app-main .feed-tabs');
      if (tabs) { targets.push({ after: tabs }); }
    } else if (ownProfile && (!tab || tab === 'posts' || tab === 'repost')) {
      document.querySelectorAll('.app-main .profile-empty-state').forEach(function (list) { targets.push({ into: list }); });
    }
    targets.forEach(function (t) {
      var holder = document.createElement('div');
      holder.innerHTML = html.trim();
      var card = holder.firstElementChild;
      card.classList.add('post-card-new');
      if (t.after) {
        var empty = t.after.parentNode.querySelector('.feed-tabs ~ .center-card');
        if (empty) { empty.remove(); }
        t.after.insertAdjacentElement('afterend', card);
      } else {
        var none = t.into.querySelector(':scope > .center-card');
        if (none) { none.remove(); }
        var note = t.into.querySelector(':scope > .profile-private-note');
        if (note) { note.insertAdjacentElement('afterend', card); } else { t.into.insertBefore(card, t.into.firstChild); }
      }
    });
    return targets.length > 0;
  }

  function busy(label) {
    sending = true; refresh();
    submit.innerHTML = '<span class="spinner-border spinner-border-sm"></span> ' + label;
  }
  function idle() {
    sending = false;
    submit.textContent = 'Quote';
    refresh();
  }

  form.addEventListener('submit', function (e) {
    // A video going to ImageKit first: video-upload.js has taken this
    // submit (and shows the progress); it fires uc:ik-uploaded when done.
    if (e.defaultPrevented) {
      if (quotingId && !sending) { showError(''); busy('Uploading'); }
      return;
    }
    e.preventDefault();
    if (submit.disabled || !quotingId) { return; }
    if (!text.value.trim() && !pendingMedia().length) { showError('Add a comment, a photo or a video to quote this post.'); return; }
    send();
  });
  form.addEventListener('uc:ik-uploaded', function () { send(); });
  form.addEventListener('uc:ik-failed', function () { idle(); });

  function send() {
    if (!quotingId) { return; }
    busy('Posting');
    // Your words, photos (or a video, or its ImageKit ID) and thumbnail —
    // exactly what the form holds, checked again by the server.
    var data = new FormData(form);
    data.set('content', text.value.trim());
    var originalId = quotingId;
    postForm('/post/' + originalId + '/quote/', data).then(function (res) {
      applyRepostState(res.original_id, document.querySelector('.js-repost-btn[data-post-id="' + res.original_id + '"]') ? document.querySelector('.js-repost-btn[data-post-id="' + res.original_id + '"]').dataset.reposted === '1' : false, res.reposts_count);
      var shown = dropIntoFeed(res.html);
      modal().hide();
      toast(shown ? res.message : res.message + ' It’s on your profile.');
      resetMedia();
    }).catch(function (err) {
      showError(err.message);
    }).then(function () {
      idle();
    });
  }
})(window.jQuery);

/* ---------------------------------------------------------------
   "See more" on long posts (app.css cuts feed posts at 5 lines).
   A button is added only under posts whose text really is longer;
   tapping it shows the whole post in place. Re-checked when posts
   are added to the page and when the screen size changes.
   --------------------------------------------------------------- */
(function () {
  'use strict';
  var SEL = '.post-card:not(.post-detail):not(.profile-reply-card) > .post-card-text';

  function check(text) {
    if (text.classList.contains('is-expanded')) { return; }
    var btn = text.nextElementSibling && text.nextElementSibling.classList.contains('js-see-more') ? text.nextElementSibling : null;
    if (!text.clientHeight) { return; }                 // hidden right now (e.g. the phone video feed) — check later
    var long = text.scrollHeight > text.clientHeight + 2;
    if (long && !btn) {
      btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'post-card-see-more js-see-more';
      btn.textContent = 'See more';
      text.insertAdjacentElement('afterend', btn);
    }
    if (btn) { btn.hidden = !long; }
  }
  function scan(root) {
    (root && root.querySelectorAll ? root : document).querySelectorAll(SEL).forEach(check);
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.js-see-more');
    if (!btn) { return; }
    e.preventDefault();
    var text = btn.previousElementSibling;
    if (text) { text.classList.add('is-expanded'); }
    btn.remove();
  });

  var queued = false;
  function later() {
    if (queued) { return; }
    queued = true;
    requestAnimationFrame(function () { queued = false; scan(); });
  }
  if ('MutationObserver' in window) {
    new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        if (records[i].addedNodes.length) { later(); return; }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }
  window.addEventListener('resize', later);
  document.addEventListener('uc:page', later);
  if (document.fonts && document.fonts.ready) { document.fonts.ready.then(later); }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', later); } else { later(); }
})();


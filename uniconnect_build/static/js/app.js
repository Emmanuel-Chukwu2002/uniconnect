// Clears a field's validation error the moment the student starts
// correcting it, instead of leaving the old error showing until the
// next full page reload/submission. Searches up to the field's crispy
// wrapper (div_id_<field>) rather than assuming the error is a direct
// sibling, since the password show/hide toggle below wraps password
// inputs in an extra div.
$(function () {
  $(document).on('input change', '.is-invalid', function () {
    $(this).removeClass('is-invalid');
    $(this).closest('[id^="div_id_"]').find('.invalid-feedback').remove();
  });

  // Password show/hide toggle (Bootstrap Icons eye / eye-slash)
  $('input[type="password"]').each(function () {
    var $input = $(this);
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
  });

  // -----------------------------------------------------------
  // Light / dark mode toggle (persisted in localStorage)
  // -----------------------------------------------------------
  var modeToggle = document.getElementById('modeToggle');
  var modeText = document.getElementById('modeText');

  function syncModeLabel() {
    if (modeText) {
      modeText.textContent = document.body.classList.contains('light-mode') ? 'Dark Mode' : 'Light Mode';
    }
  }
  syncModeLabel();

  if (modeToggle) {
    modeToggle.addEventListener('click', function () {
      document.body.classList.toggle('light-mode');
      var isLight = document.body.classList.contains('light-mode');
      localStorage.setItem('theme', isLight ? 'light' : 'dark');
      syncModeLabel();
    });
  }

  // -----------------------------------------------------------
  // Follow / unfollow toggle (Who to follow widget)
  // -----------------------------------------------------------
  $(document).on('click', '.follow-btn', function () {
    var $btn = $(this);
    var userId = $btn.data('user-id');
    $.ajax({
      url: '/follow/' + userId + '/',
      type: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') },
      success: function (data) {
        if (data.following) {
          $btn.text('Following').removeClass('btn-primary').addClass('btn-outline-secondary');
        } else {
          $btn.text('Follow').removeClass('btn-outline-secondary').addClass('btn-primary');
        }
      }
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
});

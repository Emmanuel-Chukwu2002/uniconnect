/* =====================================================================
   UniConnect Messages — Communities
   New community, new group in a community, joining a group, adding
   members (admins).
   ===================================================================== */
(function () {
  'use strict';
  var WA = window.WA;
  var modalEl = document.getElementById('waFormModal');
  if (!WA || !modalEl) { return; }
  var form = modalEl.querySelector('.js-wa-form-modal');
  var submitUrl = null;

  function openForm(title, button, url) {
    submitUrl = url;
    form.reset();
    modalEl.querySelector('.js-wa-modal-title').textContent = title;
    modalEl.querySelector('.js-wa-modal-submit').textContent = button;
    modalEl.querySelector('.js-wa-form-error').hidden = true;
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
    setTimeout(function () { form.querySelector('input[name="name"]').focus(); }, 300);
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var err = modalEl.querySelector('.js-wa-form-error');
    WA.post(submitUrl, new FormData(form)).then(function (res) {
      bootstrap.Modal.getOrCreateInstance(modalEl).hide();
      if (res.url) { WA.navigate(res.url); }
    }).catch(function (ex) { err.textContent = ex.message; err.hidden = false; });
  });

  document.addEventListener('click', function (e) {
    var t = e.target;
    if (t.closest('.js-wa-new-community')) {
      openForm('New community', 'Create community', '/messages/communities/new/');
    } else if (t.closest('.js-wa-community-new-group')) {
      openForm('New group in this community', 'Create group', t.closest('.js-wa-community-new-group').getAttribute('data-url'));
    } else if (t.closest('.js-wa-join-group')) {
      var btn = t.closest('.js-wa-join-group');
      btn.disabled = true;
      WA.post(btn.getAttribute('data-url'), {}).then(function (res) { WA.navigate(res.url); })
        .catch(function (ex) { btn.disabled = false; WA.toast(ex.message, 'error'); });
    } else if (t.closest('.js-wa-community-add')) {
      var url = t.closest('.js-wa-community-add').getAttribute('data-url');
      WA.people.open('members', {
        title: 'Add members',
        onConfirm: function (ids) {
          var fd = new FormData();
          ids.forEach(function (id) { fd.append('members', id); });
          WA.post(url, fd).then(function (res) {
            WA.people.close();
            WA.toast(res.added ? res.added + ' added to the community.' : 'They were already members.');
            WA.navigate(res.url + '?r=' + Date.now());
          }).catch(function (ex) { WA.toast(ex.message, 'error'); });
        },
      });
    }
  });
})();

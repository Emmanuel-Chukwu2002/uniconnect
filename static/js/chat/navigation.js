/* =====================================================================
   UniConnect Messages — moving between tabs and chats without a full
   page reload (so the WebSocket stays connected).

   Links marked data-wa-nav are fetched in the background; the new
   page's list pane / main pane are swapped in, the address bar is
   updated (history.pushState) and Back/Forward work. Every page is
   still a real URL, so refreshing or opening in a new tab works too.
   ===================================================================== */
(function () {
  'use strict';
  var WA = window.WA;
  var app = document.getElementById('waApp');
  if (!WA || !app) { return; }

  var busy = false;

  function isMessagesUrl(url) {
    return url.origin === location.origin && url.pathname.indexOf('/messages/') === 0;
  }

  function listKind(root) {
    var a = root.querySelector('#waApp');
    var rows = root.querySelector('#waListPane .js-wa-rows');
    var community = root.querySelector('#waListPane .wa-community-hero');
    return (a ? a.getAttribute('data-tab') : '') + (rows ? (rows.hasAttribute('data-archived-list') ? ':archived' : ':list') : '') +
      (community ? ':' + location.pathname : '');
  }

  function swap(doc, url, push) {
    // Pages that need extra scripts on load (Updates uses the Stories
    // viewer from app.js) are opened normally the first time.
    if (doc.getElementById('storiesData') && !window.UniStories) { location.href = url; return; }

    var newApp = doc.getElementById('waApp');
    if (!newApp) { location.href = url; return; }
    var keepList = listKind(document) === listKind(doc) && listKind(doc).indexOf(':list') > -1;

    WA.emit('page:leave', {});
    if (!keepList) {
      document.getElementById('waListPane').innerHTML = doc.getElementById('waListPane').innerHTML;
    }
    document.getElementById('waMainPane').innerHTML = doc.getElementById('waMainPane').innerHTML;
    document.getElementById('waPageData').innerHTML = doc.getElementById('waPageData').innerHTML;

    var wasConversation = app.classList.contains('has-conversation');
    app.className = newApp.className;
    ['data-tab', 'data-conversation'].forEach(function (attr) { app.setAttribute(attr, newApp.getAttribute(attr) || ''); });
    // Bottom nav / rail active state and badges come from the new page.
    document.querySelectorAll('.js-wa-tab').forEach(function (tab) {
      tab.classList.toggle('is-active', tab.getAttribute('data-tab') === newApp.getAttribute('data-tab'));
    });
    if (app.classList.contains('has-conversation') && !wasConversation) { app.classList.add('is-entering'); }
    setTimeout(function () { app.classList.remove('is-entering'); }, 260);

    document.title = doc.title;
    if (push) { history.pushState({ wa: true }, '', url); }
    WA.refreshTimes(document.getElementById('waMainPane'));
    if (!keepList) { WA.refreshTimes(document.getElementById('waListPane')); }
    WA.emit('page', { url: url, keepList: keepList });
  }

  function go(url, push) {
    if (busy) { return; }
    busy = true;
    app.classList.add('is-loading');
    fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) {
        if (r.redirected && !isMessagesUrl(new URL(r.url))) { location.href = r.url; return null; }
        return r.text();
      })
      .then(function (html) {
        if (html === null) { return; }
        swap(new DOMParser().parseFromString(html, 'text/html'), url, push);
      })
      .catch(function () { location.href = url; })
      .then(function () { busy = false; app.classList.remove('is-loading'); });
  }
  WA.navigate = function (url) { go(url, true); };

  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[data-wa-nav]');
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return; }
    var url = new URL(a.href, location.href);
    if (!isMessagesUrl(url)) { return; }
    e.preventDefault();
    // Close any open sheet/dropdown first.
    WA.emit('nav:click', {});
    if (url.pathname === location.pathname && url.search === location.search) { return; }
    go(url.href, true);
  });

  window.addEventListener('popstate', function () {
    if (isMessagesUrl(new URL(location.href))) { go(location.href, false); }
  });
  history.replaceState({ wa: true }, '', location.href);
})();

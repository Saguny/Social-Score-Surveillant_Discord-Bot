(function () {
  'use strict';

  /* ── Active nav state ──────────────────────────────────────────────────── */
  var path = window.location.pathname.replace(/\/+$/, '') || '/social-credit';
  var links = document.querySelectorAll('[data-nav]');
  var best = null;

  links.forEach(function (a) {
    var href = a.getAttribute('data-nav').replace(/\/+$/, '');
    if (path === href || (href !== '/social-credit' && path.indexOf(href + '/') === 0)) {
      if (!best || href.length > best.length) best = href;
    }
  });
  links.forEach(function (a) {
    if (best && a.getAttribute('data-nav').replace(/\/+$/, '') === best) {
      a.classList.add('active');
      a.setAttribute('aria-current', 'page');
    }
  });

  /* ── Mobile drawer ─────────────────────────────────────────────────────── */
  var sidebar  = document.getElementById('nav-sidebar');
  var backdrop = document.getElementById('nav-backdrop');
  var ham      = document.getElementById('nav-hamburger');
  var closeBtn = document.getElementById('sidebar-close');
  var lastFocus = null;

  var FOCUSABLE = 'a[href],button:not([disabled]),select,input,textarea,[tabindex]:not([tabindex="-1"])';

  function openDrawer() {
    if (!sidebar) return;
    lastFocus = document.activeElement;
    sidebar.classList.add('open');
    if (backdrop) backdrop.classList.add('open');
    sidebar.setAttribute('aria-hidden', 'false');
    if (ham) ham.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = 'hidden';
    var first = sidebar.querySelector(FOCUSABLE);
    if (first) first.focus();
  }

  function closeDrawer() {
    if (!sidebar || !sidebar.classList.contains('open')) return;
    sidebar.classList.remove('open');
    if (backdrop) backdrop.classList.remove('open');
    sidebar.setAttribute('aria-hidden', 'true');
    if (ham) ham.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  if (ham)      ham.addEventListener('click', openDrawer);
  if (backdrop) backdrop.addEventListener('click', closeDrawer);
  if (closeBtn) closeBtn.addEventListener('click', closeDrawer);

  if (sidebar) {
    sidebar.addEventListener('keydown', function (e) {
      if (e.key !== 'Tab') return;
      var items = Array.prototype.filter.call(
        sidebar.querySelectorAll(FOCUSABLE),
        function (el) { return el.offsetParent !== null; }
      );
      if (!items.length) return;
      var first = items[0];
      var last  = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
  }

  /* Growing past the mobile breakpoint must release the body scroll lock. */
  var mq = window.matchMedia('(min-width: 768px)');
  var onMq = function (e) { if (e.matches) closeDrawer(); };
  if (mq.addEventListener) mq.addEventListener('change', onMq);
  else if (mq.addListener) mq.addListener(onMq);

  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeDrawer(); });

  /* ── Pinned account footer ─────────────────────────────────────────────── */
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function paintAccount(suffix, user) {
    var root = document.getElementById('rail-account' + suffix);
    var av   = document.getElementById('rail-avatar' + suffix);
    var name = document.getElementById('rail-account-name' + suffix);
    var sub  = document.getElementById('rail-account-sub' + suffix);
    if (!root || !av || !name || !sub) return;

    if (user && user.logged_in !== false && user.username) {
      root.classList.add('is-in');
      root.setAttribute('title', '@' + user.username);
      av.innerHTML = user.avatar
        ? '<img src="https://cdn.discordapp.com/avatars/' + esc(user.id) + '/' + esc(user.avatar) +
          '.png?size=64" alt="" loading="lazy">'
        : esc(user.username.slice(0, 2).toUpperCase());
      name.textContent = '@' + user.username;
      name.removeAttribute('data-i18n');
      sub.textContent = t('MY ACCOUNT');
      sub.setAttribute('data-i18n', 'MY ACCOUNT');
    } else {
      root.classList.remove('is-in');
      name.textContent = t('MY ACCOUNT');
      name.setAttribute('data-i18n', 'MY ACCOUNT');
      sub.textContent = t('Not signed in');
      sub.setAttribute('data-i18n', 'Not signed in');
    }
  }

  var _railUser = null;

  function paintBoth() {
    paintAccount('', _railUser);
    paintAccount('-m', _railUser);
  }

  if (document.getElementById('rail-account')) {
    fetch('/api/discord/me', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (u) { _railUser = u; paintBoth(); })
      .catch(function () { /* stay logged-out */ });

    document.addEventListener('i18n:changed', paintBoth);
  }
})();

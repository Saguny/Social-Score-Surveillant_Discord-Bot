(function () {
  var sidebar  = document.getElementById('nav-sidebar');
  var backdrop = document.getElementById('nav-backdrop');
  var ham      = document.getElementById('nav-hamburger');
  var closeBtn = document.getElementById('sidebar-close');

  function _open() {
    if (!sidebar) return;
    sidebar.classList.add('open');
    backdrop && backdrop.classList.add('open');
    sidebar.setAttribute('aria-hidden', 'false');
    ham && ham.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = 'hidden';
  }
  function _close() {
    if (!sidebar) return;
    sidebar.classList.remove('open');
    backdrop && backdrop.classList.remove('open');
    sidebar.setAttribute('aria-hidden', 'true');
    ham && ham.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
  }

  if (ham)      ham.addEventListener('click', _open);
  if (backdrop) backdrop.addEventListener('click', _close);
  if (closeBtn) closeBtn.addEventListener('click', _close);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') _close(); });
})();

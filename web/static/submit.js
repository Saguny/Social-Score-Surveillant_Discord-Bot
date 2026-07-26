/* submit.js — character suggestion page */
(function () {
  'use strict';

  /* ── state ───────────────────────────────────────────────────────────────── */
  let _user        = null;   // { id, username, avatar }
  let _debounce    = null;
  let _sugDebounce = null;
  let _lastTitle   = null;
  let _currentData = null;
  let _sugItems    = [];
  let _sugIndex    = -1;
  let _sugSeq      = 0;

  const _DEBOUNCE_MS     = 380;
  const _SUGGEST_MS      = 200;
  const _SUGGEST_LIMIT   = 7;
  const _LOGIN_URL       = '/social-credit/auth/discord?next=/social-credit/submit';

  /* ── DOM refs ────────────────────────────────────────────────────────────── */
  const $input   = document.getElementById('wiki-input');
  const $result  = document.getElementById('result-area');
  const $bar     = document.getElementById('discord-bar');
  const $toast   = document.getElementById('toast');
  const $suggest = document.getElementById('wiki-suggest');
  const $combo   = document.getElementById('search-combo');
  const $clear   = document.getElementById('search-clear');
  const $urlFb   = document.getElementById('url-fallback');
  const $urlHint = document.getElementById('url-fallback-hint');
  const $steps   = document.getElementById('steps');

  /* ── helpers ─────────────────────────────────────────────────────────────── */
  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  let _toastTimer = null;
  function toast(msg, type) {
    $toast.textContent = msg;
    $toast.className = 'toast-msg show' + (type ? ' ' + type : '');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => { $toast.className = 'toast-msg'; }, 3400);
  }

  function _timeAgo(ts) {
    const diff = Math.floor(Date.now() / 1000) - ts;
    if (diff < 60)   return t('just now');
    if (diff < 3600) return `${Math.floor(diff / 60)}${t('m_ago')}`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}${t('h_ago')}`;
    const days = Math.floor(diff / 86400);
    return days === 1 ? `1${t('day_ago')}` : `${days}${t('days_ago')}`;
  }

  /* Steps: 1 find · 2 confirm · 3 review */
  function setStep(n) {
    if (!$steps) return;
    $steps.querySelectorAll('.step').forEach(el => {
      const s = parseInt(el.dataset.step, 10);
      el.classList.toggle('is-active', s === n);
      el.classList.toggle('is-done', s < n);
    });
  }

  /* ── Discord login bar ───────────────────────────────────────────────────── */
  function _avatarHtml(user, cls) {
    return user.avatar
      ? `<img class="${cls}" src="https://cdn.discordapp.com/avatars/${_esc(user.id)}/${_esc(user.avatar)}.png?size=64" alt="">`
      : `<div class="avatar-placeholder" style="background:var(--accent);display:flex;align-items:center;justify-content:center;font-size:.7rem;font-weight:700;color:var(--cream)">${_esc(user.username.slice(0, 2).toUpperCase())}</div>`;
  }

  function renderBar(user) {
    if (user && user.logged_in !== false && user.username) {
      $bar.innerHTML = `
        ${_avatarHtml(user, 'avatar')}
        <span class="uname">@${_esc(user.username)}</span>
        <span style="font-size:.75rem;color:var(--text-faint)">${_esc(t('You are logged in'))}</span>
        <a href="/social-credit/auth/discord/logout?next=/social-credit/submit" class="logout-link">${_esc(t('Log out'))}</a>`;
    } else {
      $bar.innerHTML = `
        <div class="avatar-placeholder"></div>
        <span style="font-size:.82rem;color:var(--text-muted)">${_esc(t('Log in to submit or vote on characters'))}</span>
        <a href="${_LOGIN_URL}" class="login-link">${_esc(t('Login with Discord'))}</a>`;
    }
  }

  function _loggedIn() {
    return !!(_user && _user.logged_in !== false && _user.username);
  }

  async function loadUser() {
    try {
      const r = await fetch('/api/discord/me', { credentials: 'same-origin' });
      if (r.ok) _user = await r.json();
    } catch (_) { /* stay logged out */ }
    renderBar(_user);
  }

  /* ── Wikipedia typeahead ─────────────────────────────────────────────────────
     Wikipedia's opensearch endpoint is CORS-enabled with origin=*, so the
     lookup runs straight from the browser with no server round-trip. */
  function _wikiLang() {
    const l = (document.documentElement.getAttribute('lang') || 'en').toLowerCase();
    if (l.indexOf('zh') === 0) return 'zh';
    if (l.indexOf('de') === 0) return 'de';
    return 'en';
  }

  function hideSuggest() {
    $suggest.hidden = true;
    $suggest.innerHTML = '';
    $combo.setAttribute('aria-expanded', 'false');
    _sugItems = [];
    _sugIndex = -1;
  }

  function renderSuggest(items) {
    _sugItems = items;
    _sugIndex = -1;
    if (!items.length) {
      $suggest.innerHTML = `<li class="suggest-empty">${_esc(t('No matches. Try their full name.'))}</li>`;
      $suggest.hidden = false;
      $combo.setAttribute('aria-expanded', 'true');
      return;
    }
    $suggest.innerHTML = items.map((it, i) => `
      <li class="suggest-item" role="option" id="sug-${i}" data-i="${i}" aria-selected="false">
        <span class="suggest-title">${_esc(it.title)}</span>
        <span class="suggest-desc">${_esc(it.desc || '')}</span>
      </li>`).join('');
    $suggest.hidden = false;
    $combo.setAttribute('aria-expanded', 'true');
  }

  function moveSuggest(delta) {
    if (!_sugItems.length) return;
    _sugIndex = (_sugIndex + delta + _sugItems.length) % _sugItems.length;
    $suggest.querySelectorAll('.suggest-item').forEach((el, i) => {
      const on = i === _sugIndex;
      el.classList.toggle('is-active', on);
      el.setAttribute('aria-selected', on ? 'true' : 'false');
      if (on) el.scrollIntoView({ block: 'nearest' });
    });
  }

  function pickSuggest(i) {
    const it = _sugItems[i];
    if (!it) return;
    hideSuggest();
    $input.value = it.title;
    clearTimeout(_debounce);
    doCheck(it.title);
  }

  async function fetchSuggest(term) {
    const seq = ++_sugSeq;
    const url = `https://${_wikiLang()}.wikipedia.org/w/api.php?action=opensearch&format=json&origin=*`
              + `&limit=${_SUGGEST_LIMIT}&namespace=0&search=${encodeURIComponent(term)}`;
    let data;
    try {
      const r = await fetch(url);
      data = await r.json();
    } catch (_) { return; }
    if (seq !== _sugSeq) return;            // a newer keystroke already won
    const titles = data[1] || [];
    const descs  = data[2] || [];
    renderSuggest(titles.map((title, i) => ({ title, desc: descs[i] || '' })));
  }

  /* ── preview card ────────────────────────────────────────────────────────── */
  function _wikiPreviewHtml(d) {
    const title   = d.wiki_title || d.title || '';
    /* Nothing to show without a title — rendering the shell anyway leaves an
       empty card, which is what the rejected-article state used to do. */
    if (!title) return '';
    const thumb   = d.thumbnail_url || '';
    const desc    = d.description || '';
    const extract = d.extract || '';
    const slug    = d.wiki_slug || '';
    const lang    = d.wiki_lang || 'en';
    const imgHtml = thumb
      ? `<img src="${_esc(thumb)}" alt="" loading="lazy">`
      : `<svg class="portrait-ico" aria-hidden="true"><use href="#i-user"/></svg>`;
    const descH   = desc ? `<div class="meta-desc">${_esc(desc)}</div>` : '';
    const extrH   = extract ? `<div class="meta-extract">${_esc(extract)}</div>` : '';
    const linkH   = slug
      ? `<a class="wiki-link" href="https://${_esc(lang)}.wikipedia.org/wiki/${encodeURIComponent(slug)}" target="_blank" rel="noopener">↗ ${_esc(t('Read on Wikipedia'))}</a>`
      : '';
    return `
      <div class="wiki-preview">
        <div class="portrait">${imgHtml}</div>
        <div class="meta">
          <div class="meta-name">${_esc(title)}</div>
          ${descH}${extrH}${linkH}
        </div>
      </div>`;
  }

  function _loginPromptHtml(message) {
    return `
      <div class="login-prompt">
        <div class="login-prompt-text">${_esc(message)}</div>
        <a class="login-prompt-btn" href="${_LOGIN_URL}">${_esc(t('Login with Discord'))}</a>
      </div>`;
  }

  function _nextStepsHtml() {
    return `
      <div class="next-steps">
        <div class="next-steps-title">${_esc(t('What happens next'))}</div>
        <div class="next-step"><span class="next-step-dot"></span><span>${_esc(t('Other citizens can upvote your suggestion on the wishlist.'))}</span></div>
        <div class="next-step"><span class="next-step-dot"></span><span>${_esc(t('Highly-supported requests move to the top of the admin review queue.'))}</span></div>
        <div class="next-step"><span class="next-step-dot"></span><span>${_esc(t('If approved, the character enters the gacha pool and your username is credited on their card.'))}</span></div>
      </div>`;
  }

  /* ── render states ───────────────────────────────────────────────────────── */
  function renderIdle() {
    setStep(1);
    $result.innerHTML = '';
  }

  function renderChecking() {
    $result.innerHTML = `
      <div class="feedback fb-checking">
        <span class="spin"></span>
        <span>${_esc(t('Looking up Wikipedia…'))}</span>
      </div>`;
  }

  function renderInGame(d) {
    setStep(3);
    $result.innerHTML = `
      <div class="feedback fb-ingame">
        <span>✓</span>
        <span><strong>${_esc(d.wiki_title || t('This character'))}</strong> ${_esc(t('is already in the game.'))}</span>
        <a class="fb-link" href="/social-credit/wishlist">${_esc(t('Browse the wishlist'))}</a>
      </div>
      ${_wikiPreviewHtml(d)}`;
  }

  function renderNotFound() {
    setStep(1);
    $result.innerHTML = `
      <div class="feedback fb-error">
        <span>✗</span>
        <span>${_esc(t('No Wikipedia article found. Check the spelling or try their full official name.'))}</span>
      </div>`;
  }

  function renderNotPerson(d) {
    setStep(1);
    $result.innerHTML = `
      <div class="feedback fb-error">
        <span>✗</span>
        <span>${_esc(t('That article is not about a real person. The gacha pool only accepts historical figures and public personalities.'))}</span>
      </div>
      ${_wikiPreviewHtml(d)}`;
  }

  function renderRequested(d) {
    setStep(3);
    const voted     = !!d.has_voted;
    const voteCount = d.vote_count || 0;
    const voters    = d.recent_voters || [];
    const btnLabel  = voted ? `✓ ${t('Supported')}` : `▲ ${t('Support')}`;
    const previewD  = {
      wiki_title: d.wiki_title, wiki_slug: d.wiki_slug || '',
      thumbnail_url: d.thumbnail_url || '', description: d.description || '',
      wiki_lang: d.wiki_lang || 'en',
    };
    const stack = voters.length
      ? `<div class="avatar-stack">${voters.slice(0, 4).map(v =>
          `<div class="av" title="@${_esc(v.discord_username || '')}">${_esc((v.discord_username || '').slice(0, 2).toUpperCase())}</div>`
        ).join('')}</div>`
      : '';

    $result.innerHTML = `
      ${_wikiPreviewHtml(previewD)}
      <div class="support-block">
        <div class="support-top">
          <div class="vote-count">
            <div class="num">${voteCount}</div>
            <div class="lbl">${_esc(voteCount === 1 ? t('supporter') : t('supporters'))}</div>
          </div>
          ${_loggedIn()
            ? `<button class="support-btn${voted ? ' voted' : ''}" id="support-btn" data-id="${_esc(d.request_id)}">${_esc(btnLabel)}</button>`
            : ''}
        </div>
        ${stack}
        <div class="support-footer">
          ${_esc(t('Already suggested'))} ${_esc(_timeAgo(d.submitted_at))} ${_esc(t('by'))} <b>@${_esc(d.submitted_by || '?')}</b>
        </div>
      </div>
      ${_loggedIn() ? '' : _loginPromptHtml(t('Log in to add your support to this suggestion.'))}
      ${_nextStepsHtml()}`;

    const btn = document.getElementById('support-btn');
    if (btn) btn.addEventListener('click', onSupportClick);
  }

  function renderValid(d) {
    setStep(2);
    if (!_loggedIn()) {
      $result.innerHTML = `
        ${_wikiPreviewHtml(d)}
        ${_loginPromptHtml(t('Log in with Discord to submit this character for review.'))}
        ${_nextStepsHtml()}`;
      return;
    }
    $result.innerHTML = `
      ${_wikiPreviewHtml(d)}
      <div class="tos-section" id="tos-box">
        <label class="tos-row">
          <input type="checkbox" class="tos-chk" id="tos-confirm">
          <span>${_esc(t('tos_single'))}</span>
        </label>
      </div>
      <button class="submit-btn" id="submit-btn" disabled>${_esc(t('SUBMIT FOR REVIEW'))}</button>
      <div class="submit-hint" id="submit-hint">${_esc(t('Tick the box to submit.'))}</div>
      ${_nextStepsHtml()}`;

    document.querySelectorAll('.tos-chk').forEach(c => c.addEventListener('change', updateSubmitBtn));
    document.getElementById('submit-btn').addEventListener('click', onSubmitClick);
    updateSubmitBtn();
  }

  function renderSubmitted(d) {
    setStep(3);
    $result.innerHTML = `
      <div class="feedback fb-valid">
        <span>✓</span>
        <span><strong>${_esc(d.wiki_title || '')}</strong> ${_esc(t('was submitted for review. Thank you!'))}</span>
        <a class="fb-link" href="/social-credit/wishlist">${_esc(t('See it on the wishlist'))}</a>
      </div>
      ${_nextStepsHtml()}`;
  }

  function updateSubmitBtn() {
    const all = Array.prototype.slice.call(document.querySelectorAll('.tos-chk'));
    const btn = document.getElementById('submit-btn');
    if (!btn) return;
    const ok = all.length > 0 && all.every(c => c.checked);
    btn.disabled = !ok;
    const hint = document.getElementById('submit-hint');
    if (hint) hint.textContent = ok
      ? t('Your username will be credited on the card if approved.')
      : t('Tick the box to submit.');
  }

  /* ── API calls ───────────────────────────────────────────────────────────── */
  async function doCheck(title) {
    renderChecking();
    _lastTitle = title;
    let data;
    try {
      const r = await fetch(`/api/requests/check?title=${encodeURIComponent(title)}`, { credentials: 'same-origin' });
      data = await r.json();
    } catch (_) {
      $result.innerHTML = `<div class="feedback fb-error"><span>✗</span><span>${_esc(t('Network error. Please try again.'))}</span></div>`;
      return;
    }
    if (_lastTitle !== title) return;   // stale response
    _currentData = data;
    renderState(data);
  }

  function renderState(data) {
    switch (data && data.state) {
      case 'in_game':    renderInGame(data);    break;
      case 'requested':  renderRequested(data); break;
      case 'valid':      renderValid(data);     break;
      case 'not_found':  renderNotFound();      break;
      case 'not_person': renderNotPerson(data); break;
      case 'submitted':  renderSubmitted(data); break;
      default:           renderIdle();
    }
  }

  async function onSupportClick(e) {
    const btn = e.currentTarget;
    if (!_loggedIn()) { toast(t('Log in to support characters'), 'error'); return; }
    btn.disabled = true;
    try {
      const r = await fetch('/api/requests/vote', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: parseInt(btn.dataset.id, 10) }),
      });
      const body = await r.json();
      if (!r.ok) { toast(body.error || t('Error'), 'error'); btn.disabled = false; return; }
      if (_lastTitle) doCheck(_lastTitle);
    } catch (_) {
      toast(t('Network error'), 'error');
      btn.disabled = false;
    }
  }

  async function onSubmitClick() {
    if (!_loggedIn()) return;
    if (!_currentData || _currentData.state !== 'valid') return;
    const btn = document.getElementById('submit-btn');
    const title = _currentData.wiki_title;
    if (btn) { btn.disabled = true; btn.textContent = t('SUBMITTING…'); }
    try {
      const r = await fetch('/api/requests/submit', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, tos_confirmed: true }),
      });
      const body = await r.json();
      if (!r.ok) {
        if (body.error === 'already_requested' || body.error === 'already_in_game') {
          if (_lastTitle) doCheck(_lastTitle);
          return;
        }
        toast(body.error || t('Submission failed'), 'error');
        if (btn) { btn.disabled = false; btn.textContent = t('SUBMIT FOR REVIEW'); }
        return;
      }
      toast(t('Submitted! Thank you for your suggestion.'), 'success');
      _currentData = { state: 'submitted', wiki_title: title };
      renderSubmitted(_currentData);
    } catch (_) {
      toast(t('Network error'), 'error');
      if (btn) { btn.disabled = false; btn.textContent = t('SUBMIT FOR REVIEW'); }
    }
  }

  /* ── input wiring ────────────────────────────────────────────────────────── */
  $input.addEventListener('input', () => {
    const title = $input.value.trim();
    $clear.hidden = !title;
    clearTimeout(_debounce);
    clearTimeout(_sugDebounce);
    if (!title) {
      hideSuggest();
      _lastTitle = null;
      _currentData = null;
      renderIdle();
      return;
    }
    _sugDebounce = setTimeout(() => fetchSuggest(title), _SUGGEST_MS);
    _debounce = setTimeout(() => doCheck(title), _DEBOUNCE_MS);
  });

  $input.addEventListener('keydown', (e) => {
    if ($suggest.hidden) return;
    if (e.key === 'ArrowDown')      { e.preventDefault(); moveSuggest(1); }
    else if (e.key === 'ArrowUp')   { e.preventDefault(); moveSuggest(-1); }
    else if (e.key === 'Enter' && _sugIndex >= 0) { e.preventDefault(); pickSuggest(_sugIndex); }
    else if (e.key === 'Escape')    { hideSuggest(); }
  });

  $suggest.addEventListener('mousedown', (e) => {
    const li = e.target.closest('.suggest-item');
    if (!li) return;
    e.preventDefault();                       // keep focus off the blur path
    pickSuggest(parseInt(li.dataset.i, 10));
  });

  $input.addEventListener('blur', () => { setTimeout(hideSuggest, 120); });

  $clear.addEventListener('click', () => {
    $input.value = '';
    $clear.hidden = true;
    hideSuggest();
    _lastTitle = null;
    _currentData = null;
    renderIdle();
    $input.focus();
  });

  /* URL fallback — extract the article title out of a pasted Wikipedia link */
  function _titleFromUrl(url) {
    const m = String(url).match(/\/wiki\/([^?#]+)/);
    if (!m) return null;
    try { return decodeURIComponent(m[1]).replace(/_/g, ' '); } catch (_) { return null; }
  }

  if ($urlFb) {
    $urlFb.addEventListener('input', () => {
      const val = $urlFb.value.trim();
      const setHint = (msg, err) => {
        if (!$urlHint) return;
        $urlHint.textContent = msg;
        $urlHint.classList.toggle('hint-error', !!err);
      };
      if (!val) { setHint(t("We'll pull the article title out of the link automatically."), false); return; }
      if (val.indexOf('wikipedia.org') === -1) { setHint(t('That is not a wikipedia.org link.'), true); return; }
      const title = _titleFromUrl(val);
      if (!title) { setHint(t("Couldn't find a /wiki/ path in that link."), true); return; }
      setHint(`${t('Searching for')} "${title}"…`, false);
      $input.value = title;
      $clear.hidden = false;
      hideSuggest();
      _lastTitle = null;
      _currentData = null;
      clearTimeout(_debounce);
      _debounce = setTimeout(() => doCheck(title), _DEBOUNCE_MS);
    });
  }

  /* ── init ────────────────────────────────────────────────────────────────── */
  loadUser();
  renderIdle();

  document.addEventListener('i18n:changed', () => {
    renderBar(_user);
    if (_currentData) renderState(_currentData);
  });

  document.addEventListener('click', async (e) => {
    const link = e.target.closest('a.logout-link');
    if (!link) return;
    e.preventDefault();
    await fetch('/social-credit/auth/discord/logout', { method: 'POST', credentials: 'same-origin' });
    window.location.href = '/social-credit/submit';
  });
})();

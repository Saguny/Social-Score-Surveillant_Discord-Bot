/* submit.js — character suggestion page */
(function () {
  'use strict';

  // ── state ──────────────────────────────────────────────────────────────────
  let _user        = null;   // { id, username, avatar }
  let _debounce    = null;
  let _lastTitle   = null;
  let _currentData = null;   // last /api/requests/check response
  const _DEBOUNCE_MS = 420;

  // ── DOM refs ───────────────────────────────────────────────────────────────
  const $input  = document.getElementById('wiki-input');
  const $result = document.getElementById('result-area');
  const $bar    = document.getElementById('discord-bar');
  const $toast  = document.getElementById('toast');

  // ── toast ──────────────────────────────────────────────────────────────────
  let _toastTimer = null;
  function toast(msg, type = '') {
    $toast.textContent = msg;
    $toast.className   = 'toast-msg show' + (type ? ' ' + type : '');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => { $toast.className = 'toast-msg'; }, 3200);
  }

  // ── Discord login bar ──────────────────────────────────────────────────────
  function renderBar(user) {
    if (user) {
      const av = user.avatar
        ? `<img class="avatar" src="https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png?size=64" alt="">`
        : `<div class="avatar-placeholder" style="background:var(--slate);display:flex;align-items:center;justify-content:center;font-size:.7rem;font-weight:700;color:var(--cream)">${user.username.slice(0,2).toUpperCase()}</div>`;
      $bar.innerHTML = `
        ${av}
        <span class="uname">@${_esc(user.username)}</span>
        <span style="font-size:.75rem;color:var(--grey)">You are logged in</span>
        <a href="/social-credit/auth/discord/logout?next=/social-credit/submit" class="logout-link">Log out</a>`;
    } else {
      $bar.innerHTML = `
        <div class="avatar-placeholder"></div>
        <span style="font-size:.82rem;color:var(--text-muted)">Log in to submit or vote on characters</span>
        <a href="/social-credit/auth/discord?next=/social-credit/submit" class="login-link">🔗 Login with Discord</a>`;
    }
  }

  async function loadUser() {
    try {
      const r = await fetch('/api/discord/me', { credentials: 'same-origin' });
      if (r.ok) _user = await r.json();
    } catch (_) {}
    renderBar(_user);
  }

  // ── helpers ────────────────────────────────────────────────────────────────
  function _esc(s) {
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _timeAgo(ts) {
    const diff = Math.floor(Date.now() / 1000) - ts;
    if (diff < 60)    return 'just now';
    if (diff < 3600)  return `${Math.floor(diff/60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
    const days = Math.floor(diff/86400);
    return days === 1 ? '1 day ago' : `${days} days ago`;
  }

  function _avatarStack(voters) {
    if (!voters || !voters.length) return '';
    const items = voters.slice(0, 4).map(v => {
      const name = v.discord_username || '';
      return `<div class="av" title="@${_esc(name)}">${_esc(name.slice(0,2).toUpperCase())}</div>`;
    }).join('');
    return `<div class="avatar-stack">${items}</div>`;
  }

  // Build Wikipedia preview card from server response fields.
  // Server returns: thumbnail_url, wiki_title, description, extract, wiki_slug
  // (valid state); for requested state: wiki_title, submitted_by etc. but no thumbnail.
  function _wikiPreviewHtml(d) {
    const title     = d.wiki_title || d.title || '';
    const thumb     = d.thumbnail_url || '';
    const desc      = d.description || '';
    const extract   = d.extract || '';
    const slug      = d.wiki_slug || '';
    const imgHtml   = thumb ? `<img src="${_esc(thumb)}" alt="" loading="lazy">` : '👤';
    const descHtml  = desc    ? `<div class="meta-desc">${_esc(desc)}</div>`    : '';
    const extrHtml  = extract ? `<div class="meta-extract">${_esc(extract)}</div>` : '';
    const wikiLang  = d.wiki_lang || 'en';
    const wikiLink  = slug
      ? `<a class="wiki-link" href="https://${wikiLang}.wikipedia.org/wiki/${encodeURIComponent(slug)}" target="_blank" rel="noopener">↗ Read on Wikipedia</a>`
      : '';
    return `
      <div class="wiki-preview">
        <div class="portrait">${imgHtml}</div>
        <div class="meta">
          <div class="meta-name">${_esc(title)}</div>
          ${descHtml}${extrHtml}
          ${wikiLink}
        </div>
      </div>`;
  }

  // ── render states ──────────────────────────────────────────────────────────
  function renderChecking() {
    $result.innerHTML = `
      <div class="feedback fb-checking">
        <span class="spin"></span>
        <span>Looking up Wikipedia…</span>
      </div>`;
  }

  function renderInGame(d) {
    $result.innerHTML = `
      <div class="feedback fb-ingame">
        ✓ <strong>${_esc(d.wiki_title || 'This character')}</strong> is already in the game!
      </div>`;
  }

  function _parseTitleFromUrl(url) {
    try {
      const match = url.match(/\/wiki\/([^?#]+)/);
      if (!match) return null;
      return decodeURIComponent(match[1]).replace(/_/g, ' ');
    } catch (_) { return null; }
  }

  function _urlFallbackHtml(label) {
    return `
      <div class="fallback-section">
        <div class="input-label" style="margin-top:.1rem">${label}</div>
        <input
          id="url-fallback"
          class="wiki-input"
          type="text"
          placeholder="Paste their Wikipedia URL — e.g. https://en.wikipedia.org/wiki/Xi_Jinping"
          autocomplete="off"
          spellcheck="false"
        >
        <div class="input-hint">We'll extract the article title and search again automatically.</div>
      </div>`;
  }

  function _bindUrlFallback() {
    const el = document.getElementById('url-fallback');
    if (!el) return;
    const hint = el.nextElementSibling;
    el.addEventListener('input', (e) => {
      const val = e.target.value.trim();
      if (!val) {
        if (hint) { hint.textContent = 'We\'ll extract the article title and search again automatically.'; hint.classList.remove('hint-error'); }
        return;
      }
      if (!val.includes('wikipedia.org')) {
        if (hint) { hint.textContent = '⚠ Please paste a link from wikipedia.org'; hint.classList.add('hint-error'); }
        return;
      }
      const title = _parseTitleFromUrl(val);
      if (!title) {
        if (hint) { hint.textContent = '⚠ Couldn\'t find a /wiki/ path in that URL — try copying the address bar URL directly.'; hint.classList.add('hint-error'); }
        return;
      }
      if (hint) { hint.textContent = `Searching for "${title}"…`; hint.classList.remove('hint-error'); }
      $input.value = title;
      _lastTitle   = null;
      _currentData = null;
      clearTimeout(_debounce);
      _debounce = setTimeout(() => doCheck(title), _DEBOUNCE_MS);
    });
  }

  function renderNotFound() {
    $result.innerHTML = `
      <div class="feedback fb-error">
        ✗ No Wikipedia article found with that exact title. Check spelling or try the full official name.
      </div>
      ${_urlFallbackHtml("Can't find them by title?")}`;
    _bindUrlFallback();
  }

  function renderNotPerson(d) {
    $result.innerHTML = `
      <div class="feedback fb-error">
        ✗ This Wikipedia article doesn't appear to be about a real person.
        The gacha pool only includes historical figures and public personalities.
      </div>
      ${_wikiPreviewHtml(d)}`;
  }

  function renderRequested(d) {
    // Server fields: request_id, wiki_title, submitted_by, submitted_at,
    //                vote_count, recent_voters, has_voted
    const voted     = d.has_voted || false;
    const voteCount = d.vote_count || 0;
    const voters    = d.recent_voters || [];
    const when      = _timeAgo(d.submitted_at);
    const btnLabel  = voted ? '✓ Supported' : '▲ Support';
    const btnCls    = voted ? 'support-btn voted' : 'support-btn';
    const btnDis    = !_user ? 'disabled title="Log in to support"' : '';
    // Build a minimal preview from whatever we have (no thumbnail in this response)
    const previewD  = { wiki_title: d.wiki_title, wiki_slug: d.wiki_slug || '', thumbnail_url: d.thumbnail_url || '', description: d.description || '' };
    $result.innerHTML = `
      ${_wikiPreviewHtml(previewD)}
      <div class="support-block">
        <div class="support-top">
          <div class="vote-count">
            <div class="num">${voteCount}</div>
            <div class="lbl">${voteCount === 1 ? 'supporter' : 'supporters'}</div>
          </div>
          <button class="${btnCls}" id="support-btn" data-id="${d.request_id}" ${btnDis}>
            ${btnLabel}
          </button>
        </div>
        ${_avatarStack(voters)}
        <div class="support-footer">
          First requested ${when} by <b>@${_esc(d.submitted_by || '?')}</b>
        </div>
      </div>
      ${_urlFallbackHtml('Not the right person? Paste their Wikipedia URL')}`;
    document.getElementById('support-btn')?.addEventListener('click', onSupportClick);
    _bindUrlFallback();
  }

  function renderValid(d) {
    $result.innerHTML = `
      ${_wikiPreviewHtml(d)}
      <div class="tos-section" id="tos-box">
        <div class="tos-title">Before submitting, confirm:</div>
        <label class="tos-row"><input type="checkbox" class="tos-chk"> This is a real historical or public figure, not fictional.</label>
        <label class="tos-row"><input type="checkbox" class="tos-chk"> The image I'm aware of is appropriate for a gacha card.</label>
        <label class="tos-row"><input type="checkbox" class="tos-chk"> I understand submissions may be rejected without explanation.</label>
        <label class="tos-row"><input type="checkbox" class="tos-chk"> I have not submitted this person before in the last 24 hours.</label>
      </div>
      <button class="submit-btn" id="submit-btn" disabled>SUBMIT FOR REVIEW</button>
      <div class="submit-hint" id="submit-hint">
        ${_user ? 'Check all boxes to submit.' : '<a href="/social-credit/auth/discord?next=/social-credit/submit">Log in with Discord</a> to submit.'}
      </div>
      ${_urlFallbackHtml('Not the right person? Paste their Wikipedia URL')}`;

    document.querySelectorAll('.tos-chk').forEach(chk => {
      chk.addEventListener('change', updateSubmitBtn);
    });
    document.getElementById('submit-btn')?.addEventListener('click', onSubmitClick);
    _bindUrlFallback();
    updateSubmitBtn();
  }

  function updateSubmitBtn() {
    if (!_user) return;
    const all = [...document.querySelectorAll('.tos-chk')];
    const btn = document.getElementById('submit-btn');
    if (!btn) return;
    const allChecked = all.length > 0 && all.every(c => c.checked);
    btn.disabled = !allChecked;
    const hint = document.getElementById('submit-hint');
    if (hint) hint.textContent = allChecked
      ? 'Your username will be credited on the card if approved.'
      : 'Check all boxes to submit.';
  }

  function onClearClick(e) {
    e.preventDefault();
    $input.value = '';
    $input.focus();
    $result.innerHTML = '';
    _lastTitle   = null;
    _currentData = null;
  }

  // ── API calls ──────────────────────────────────────────────────────────────
  async function doCheck(title) {
    renderChecking();
    _lastTitle = title;
    let data;
    try {
      const r = await fetch(`/api/requests/check?title=${encodeURIComponent(title)}`, {
        credentials: 'same-origin',
      });
      data = await r.json();
    } catch (_) {
      $result.innerHTML = `<div class="feedback fb-error">✗ Network error. Please try again.</div>`;
      return;
    }
    if (_lastTitle !== title) return; // stale
    _currentData = data;
    switch (data.state) {
      case 'in_game':    renderInGame(data);    break;
      case 'requested':  renderRequested(data); break;
      case 'valid':      renderValid(data);     break;
      case 'not_found':  renderNotFound();      break;
      case 'not_person': renderNotPerson(data); break;
      default:           $result.innerHTML = '';
    }
  }

  async function onSupportClick(e) {
    const btn = e.currentTarget;
    if (!_user) { toast('Log in to support characters', 'error'); return; }
    const reqId = parseInt(btn.dataset.id, 10);
    btn.disabled = true;
    try {
      const r = await fetch('/api/requests/vote', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: reqId }),
      });
      const body = await r.json();
      if (!r.ok) { toast(body.error || 'Error', 'error'); btn.disabled = false; return; }
      // re-fetch to get updated counts
      if (_lastTitle) doCheck(_lastTitle);
    } catch (_) {
      toast('Network error', 'error');
      btn.disabled = false;
    }
  }

  async function onSubmitClick() {
    if (!_user) return;
    if (!_currentData || _currentData.state !== 'valid') return;
    const btn = document.getElementById('submit-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'SUBMITTING…'; }
    try {
      const r = await fetch('/api/requests/submit', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title:         _currentData.wiki_title,
          tos_confirmed: true,
        }),
      });
      const body = await r.json();
      if (!r.ok) {
        if (body.error === 'already_requested' || body.error === 'already_in_game') {
          if (_lastTitle) doCheck(_lastTitle);
          return;
        }
        toast(body.error || 'Submission failed', 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'SUBMIT FOR REVIEW'; }
        return;
      }
      toast('Submitted! Thank you for your suggestion.', 'success');
      // re-check to flip to "requested" state
      if (_lastTitle) doCheck(_lastTitle);
    } catch (_) {
      toast('Network error', 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'SUBMIT FOR REVIEW'; }
    }
  }

  // ── input handler ──────────────────────────────────────────────────────────
  $input.addEventListener('input', () => {
    const title = $input.value.trim();
    clearTimeout(_debounce);
    if (!title) {
      $result.innerHTML = '';
      _lastTitle   = null;
      _currentData = null;
      return;
    }
    _debounce = setTimeout(() => doCheck(title), _DEBOUNCE_MS);
  });

  // ── init ───────────────────────────────────────────────────────────────────
  loadUser();

  document.addEventListener('click', async (e) => {
    const link = e.target.closest('a.logout-link');
    if (!link) return;
    e.preventDefault();
    await fetch('/social-credit/auth/discord/logout', { method: 'POST', credentials: 'same-origin' });
    window.location.href = '/social-credit/submit';
  });
})();

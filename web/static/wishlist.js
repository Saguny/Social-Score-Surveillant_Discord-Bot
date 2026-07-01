/* wishlist.js — community wishlist page */
(function () {
  'use strict';

  let _user = null;

  const $list  = document.getElementById('wl-list');
  const $bar   = document.getElementById('discord-bar');
  const $toast = document.getElementById('toast');

  // ── toast ──────────────────────────────────────────────────────────────────
  let _toastTimer = null;
  function toast(msg, type = '') {
    $toast.textContent = msg;
    $toast.className   = 'toast-msg show' + (type ? ' ' + type : '');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => { $toast.className = 'toast-msg'; }, 3200);
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
        <a href="/auth/discord/logout?next=/wishlist" class="logout-link">Log out</a>`;
    } else {
      $bar.innerHTML = `
        <div class="avatar-placeholder"></div>
        <span style="font-size:.82rem;color:var(--text-muted)">Log in to vote on character requests</span>
        <a href="/auth/discord?next=/wishlist" class="login-link">🔗 Login with Discord</a>`;
    }
  }

  async function loadUser() {
    try {
      const r = await fetch('/api/discord/me', { credentials: 'same-origin' });
      if (r.ok) _user = await r.json();
    } catch (_) {}
    renderBar(_user);
  }

  // ── render list ────────────────────────────────────────────────────────────
  // Server response fields per item: id, wiki_slug, wiki_title,
  // submitted_by (discord_username), submitted_at, vote_count,
  // recent_voters ([{discord_id, discord_username}]), has_voted
  function renderList(items) {
    if (!items || !items.length) {
      $list.innerHTML = `<div class="wl-empty">
        No pending requests yet.
        <a href="/submit" style="color:var(--sage)">Be the first to suggest someone!</a>
      </div>`;
      return;
    }

    $list.innerHTML = items.map((item, idx) => {
      const rank  = idx + 1;
      const when  = _timeAgo(item.submitted_at);
      const by    = item.submitted_by || '?';

      let btnHtml;
      if (!_user) {
        btnHtml = `<button class="wl-support-btn login-req" data-id="${item.id}" data-action="login">▲ Vote</button>`;
      } else if (item.has_voted) {
        btnHtml = `<button class="wl-support-btn voted" data-id="${item.id}" data-action="remove">✓ Voted</button>`;
      } else {
        btnHtml = `<button class="wl-support-btn" data-id="${item.id}" data-action="add">▲ Vote</button>`;
      }

      return `
        <div class="wl-row" data-id="${item.id}">
          <div class="wl-rank">${rank}</div>
          <div class="wl-portrait"><img id="portrait-${item.id}" src="" alt="" onerror="this.style.display='none'"></div>
          <div class="wl-meta">
            <div class="wl-name">${_esc(item.wiki_title)}</div>
            <div class="wl-desc">by @${_esc(by)} · ${when}</div>
          </div>
          <div class="wl-votes">
            <div class="n" id="vc-${item.id}">${item.vote_count}</div>
            <div class="lbl">${item.vote_count === 1 ? 'vote' : 'votes'}</div>
          </div>
          ${btnHtml}
        </div>`;
    }).join('');

    $list.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', onVoteClick);
    });
  }

  // ── vote handler ───────────────────────────────────────────────────────────
  // Server toggles automatically — no need to send action field.
  async function onVoteClick(e) {
    const btn    = e.currentTarget;
    const action = btn.dataset.action;
    const reqId  = parseInt(btn.dataset.id, 10);

    if (action === 'login') {
      window.location.href = '/auth/discord?next=/wishlist';
      return;
    }

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

      const voted = body.voted;
      const $vc   = document.getElementById('vc-' + reqId);
      if ($vc) $vc.textContent = body.vote_count;

      btn.textContent    = voted ? '✓ Voted' : '▲ Vote';
      btn.dataset.action = voted ? 'remove'  : 'add';
      btn.classList.toggle('voted', voted);
      btn.disabled = false;
    } catch (_) {
      toast('Network error', 'error');
      btn.disabled = false;
    }
  }

  // ── wikipedia thumbnails ───────────────────────────────────────────────────
  async function loadPortraits(items) {
    await Promise.all(items.map(async item => {
      const $img = document.getElementById('portrait-' + item.id);
      if (!$img) return;
      try {
        const r = await fetch(
          'https://en.wikipedia.org/api/rest_v1/page/summary/' + encodeURIComponent(item.wiki_slug),
          { headers: { Accept: 'application/json' } }
        );
        if (!r.ok) return;
        const data = await r.json();
        const src = data.thumbnail && data.thumbnail.source;
        if (src) $img.src = src;
      } catch (_) {}
    }));
  }

  // ── load wishlist ──────────────────────────────────────────────────────────
  async function loadList() {
    try {
      const r = await fetch('/api/requests/wishlist', { credentials: 'same-origin' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const data = await r.json();
      const items = data.requests || [];
      renderList(items);
      loadPortraits(items);
    } catch (_) {
      $list.innerHTML = '<div class="wl-empty">Failed to load — please refresh.</div>';
    }
  }

  // ── init ───────────────────────────────────────────────────────────────────
  loadUser().then(loadList);
})();

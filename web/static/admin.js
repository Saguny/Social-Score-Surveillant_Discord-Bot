/* ═══════════════════════════════════════════════════════════════════════════
   admin.js — Social Credit admin console
   ═══════════════════════════════════════════════════════════════════════════ */

function v(id) { const e = document.getElementById(id); return e ? e.value.trim() : ''; }

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/"/g, '&quot;')
    .replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
const _re = _esc;

/* ── Toasts ──────────────────────────────────────────────────────────────── */
function toast(msg, kind) {
  const stack = document.getElementById('toasts');
  if (!stack) { console.log(msg); return; }
  const el = document.createElement('div');
  el.className = 'toast-item' + (kind ? ' toast-' + kind : '');
  el.textContent = msg;
  stack.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => {
    el.classList.remove('show');
    setTimeout(() => el.remove(), 250);
  }, kind === 'error' ? 6000 : 3600);
}

/* ── Fetch wrapper ───────────────────────────────────────────────────────────
   One place that understands the three failure modes: signed out (bounce to
   login), capability denied (explain, do NOT bounce — bouncing a reviewer to a
   token login form was the old confusing behaviour), and everything else. */
async function api(url, opts) {
  let res;
  try {
    res = await fetch(url, opts);
  } catch (e) {
    return { ok: false, status: 0, data: { error: 'Network error.' } };
  }
  let data = {};
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) {
    data = await res.json().catch(() => ({}));
  }
  if (res.status === 401 && !data.missing_cap) {
    location.href = '/social-credit/login?next=/social-credit/admin';
    return { ok: false, status: 401, data };
  }
  return { ok: res.ok, status: res.status, data, res };
}

function apiError(r, fallback) {
  const d = r.data || {};
  if (d.needs_discord_login) {
    toast(d.error, 'error');
    if (confirm(d.error + '\n\nSign in with Discord now?')) {
      location.href = d.login_url || '/social-credit/auth/discord?next=/social-credit/admin';
    }
    loadWhoami();
    return;
  }
  toast(d.error || fallback || ('Request failed (' + r.status + ')'), 'error');
}

/* ── Console ─────────────────────────────────────────────────────────────── */
function log(cmd, output, ok) {
  const term = document.getElementById('terminal');
  if (!term) return;
  const prompt = document.createElement('div');
  prompt.className = 't-prompt';
  prompt.textContent = '> ' + cmd;
  const out = document.createElement('div');
  out.className = ok ? 't-ok' : 't-err';
  out.textContent = output;
  term.appendChild(prompt);
  term.appendChild(out);
  term.scrollTop = term.scrollHeight;
}

async function run(command, args = []) {
  if (!args.every(a => a !== '')) { log(command, 'Missing required arguments.', false); return; }
  const r = await api('/api/admin/command', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command, args }),
  });
  const text = r.data.output || r.data.error || 'No output.';
  log(command + (args.length ? ' ' + args.join(' ') : ''), text, r.ok && !r.data.error);
  if (!r.ok) { showSection('overview'); apiError(r); }
}

function confirmRun(command, args, msg) { if (confirm(msg)) run(command, args); }

/* ── Identity + section nav ──────────────────────────────────────────────── */
let _me = null;

async function loadWhoami() {
  const r = await api('/api/admin/whoami');
  // A 302 to the login page is followed by fetch and comes back as HTML, so
  // an ok response with no payload still means "not signed in".
  if (!r.ok || !r.data || !r.data.signed_in) {
    location.href = '/social-credit/login?next=/social-credit/admin';
    return;
  }
  _me = r.data;

  const chip = document.getElementById('whoami');
  if (chip) {
    const av = _me.avatar && _me.discord_id
      ? `<img src="https://cdn.discordapp.com/avatars/${_esc(_me.discord_id)}/${_esc(_me.avatar)}.png?size=64" alt="">`
      : '<span class="whoami-dot"></span>';
    const who = _me.username ? '@' + _esc(_me.username) : 'Token session';
    chip.innerHTML = `${av}<span class="whoami-text"><b>${who}</b><span>${_esc(_me.role_label)}</span></span>`;
  }

  // Hide anything this role cannot use.
  const caps = new Set(_me.caps || []);
  document.querySelectorAll('[data-cap]').forEach(el => {
    const need = el.getAttribute('data-cap');
    el.hidden = !!need && !caps.has(need);
  });

  const wanted = (location.hash || '').replace('#', '');
  const first  = document.querySelector('.anav-item:not([hidden])');
  const target = document.querySelector(`.anav-item[data-section="${wanted}"]:not([hidden])`);
  showSection(target ? wanted : (first ? first.dataset.section : 'overview'));
}

function showSection(name) {
  // The nav item is hidden when the role lacks the capability, so refuse to
  // reveal a section by hash. The API enforces this too; this keeps the UI
  // honest rather than showing controls that would only ever 403.
  const nav = document.querySelector(`.anav-item[data-section="${name}"]`);
  if (!nav || nav.hidden) {
    const first = document.querySelector('.anav-item:not([hidden])');
    if (!first || first.dataset.section === name) return;
    name = first.dataset.section;
  }
  document.querySelectorAll('.asec').forEach(s => s.classList.toggle('active', s.dataset.section === name));
  document.querySelectorAll('.anav-item').forEach(b => b.classList.toggle('active', b.dataset.section === name));
  document.getElementById('admin-nav')?.classList.remove('open');
  if (location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
  _sectionLoaders[name] && _sectionLoaders[name]();
}

const _loaded = {};
function _once(key, fn) { return () => { if (_loaded[key]) return; _loaded[key] = true; fn(); }; }

const _sectionLoaders = {
  overview:   _once('overview',   () => { loadVoteChart('7D'); loadOverviewStats(); }),
  requests:   _once('requests',   () => { loadPendingRequests(); loadSubmitSettings(); }),
  characters: _once('characters', () => { loadCharacterMeta().then(loadCharacters); }),
  broadcast:  _once('broadcast',  () => { loadGuildListForBroadcast(); renderEmbedFields(); renderEmbedPreview(); loadAnnouncement(); }),
  team:       _once('team',       () => { loadTeam(); }),
  audit:      _once('audit',      () => { loadAudit(); }),
};

/* ── Overview stats ──────────────────────────────────────────────────────── */
async function loadOverviewStats() {
  const wrap = document.getElementById('overview-stats');
  if (!wrap) return;
  const r = await api('/api/stats');
  if (!r.ok) return;
  const d = r.data;
  const tiles = [
    ['Citizens', (d.total_users || 0).toLocaleString()],
    ['Servers',  (d.total_guilds || 0).toLocaleString()],
    ['Messages rated', (d.total_messages || 0).toLocaleString()],
    ['Yuan in circulation', '¥' + (d.total_yuan || 0).toLocaleString()],
  ];
  wrap.innerHTML = tiles.map(([k, val]) =>
    `<div class="stat-tile"><div class="lbl">${_esc(k)}</div><div class="stat-val">${_esc(val)}</div></div>`
  ).join('');
}

/* ── Users ───────────────────────────────────────────────────────────────── */
async function lookupUser() {
  const userId = v('ul-user-id');
  const out = document.getElementById('ul-result');
  if (!userId) { out.innerHTML = '<div class="empty-state">Enter a user ID.</div>'; return; }
  out.innerHTML = '<div class="empty-state">Looking up…</div>';

  const r = await api('/api/admin/user-lookup?user_id=' + encodeURIComponent(userId));
  if (!r.ok) { out.innerHTML = ''; apiError(r); return; }
  const data = r.data;
  if (data.error) { out.innerHTML = `<div class="empty-state err">${_esc(data.error)}</div>`; return; }

  const header = `
    <div class="ul-head">
      <img src="${_esc(data.avatar_url)}" alt="" onerror="this.style.visibility='hidden'">
      <div><strong>${_esc(data.username)}</strong>
      <div class="hint-line">${_esc(data.user_id)}</div></div>
    </div>`;

  if (!data.guilds.length) {
    out.innerHTML = header + '<div class="empty-state">Not a member of any server the bot shares.</div>';
    return;
  }

  out.innerHTML = header + data.guilds.map(g => `
    <div class="ul-row" data-guild="${_esc(g.guild_id)}">
      <div class="ul-name">
        <strong>${_esc(g.guild_name)}</strong>
        <div class="hint-line" id="ul-sub-${_esc(g.guild_id)}">
          Score ${g.score.toFixed(2)} · <span class="ul-yuan">¥${g.yuan.toLocaleString()}</span>
        </div>
      </div>
      <input type="number" class="form-control form-control-sm ul-amt" placeholder="+/- amount">
      <button class="btn-run" onclick="applyYuan('${_esc(g.guild_id)}','${_esc(data.user_id)}', this)">Apply</button>
    </div>`).join('');
}

async function applyYuan(guildId, userId, btn) {
  const row = btn.closest('[data-guild]');
  const amtInput = row.querySelector('.ul-amt');
  const amount = parseInt(amtInput.value, 10);
  if (!amount) { toast('Enter a non-zero amount.', 'error'); return; }

  btn.disabled = true;
  const r = await api('/api/admin/user-yuan-adjust', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ guild_id: guildId, user_id: userId, amount }),
  });
  btn.disabled = false;
  if (!r.ok || r.data.error) { apiError(r, r.data.error); return; }

  // Target the span directly. The old code regex-replaced "&yen;" against
  // innerHTML, which serialises as "¥" — so the balance never updated.
  const sub = document.getElementById('ul-sub-' + guildId);
  const span = sub && sub.querySelector('.ul-yuan');
  if (span) span.textContent = '¥' + r.data.yuan.toLocaleString();
  amtInput.value = '';
  toast('Balance updated to ¥' + r.data.yuan.toLocaleString(), 'ok');
}

/* ── Embed broadcaster ───────────────────────────────────────────────────── */
let ebFields = [];

function addEmbedField() {
  if (ebFields.length >= 25) return;
  ebFields.push({ name: '', value: '', inline: false });
  renderEmbedFields(); renderEmbedPreview();
}
function removeEmbedField(i) { ebFields.splice(i, 1); renderEmbedFields(); renderEmbedPreview(); }
function updateEmbedField(i, key, val) { ebFields[i][key] = val; renderEmbedPreview(); }

function renderEmbedFields() {
  const container = document.getElementById('eb-fields');
  if (!container) return;
  container.innerHTML = '';
  ebFields.forEach((f, i) => {
    const row = document.createElement('div');
    row.className = 'row g-2 align-items-center mb-2';
    row.innerHTML = `
      <div class="col-4"><input type="text" class="form-control form-control-sm" placeholder="Field name" value="${_esc(f.name)}" oninput="updateEmbedField(${i},'name',this.value)"></div>
      <div class="col-5"><input type="text" class="form-control form-control-sm" placeholder="Field value" value="${_esc(f.value)}" oninput="updateEmbedField(${i},'value',this.value)"></div>
      <div class="col-auto form-check">
        <input class="form-check-input" type="checkbox" id="eb-inline-${i}" ${f.inline ? 'checked' : ''} onchange="updateEmbedField(${i},'inline',this.checked)">
        <label class="form-check-label" for="eb-inline-${i}" style="font-size:.7rem;color:var(--text-muted)">inline</label>
      </div>
      <div class="col-auto"><button class="btn-run btn-danger-soft btn-compact" onclick="removeEmbedField(${i})">&times;</button></div>`;
    container.appendChild(row);
  });
}

function renderEmbedPreview() {
  const prev = document.getElementById('eb-preview');
  if (!prev) return;
  const title = v('eb-title'), desc = v('eb-desc');
  const color = document.getElementById('eb-color').value;
  const image = v('eb-image'), thumb = v('eb-thumb');
  const btnLabel = v('eb-btn-label'), btnUrl = v('eb-btn-url');

  const fieldsHtml = ebFields.filter(f => f.name && f.value).map(f =>
    `<div style="flex:${f.inline ? '0 0 auto;min-width:120px' : '1 0 100%'};margin-top:8px">
       <div style="font-weight:600;font-size:.8rem">${_esc(f.name)}</div>
       <div style="font-size:.8rem;color:var(--text-muted);white-space:pre-wrap">${_esc(f.value)}</div>
     </div>`).join('');

  prev.innerHTML = `
    <div style="border-left:4px solid ${_esc(color)};background:var(--surface-recessed);border-radius:8px;padding:12px 14px;display:flex;gap:12px">
      <div style="flex:1;min-width:0">
        ${title ? `<div style="font-weight:700;margin-bottom:4px">${_esc(title)}</div>` : ''}
        ${desc ? `<div style="font-size:.85rem;color:var(--text-muted);white-space:pre-wrap">${_esc(desc)}</div>` : ''}
        <div style="display:flex;flex-wrap:wrap;gap:8px">${fieldsHtml}</div>
        ${image ? `<img src="${_esc(image)}" style="max-width:100%;border-radius:6px;margin-top:10px" onerror="this.style.display='none'">` : ''}
        ${btnLabel && btnUrl ? `<div style="margin-top:10px"><span style="display:inline-block;padding:6px 14px;border:1px solid var(--border-strong);border-radius:6px;font-size:.8rem">${_esc(btnLabel)}</span></div>` : ''}
        <div style="font-size:.7rem;color:var(--text-faint);margin-top:10px">GLORY TO THE CCP! (footer added automatically)</div>
      </div>
      ${thumb ? `<img src="${_esc(thumb)}" style="width:64px;height:64px;border-radius:6px;object-fit:cover" onerror="this.style.display='none'">` : ''}
    </div>`;
}

async function loadGuildListForBroadcast() {
  const r = await api('/api/admin/guild-list');
  if (!r.ok) return;
  const sel = document.getElementById('eb-target');
  if (!sel) return;
  sel.innerHTML = '<option value="all">All servers</option>';
  (r.data.guilds || []).forEach(g => {
    const opt = document.createElement('option');
    opt.value = g.id;
    opt.textContent = `${g.name} (${g.member_count} members)`;
    sel.appendChild(opt);
  });
}

async function sendBroadcastEmbed() {
  const title = v('eb-title'), desc = v('eb-desc');
  if (!title && !desc) { toast('Add a title or description first.', 'error'); return; }
  const sel = document.getElementById('eb-target');
  const targetLabel = sel.selectedOptions[0].textContent;
  if (!confirm(`Send this embed to ${targetLabel}? This sends once, immediately, and cannot be undone.`)) return;

  const out = document.getElementById('eb-result');
  out.textContent = 'Sending…';
  const r = await api('/api/admin/broadcast-embed', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      target: sel.value, title, description: desc,
      color: document.getElementById('eb-color').value.replace('#', ''),
      image_url: v('eb-image'), thumbnail_url: v('eb-thumb'),
      fields: ebFields.filter(f => f.name && f.value),
      button_label: v('eb-btn-label'), button_url: v('eb-btn-url'),
    }),
  });
  if (!r.ok || r.data.error) { out.textContent = ''; apiError(r, r.data.error); return; }
  out.textContent = `Sent to ${r.data.sent}/${r.data.total} guild(s):\n` +
    r.data.results.map(x => `${x.guild_name} (${x.guild_id}) — ${x.status}${x.detail ? ': ' + x.detail : ''}`).join('\n');
  toast(`Embed sent to ${r.data.sent} guild(s).`, 'ok');
}

/* ── Announcement ────────────────────────────────────────────────────────── */
async function loadAnnouncement() {
  const r = await api('/api/announcement');
  if (!r.ok) return;
  document.getElementById('an-enabled').checked = !!r.data.enabled;
  document.getElementById('an-severity').value = r.data.severity || 'info';
  document.getElementById('an-message').value = r.data.message || '';
  renderAnnouncementPreview();
}

function renderAnnouncementPreview() {
  const preview = document.getElementById('an-preview');
  if (!preview) return;
  const enabled = document.getElementById('an-enabled').checked;
  const severity = document.getElementById('an-severity').value;
  const message = v('an-message');
  preview.innerHTML = (!enabled || !message)
    ? '<div class="hint-line">Banner hidden (disabled or empty message).</div>'
    : `<div class="announce-banner announce-${_esc(severity)}">${_esc(message)}</div>`;
}

async function saveAnnouncement() {
  const out = document.getElementById('an-result');
  out.textContent = 'Saving…';
  const r = await api('/api/admin/announcement', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      enabled: document.getElementById('an-enabled').checked,
      severity: document.getElementById('an-severity').value,
      message: v('an-message'),
    }),
  });
  if (!r.ok || r.data.error) { out.textContent = ''; apiError(r, r.data.error); return; }
  out.textContent = 'Saved. Live on the dashboard immediately, no restart needed.';
  toast('Announcement saved.', 'ok');
}

/* ── Vote chart ──────────────────────────────────────────────────────────── */
let _voteChart = null;

function _formatBucket(ts, period) {
  const d = new Date(ts * 1000);
  if (period === '1D') return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

async function loadVoteChart(period) {
  document.querySelectorAll('[data-period]').forEach(b => b.classList.toggle('active', b.dataset.period === period));
  const r = await api('/api/admin/topgg-votes?period=' + period);
  if (!r.ok) return;
  const data = r.data;
  document.getElementById('vote-total').textContent =
    data.total + ' vote' + (data.total === 1 ? '' : 's') + ' · ' + period;

  const ctx = document.getElementById('vote-chart').getContext('2d');
  if (_voteChart) _voteChart.destroy();
  _voteChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.buckets.map(b => _formatBucket(b.bucket, period)),
      datasets: [{ label: 'Votes', data: data.buckets.map(b => b.votes), backgroundColor: '#8FB3B1', borderRadius: 3 }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  });
}

/* ── Submissions ─────────────────────────────────────────────────────────── */
async function loadSubmitSettings() {
  const r = await api('/api/admin/submit-settings');
  if (!r.ok) return;
  const el = document.getElementById('submit-limit-val');
  if (el) el.value = r.data.submit_daily_limit ?? 25;
}

async function saveSubmitLimit() {
  const el = document.getElementById('submit-limit-val');
  const out = document.getElementById('submit-limit-result');
  const val = parseInt(el?.value, 10);
  if (!el || isNaN(val) || val < 1 || val > 1000) {
    out.textContent = 'Enter a number between 1 and 1000.';
    return;
  }
  const r = await api('/api/admin/submit-settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ submit_daily_limit: val }),
  });
  if (!r.ok) { out.textContent = ''; apiError(r); return; }
  out.textContent = `Saved — limit is now ${val}/day.`;
  toast('Submit limit saved.', 'ok');
}

let _reqSort = 'votes';
function setReqSort(sort) {
  _reqSort = sort;
  document.getElementById('sort-votes').classList.toggle('active', sort === 'votes');
  document.getElementById('sort-newest').classList.toggle('active', sort === 'newest');
  loadPendingRequests();
}

async function loadReviewerIdentity() {
  const bar = document.getElementById('reviewer-bar');
  if (!bar || !_me) return;
  bar.hidden = false;
  if (_me.can_review) {
    const av = _me.avatar && _me.discord_id
      ? `<img class="rv-avatar" src="https://cdn.discordapp.com/avatars/${_esc(_me.discord_id)}/${_esc(_me.avatar)}.png?size=64" alt="">`
      : '<div class="rv-avatar"></div>';
    bar.className = 'reviewer-bar rv-ok';
    bar.innerHTML = `${av}<div class="rv-text">Reviewing as <b>@${_esc(_me.username)}</b> · recorded on every approval and decline</div>`;
  } else {
    bar.className = 'reviewer-bar rv-warn';
    bar.innerHTML = `<div class="rv-text">Not linked to Discord. Approve and decline are disabled until you sign in, so every review can be attributed.</div>
                     <a class="rv-btn" href="${_esc(_me.login_url)}">Link Discord</a>`;
  }
}

function _handleReviewerError(body) {
  if (!body || !body.needs_discord_login) return false;
  apiError({ data: body, status: 403 });
  return true;
}

async function loadPendingRequests() {
  const $list = document.getElementById('req-list');
  if (!$list) return;
  loadReviewerIdentity();
  $list.innerHTML = '<div class="empty-state">Loading…</div>';
  const r = await api('/api/admin/requests?sort=' + _reqSort);
  if (!r.ok) { $list.innerHTML = '<div class="empty-state err">Failed to load.</div>'; return; }
  const rows = r.data.requests || [];
  const badge = document.getElementById('req-badge');
  if (badge) {
    if (rows.length) { badge.textContent = rows.length; badge.style.display = ''; }
    else badge.style.display = 'none';
  }
  if (!rows.length) { $list.innerHTML = '<div class="empty-state">No pending requests. 🎉</div>'; return; }

  const RARITIES = ['legendary','epic','rare','uncommon','common'];
  const GENDERS  = ['male','female','other'];
  const FACTIONS = ['reds','strongmen','conquerors','icons','capitalists','philosophers','wildcards'];

  $list.innerHTML = rows.map(req => {
    const curRarity  = req.override_rarity  || '';
    const curGender  = req.override_gender  || '';
    const curFaction = req.override_faction || '';
    const curTitle   = req.override_title   || '';
    const curUrls    = (req.override_image_urls || []).join('\n');
    const wikiLang   = req.wiki_lang || 'en';
    const badges = [
      curRarity  ? `<span class="req-override-badge">${_re(curRarity)}</span>` : '',
      curGender  ? `<span class="req-override-badge">${_re(curGender)}</span>` : '',
      curFaction ? `<span class="req-override-badge">${_re(curFaction)}</span>` : '',
      curTitle   ? `<span class="req-override-badge" title="${_re(curTitle)}">${_re(curTitle.slice(0,20))}${curTitle.length>20?'…':''}</span>` : '',
      (req.override_image_urls || []).length ? `<span class="req-override-badge">${req.override_image_urls.length} img</span>` : '',
    ].join('');
    const opts = (arr, cur) => arr.map(x => `<option value="${x}"${cur===x?' selected':''}>${x}</option>`).join('');
    return `
      <div class="req-row" id="req-${req.id}">
        <div class="req-top">
          <div class="req-meta">
            <span class="req-title">${_re(req.wiki_title)}</span>
            <span class="req-votes">${req.vote_count || 0} vote${(req.vote_count || 0) !== 1 ? 's' : ''}</span>
            <span class="req-by">@${_re(req.discord_username)}</span>
            <a href="https://${_re(wikiLang)}.wikipedia.org/wiki/${encodeURIComponent(req.wiki_slug)}" target="_blank" rel="noopener" class="req-wiki">Wikipedia ↗</a>
            ${badges}
          </div>
          <div class="req-actions">
            <button class="req-btn req-approve" onclick="approveRequest(${req.id}, '${_re(req.wiki_title).replace(/'/g, "\\'")}')">Approve</button>
            <button class="req-btn req-reject"  onclick="toggleReqReject(${req.id})">Decline</button>
            <button class="req-btn req-ban"     onclick="banSubmitter(${req.id}, ${req.discord_id})">Ban</button>
            <button class="req-btn req-edit"    onclick="toggleReqEdit(${req.id})">Edit</button>
          </div>
        </div>
        <div class="req-edit-panel" id="req-edit-${req.id}" style="display:none">
          <div class="row g-2 align-items-end">
            <div class="col-auto"><label class="form-label">Faction</label>
              <select class="form-select form-select-sm" id="req-edit-faction-${req.id}" style="width:145px"><option value="">— auto —</option>${opts(FACTIONS, curFaction)}</select></div>
            <div class="col-auto"><label class="form-label">Rarity</label>
              <select class="form-select form-select-sm" id="req-edit-rarity-${req.id}" style="width:135px"><option value="">— auto —</option>${opts(RARITIES, curRarity)}</select></div>
            <div class="col-auto"><label class="form-label">Gender</label>
              <select class="form-select form-select-sm" id="req-edit-gender-${req.id}" style="width:115px"><option value="">— auto —</option>${opts(GENDERS, curGender)}</select></div>
            <div class="col-auto"><button class="btn-run" onclick="saveReqEdit(${req.id})">Save</button></div>
            <div class="col-auto hint-line" id="req-edit-result-${req.id}"></div>
          </div>
          <div class="mt-2">
            <label class="form-label">Description / title <span style="font-weight:400;color:var(--text-faint)">(shown on card)</span></label>
            <input type="text" class="form-control form-control-sm" id="req-edit-title-${req.id}" maxlength="100" value="${_re(curTitle)}" placeholder="e.g. German YouTuber">
          </div>
          <div class="mt-2">
            <label class="form-label">Image URLs — one per line (blank uses the pipeline)</label>
            <textarea class="form-control form-control-sm mono-input" id="req-edit-urls-${req.id}" rows="3">${_re(curUrls)}</textarea>
          </div>
        </div>
        <div class="req-reject-panel" id="req-reject-${req.id}" style="display:none">
          <label class="form-label">Reason <span style="font-weight:400;color:var(--text-faint)">(optional · DMed to the submitter)</span></label>
          <textarea class="form-control form-control-sm" id="req-reject-reason-${req.id}" rows="2" placeholder="e.g. Not a real historical figure, image quality too low…" maxlength="500"></textarea>
          <div style="display:flex;gap:.4rem;margin-top:.5rem">
            <button class="req-btn req-reject" onclick="confirmRejectRequest(${req.id})">Confirm decline</button>
            <button class="req-btn req-cancel" onclick="toggleReqReject(${req.id})">Cancel</button>
          </div>
        </div>
      </div>`;
  }).join('');
}

function toggleReqEdit(id) {
  const p = document.getElementById('req-edit-' + id);
  if (p) p.style.display = p.style.display === 'none' ? 'block' : 'none';
}

function toggleReqReject(id) {
  const p = document.getElementById('req-reject-' + id);
  if (!p) return;
  const opening = p.style.display === 'none';
  p.style.display = opening ? 'block' : 'none';
  if (opening) { const ta = document.getElementById('req-reject-reason-' + id); if (ta) { ta.value = ''; ta.focus(); } }
}

async function confirmRejectRequest(requestId) {
  const ta = document.getElementById('req-reject-reason-' + requestId);
  await _doReject(requestId, ta ? ta.value.trim() : '');
}

async function _doReject(requestId, reason) {
  const r = await api('/api/admin/requests/reject', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId, reason }),
  });
  if (r.ok) {
    document.getElementById('req-' + requestId)?.remove();
    toast('Submission declined.', 'ok');
  } else apiError(r);
}

async function saveReqEdit(id) {
  const out = document.getElementById('req-edit-result-' + id);
  const urlsRaw = document.getElementById('req-edit-urls-' + id).value;
  out.textContent = 'Saving…';
  const r = await api('/api/admin/requests/edit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      request_id: id,
      faction: document.getElementById('req-edit-faction-' + id).value || null,
      rarity:  document.getElementById('req-edit-rarity-' + id).value || null,
      gender:  document.getElementById('req-edit-gender-' + id).value || null,
      title:   (document.getElementById('req-edit-title-' + id).value || '').trim() || null,
      image_urls: urlsRaw.split('\n').map(u => u.trim()).filter(Boolean),
    }),
  });
  if (r.ok) { out.textContent = 'Saved.'; toast('Overrides saved.', 'ok'); }
  else { out.textContent = ''; apiError(r); }
}

async function approveRequest(requestId, title) {
  const $panel = document.getElementById('req-pipeline');
  const $log = document.getElementById('req-pipeline-log');
  if (!$panel || !$log) return;
  if (!confirm(`Approve "${title}" and run the full gacha pipeline?`)) return;

  $panel.style.display = 'block';
  $log.innerHTML = '';
  document.getElementById('req-pipeline-title').textContent = title;
  $panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  function addLine(msg, ok) {
    const d = document.createElement('div');
    d.className = ok === false ? 'pipe-line pipe-err' : 'pipe-line pipe-ok';
    d.textContent = msg;
    $log.appendChild(d);
    $log.scrollTop = $log.scrollHeight;
  }

  let res;
  try {
    res = await fetch('/api/admin/requests/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId }),
    });
  } catch (_) { addLine('Network error.', false); return; }

  if ((res.headers.get('content-type') || '').includes('event-stream')) {
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '', succeeded = false;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const part of parts) {
        try {
          const ev = JSON.parse(part.replace(/^data: /, ''));
          addLine((ev.ok === false ? '⚠ ' : '✓ ') + ev.msg, ev.ok !== false);
          if (ev.stage === 'done' && ev.ok !== false) succeeded = true;
        } catch (_) {}
      }
    }
    if (succeeded) {
      document.getElementById('req-' + requestId)?.remove();
      toast(`${title} added to the gacha pool.`, 'ok');
      _loaded.characters = false;
    }
  } else {
    const body = await res.json().catch(() => ({}));
    addLine('Error: ' + (body.error || res.status), false);
    apiError({ data: body, status: res.status });
  }
}

async function banSubmitter(requestId, discordId) {
  if (!confirm('Ban this submitter? They will no longer be able to submit requests.')) return;
  const r = await api('/api/admin/requests/ban', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ discord_id: discordId }),
  });
  if (r.ok) { await _doReject(requestId, ''); toast('Submitter banned.', 'ok'); }
  else apiError(r);
}

/* ── Character editor ────────────────────────────────────────────────────── */
let _charMeta = { factions: [], rarities: [], genders: [] };
let _charPage = 1;
let _charDebounce = null;

async function loadCharacterMeta() {
  const r = await api('/api/admin/characters/meta');
  if (!r.ok) return;
  _charMeta = r.data;
  const f = document.getElementById('char-faction');
  const ra = document.getElementById('char-rarity');
  if (f)  f.innerHTML  = '<option value="">All factions</option>' + _charMeta.factions.map(x => `<option value="${x}">${x}</option>`).join('');
  if (ra) ra.innerHTML = '<option value="">All rarities</option>' + _charMeta.rarities.map(x => `<option value="${x}">${x}</option>`).join('');

  const s = _charMeta.stats || {};
  const wrap = document.getElementById('char-stats');
  if (wrap) {
    wrap.innerHTML = [
      ['Total', s.total], ['Enabled', s.enabled],
      ['VN exclusive', s.vn_exclusive], ['Missing art', s.no_images],
    ].map(([k, val]) =>
      `<div class="stat-tile"><div class="lbl">${k}</div><div class="stat-val">${(val ?? 0).toLocaleString()}</div></div>`
    ).join('');
  }
}

function _charQuery() {
  const p = new URLSearchParams();
  const q = v('char-search'); if (q) p.set('q', q);
  const f = document.getElementById('char-faction')?.value; if (f) p.set('faction', f);
  const r = document.getElementById('char-rarity')?.value;  if (r) p.set('rarity', r);
  const e = document.getElementById('char-enabled')?.value; if (e) p.set('enabled', e);
  if (document.getElementById('char-missing')?.checked) p.set('missing_images', '1');
  p.set('page', _charPage);
  return p.toString();
}

async function loadCharacters() {
  const list = document.getElementById('char-list');
  if (!list) return;
  list.innerHTML = '<div class="empty-state">Loading…</div>';
  const r = await api('/api/admin/characters?' + _charQuery());
  if (!r.ok) { list.innerHTML = '<div class="empty-state err">Failed to load.</div>'; apiError(r); return; }

  const { characters, total, page, pages } = r.data;
  document.getElementById('char-count').textContent =
    total ? `${total.toLocaleString()} character${total === 1 ? '' : 's'} · page ${page} of ${pages}` : '';

  if (!characters.length) { list.innerHTML = '<div class="empty-state">No characters match those filters.</div>'; document.getElementById('char-pager').innerHTML = ''; return; }

  list.innerHTML = characters.map(c => {
    const img = (c.image_urls || [])[0];
    const thumb = img
      ? `<img src="${_esc(img)}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'ch-noimg',textContent:'?'}))">`
      : '<div class="ch-noimg">?</div>';
    return `
      <button class="ch-row" onclick="openCharacter('${_esc(c.character_id)}')">
        <div class="ch-thumb">${thumb}</div>
        <div class="ch-main">
          <div class="ch-name">${_esc(c.name)}${c.enabled ? '' : ' <span class="ch-flag off">disabled</span>'}${c.vn_exclusive ? ' <span class="ch-flag vn">VN</span>' : ''}</div>
          <div class="ch-sub">${_esc(c.title || '—')}</div>
          <div class="ch-id">${_esc(c.character_id)}</div>
        </div>
        <div class="ch-tags">
          <span class="ch-tag r-${_esc(c.rarity)}">${_esc(c.rarity)}</span>
          <span class="ch-tag">${_esc(c.faction)}</span>
          ${(c.image_urls || []).length ? `<span class="ch-tag">${c.image_urls.length} img</span>` : '<span class="ch-tag warn">no art</span>'}
        </div>
      </button>`;
  }).join('');

  const pager = document.getElementById('char-pager');
  pager.innerHTML = pages <= 1 ? '' : `
    <button class="btn-run" ${page <= 1 ? 'disabled' : ''} onclick="charPage(${page - 1})">← Prev</button>
    <span class="hint-line">Page ${page} / ${pages}</span>
    <button class="btn-run" ${page >= pages ? 'disabled' : ''} onclick="charPage(${page + 1})">Next →</button>`;
}

function charPage(p) { _charPage = p; loadCharacters(); window.scrollTo({ top: 0, behavior: 'smooth' }); }

function _charFilterChanged() { _charPage = 1; loadCharacters(); }

async function openCharacter(cid) {
  const drawer = document.getElementById('char-editor');
  const backdrop = document.getElementById('char-backdrop');
  drawer.hidden = false; backdrop.hidden = false;
  drawer.innerHTML = '<div class="empty-state">Loading…</div>';

  const r = await api('/api/admin/characters/' + encodeURIComponent(cid));
  if (!r.ok) { drawer.innerHTML = '<div class="empty-state err">Not found.</div>'; return; }
  const c = r.data;
  const sel = (arr, cur) => arr.map(x => `<option value="${x}"${cur === x ? ' selected' : ''}>${x}</option>`).join('');

  drawer.innerHTML = `
    <div class="drawer-head">
      <div><div class="drawer-title">${_esc(c.name)}</div><div class="hint-line">${_esc(c.character_id)}</div></div>
      <button class="sidebar-close" onclick="closeCharacter()" aria-label="Close">
        <svg width="18" height="18"><use href="#i-close"/></svg>
      </button>
    </div>
    <div class="drawer-body">
      <label class="form-label">Name</label>
      <input class="form-control" id="ce-name" value="${_esc(c.name)}" maxlength="120">

      <label class="form-label mt-3">Title / description</label>
      <input class="form-control" id="ce-title" value="${_esc(c.title)}" maxlength="120" placeholder="e.g. German YouTuber">

      <label class="form-label mt-3">Quote</label>
      <input class="form-control" id="ce-quote" value="${_esc(c.quote)}" maxlength="300">

      <div class="row g-2 mt-2">
        <div class="col-6"><label class="form-label">Faction</label>
          <select class="form-select" id="ce-faction">${sel(_charMeta.factions, c.faction)}</select></div>
        <div class="col-6"><label class="form-label">Rarity</label>
          <select class="form-select" id="ce-rarity">${sel(_charMeta.rarities, c.rarity)}</select></div>
        <div class="col-6"><label class="form-label">Gender</label>
          <select class="form-select" id="ce-gender"><option value="">—</option>${sel(_charMeta.genders, c.gender || '')}</select></div>
        <div class="col-6"><label class="form-label">Wiki lang</label>
          <input class="form-control" id="ce-wikilang" value="${_esc(c.wiki_lang || 'en')}" maxlength="8"></div>
      </div>

      <label class="form-label mt-3">Wikipedia slug</label>
      <input class="form-control mono-input" id="ce-wiki" value="${_esc(c.wiki)}" maxlength="200">

      <div class="shdr">Stats</div>
      ${['authority', 'military', 'charisma'].map(k => `
        <div class="stat-slider">
          <label class="form-label">${k}</label>
          <input type="range" id="ce-${k}" min="0" max="100" value="${c.stats[k]}"
                 oninput="document.getElementById('ce-${k}-val').textContent=this.value">
          <output id="ce-${k}-val">${c.stats[k]}</output>
        </div>`).join('')}

      <div class="shdr">Flags</div>
      <label class="inline-check"><input type="checkbox" id="ce-enabled" ${c.enabled ? 'checked' : ''}> <span>Enabled (rollable)</span></label>
      <label class="inline-check"><input type="checkbox" id="ce-vn" ${c.vn_exclusive ? 'checked' : ''}> <span>VN exclusive</span></label>

      <div class="shdr">Artwork</div>
      <div class="ce-images" id="ce-images"></div>
      <label class="form-label mt-2">Add image URLs (one per line)</label>
      <textarea class="form-control mono-input" id="ce-newimg" rows="2" placeholder="https://…"></textarea>
      <div class="d-flex gap-2 mt-2 flex-wrap">
        <button class="btn-run" onclick="uploadCharImages('${_esc(c.character_id)}')">Upload to R2</button>
        <button class="btn-run" onclick="addCharImageDirect()">Add as-is</button>
      </div>
      <div class="hint-line">Upload mirrors the image into R2 so cards never hotlink. "Add as-is" keeps the external URL.</div>
    </div>
    <div class="drawer-foot">
      <button class="btn-run btn-danger-soft" onclick="deleteCharacter('${_esc(c.character_id)}','${_esc(c.name).replace(/'/g, "\\'")}')">Delete</button>
      <div class="toolbar-spacer"></div>
      <button class="btn-run" onclick="closeCharacter()">Cancel</button>
      <button class="btn-run btn-primary-soft" onclick="saveCharacter('${_esc(c.character_id)}')">Save changes</button>
    </div>`;

  _ceImages = (c.image_urls || []).slice();
  renderCharImages();
  document.getElementById('ce-name').focus();
}

let _ceImages = [];

function renderCharImages() {
  const wrap = document.getElementById('ce-images');
  if (!wrap) return;
  if (!_ceImages.length) { wrap.innerHTML = '<div class="hint-line">No artwork yet.</div>'; return; }
  wrap.innerHTML = _ceImages.map((u, i) => `
    <div class="ce-img">
      <img src="${_esc(u)}" alt="" loading="lazy" onerror="this.style.opacity=.25">
      <div class="ce-img-tools">
        <button title="Move left" ${i === 0 ? 'disabled' : ''} onclick="moveCharImage(${i},-1)">←</button>
        <button title="Move right" ${i === _ceImages.length - 1 ? 'disabled' : ''} onclick="moveCharImage(${i},1)">→</button>
        <button title="Remove" onclick="removeCharImage(${i})">✕</button>
      </div>
      ${i === 0 ? '<span class="ce-img-primary">primary</span>' : ''}
    </div>`).join('');
}

function moveCharImage(i, dir) {
  const j = i + dir;
  if (j < 0 || j >= _ceImages.length) return;
  [_ceImages[i], _ceImages[j]] = [_ceImages[j], _ceImages[i]];
  renderCharImages();
}
function removeCharImage(i) { _ceImages.splice(i, 1); renderCharImages(); }

function addCharImageDirect() {
  const ta = document.getElementById('ce-newimg');
  const urls = ta.value.split('\n').map(s => s.trim()).filter(Boolean);
  const bad = urls.filter(u => !/^https?:\/\//i.test(u));
  if (bad.length) { toast('URLs must start with http:// or https://', 'error'); return; }
  _ceImages = _ceImages.concat(urls).slice(0, 12);
  ta.value = '';
  renderCharImages();
}

async function uploadCharImages(cid) {
  const ta = document.getElementById('ce-newimg');
  const urls = ta.value.split('\n').map(s => s.trim()).filter(Boolean);
  if (!urls.length) { toast('Paste at least one URL first.', 'error'); return; }
  toast('Uploading to R2…');
  const r = await api(`/api/admin/characters/${encodeURIComponent(cid)}/images`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ urls }),
  });
  if (!r.ok) { apiError(r); return; }
  (r.data.errors || []).forEach(e => toast(e, 'error'));
  if ((r.data.uploaded || []).length) {
    _ceImages = _ceImages.concat(r.data.uploaded).slice(0, 12);
    ta.value = '';
    renderCharImages();
    toast(`Uploaded ${r.data.uploaded.length} image(s).`, 'ok');
  }
}

async function saveCharacter(cid) {
  const payload = {
    name:        v('ce-name'),
    title:       v('ce-title'),
    quote:       v('ce-quote'),
    wiki:        v('ce-wiki'),
    wiki_lang:   v('ce-wikilang') || 'en',
    faction:     document.getElementById('ce-faction').value,
    rarity:      document.getElementById('ce-rarity').value,
    gender:      document.getElementById('ce-gender').value || null,
    enabled:     document.getElementById('ce-enabled').checked,
    vn_exclusive: document.getElementById('ce-vn').checked,
    authority:   +document.getElementById('ce-authority').value,
    military:    +document.getElementById('ce-military').value,
    charisma:    +document.getElementById('ce-charisma').value,
    image_urls:  _ceImages,
  };
  if (!payload.name) { toast('Name cannot be empty.', 'error'); return; }

  const r = await api('/api/admin/characters/' + encodeURIComponent(cid), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) { apiError(r); return; }
  toast('Saved. Bot reloads the roster within ~10 minutes.', 'ok');
  closeCharacter();
  loadCharacters();
  loadCharacterMeta();
}

async function deleteCharacter(cid, name) {
  if (!confirm(`Delete "${name}" permanently?\n\nThis also removes every claim and wishlist entry for them. Disabling is usually safer.`)) return;
  if (!confirm('Really delete? This cannot be undone.')) return;
  const r = await api(`/api/admin/characters/${encodeURIComponent(cid)}/delete`, { method: 'POST' });
  if (!r.ok) { apiError(r); return; }
  toast(`${name} deleted.`, 'ok');
  closeCharacter();
  loadCharacters();
  loadCharacterMeta();
}

function closeCharacter() {
  document.getElementById('char-editor').hidden = true;
  document.getElementById('char-backdrop').hidden = true;
}

/* ── Team ────────────────────────────────────────────────────────────────── */
async function loadTeam() {
  const list = document.getElementById('team-list');
  if (!list) return;
  const r = await api('/api/admin/team');
  if (!r.ok) { list.innerHTML = '<div class="empty-state err">Failed to load.</div>'; return; }

  const roleSel = document.getElementById('team-role');
  if (roleSel && !roleSel.options.length) {
    roleSel.innerHTML = r.data.assignable
      .filter(x => x.value !== 'owner')
      .concat(r.data.assignable.filter(x => x.value === 'owner'))
      .map(x => `<option value="${x.value}">${_esc(x.label)}</option>`).join('');
    roleSel.value = 'gacha_reviewer';
  }

  const legend = document.getElementById('role-legend');
  if (legend) {
    legend.innerHTML = Object.entries(r.data.role_caps).map(([role, caps]) =>
      `<div><b>${_esc(r.data.assignable.find(a => a.value === role)?.label || role)}</b> — ${caps.join(', ')}</div>`
    ).join('');
  }

  const envRows = (r.data.env_owners || []).map(id => `
    <div class="team-row">
      <div class="team-main"><strong>${_esc(id)}</strong>
        <div class="hint-line">Owner via ADMIN_DISCORD_IDS — edit the env var to change</div></div>
      <span class="ch-tag">Owner</span>
    </div>`).join('');

  const rows = (r.data.roles || []).map(m => `
    <div class="team-row">
      <div class="team-main">
        <strong>${m.username ? '@' + _esc(m.username) : _esc(m.discord_id)}</strong>
        <div class="hint-line">${_esc(m.discord_id)}${m.note ? ' · ' + _esc(m.note) : ''}${m.added_by_username ? ' · added by @' + _esc(m.added_by_username) : ''}</div>
      </div>
      <span class="ch-tag">${_esc(m.role_label)}</span>
      <button class="btn-run btn-danger-soft btn-compact" onclick="removeTeamMember('${_esc(m.discord_id)}')">Remove</button>
    </div>`).join('');

  list.innerHTML = (envRows + rows) || '<div class="empty-state">No team members yet.</div>';
}

async function saveTeamMember() {
  const out = document.getElementById('team-result');
  const id = v('team-id');
  if (!/^\d+$/.test(id)) { out.textContent = 'Discord ID must be numeric.'; return; }
  out.textContent = 'Saving…';
  const r = await api('/api/admin/team/set', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      discord_id: id,
      role: document.getElementById('team-role').value,
      note: v('team-note'),
    }),
  });
  if (!r.ok) { out.textContent = ''; apiError(r); return; }
  out.textContent = '';
  document.getElementById('team-id').value = '';
  document.getElementById('team-note').value = '';
  toast(r.data.username ? `@${r.data.username} updated.` : 'Team member updated.', 'ok');
  loadTeam();
}

async function removeTeamMember(id) {
  if (!confirm('Remove this member\u2019s panel access?')) return;
  const r = await api('/api/admin/team/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ discord_id: id }),
  });
  if (!r.ok) { apiError(r); return; }
  toast('Access removed.', 'ok');
  loadTeam();
}

async function loadAudit() {
  const list = document.getElementById('audit-list');
  if (!list) return;
  const r = await api('/api/admin/audit');
  if (!r.ok) { list.innerHTML = '<div class="empty-state err">Failed to load.</div>'; return; }
  const rows = r.data.entries || [];
  if (!rows.length) { list.innerHTML = '<div class="empty-state">No actions recorded yet.</div>'; return; }
  list.innerHTML = `<div class="audit-table">${rows.map(e => `
    <div class="audit-row">
      <span class="audit-when">${new Date(e.created_at * 1000).toLocaleString()}</span>
      <span class="audit-who">${e.actor_username ? '@' + _esc(e.actor_username) : 'token'}</span>
      <span class="audit-what">${_esc(e.action)}</span>
      <span class="audit-target">${_esc(e.target)}</span>
      <span class="audit-detail">${_esc(e.detail)}</span>
    </div>`).join('')}</div>`;
}

/* ── Live logs ───────────────────────────────────────────────────────────── */
let _logEs = null, _logSvc = null;
const _LOG_MAX = 1000;

function switchLogService(svc) {
  document.querySelectorAll('.log-svc-btn').forEach(b => b.classList.toggle('active', b.dataset.svc === svc));
  _openLogStream(svc);
}

function _openLogStream(svc) {
  if (_logEs) { _logEs.close(); _logEs = null; }
  _logSvc = svc;
  const panel = document.getElementById('log-panel');
  const status = document.getElementById('log-status');
  if (!panel || !status) return;
  panel.innerHTML = '';
  status.textContent = 'Connecting to ' + svc + '…';
  status.className = 'log-status-bar log-status-connecting';

  _logEs = new EventSource('/api/admin/logs/stream?service=' + encodeURIComponent(svc));
  _logEs.onopen = () => { status.textContent = svc + ' · live'; status.className = 'log-status-bar log-status-live'; };
  _logEs.onmessage = (e) => { try { _appendLogLine(panel, JSON.parse(e.data).line || ''); } catch (_) {} };
  _logEs.onerror = () => { status.textContent = svc + ' · disconnected — retrying…'; status.className = 'log-status-bar log-status-err'; };
}

function _appendLogLine(panel, text) {
  const div = document.createElement('div');
  const lo = text.toLowerCase();
  div.className = 'log-line' + (lo.includes('error') || lo.includes('critical') ? ' log-line-err' : lo.includes('warn') ? ' log-line-warn' : '');
  div.textContent = text;
  panel.appendChild(div);
  while (panel.children.length > _LOG_MAX) panel.removeChild(panel.firstChild);
  panel.scrollTop = panel.scrollHeight;
}

function clearLog() { const p = document.getElementById('log-panel'); if (p) p.innerHTML = ''; }

/* ── Wiring ──────────────────────────────────────────────────────────────── */
document.addEventListener('click', (e) => {
  const nav = e.target.closest('.anav-item');
  if (nav) { showSection(nav.dataset.section); return; }
  if (e.target.closest('#admin-nav-toggle')) {
    document.getElementById('admin-nav')?.classList.toggle('open');
  }
  if (e.target.id === 'char-backdrop') closeCharacter();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (!document.getElementById('char-editor')?.hidden) closeCharacter();
    document.getElementById('admin-nav')?.classList.remove('open');
  }
  if (e.key === '/' && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
    const active = document.querySelector('.asec.active')?.dataset.section;
    const box = active === 'characters' ? document.getElementById('char-search')
              : active === 'users'      ? document.getElementById('ul-user-id') : null;
    if (box) { e.preventDefault(); box.focus(); }
  }
});

document.addEventListener('DOMContentLoaded', () => {
  ['char-faction', 'char-rarity', 'char-enabled', 'char-missing'].forEach(id => {
    document.getElementById(id)?.addEventListener('change', _charFilterChanged);
  });
  document.getElementById('char-search')?.addEventListener('input', () => {
    clearTimeout(_charDebounce);
    _charDebounce = setTimeout(_charFilterChanged, 300);
  });
  document.getElementById('ul-user-id')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') lookupUser();
  });
  window.addEventListener('hashchange', () => {
    const want = location.hash.replace('#', '');
    if (want) showSection(want);
  });
  loadWhoami();
});

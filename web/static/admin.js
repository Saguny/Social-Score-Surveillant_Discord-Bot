function v(id) { return document.getElementById(id).value.trim(); }

function log(cmd, output, ok) {
  const term = document.getElementById('terminal');
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
  if (!args.every(a => a !== '')) {
    log(command, 'Missing required arguments.', false);
    return;
  }
  const res = await fetch('/api/admin/command', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({command, args})
  });
  if (res.status === 401 || res.status === 403) { location.href = '/social-credit/login?next=/social-credit/admin'; return; }
  const data = await res.json();
  log(command + (args.length ? ' ' + args.join(' ') : ''), data.output || data.error, res.ok && !data.error);
}

function confirmRun(command, args, msg) {
  if (confirm(msg)) run(command, args);
}

async function lookupUser() {
  const userId = v('ul-user-id');
  const out = document.getElementById('ul-result');
  if (!userId) { out.innerHTML = '<div style="color:var(--red)">Enter a user ID.</div>'; return; }
  out.innerHTML = '<div style="color:var(--text-muted)">Looking up...</div>';

  const res = await fetch('/api/admin/user-lookup?user_id=' + encodeURIComponent(userId));
  if (res.status === 401 || res.status === 403) { location.href = '/social-credit/login?next=/social-credit/admin'; return; }
  const data = await res.json();
  if (data.error) { out.innerHTML = `<div style="color:var(--red)">${_esc(data.error)}</div>`; return; }

  const header = `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
      <img src="${data.avatar_url}" style="width:32px;height:32px;border-radius:50%">
      <strong>${_esc(data.username)}</strong>
      <span style="color:var(--text-faint)">(${data.user_id})</span>
    </div>
  `;

  if (!data.guilds.length) {
    out.innerHTML = header +
      `<div style="color:var(--text-faint);font-size:.85rem;margin-bottom:8px">Not currently a member of any server the bot shares.</div>`;
    return;
  }

  const rows = data.guilds.map(g => `
    <div class="row g-2 align-items-end mb-2" data-guild="${g.guild_id}">
      <div class="col-auto" style="min-width:220px">
        <strong>${_esc(g.guild_name)}</strong>
        <div id="ul-sub-${g.guild_id}" style="font-size:.75rem;color:var(--text-faint)">Score ${g.score.toFixed(2)} &middot; &yen;${g.yuan.toLocaleString()}</div>
      </div>
      <div class="col-2"><input type="number" class="form-control form-control-sm ul-amt" placeholder="+/- amount"></div>
      <div class="col-auto"><button class="btn btn-run btn-sm px-3" onclick="applyYuan('${g.guild_id}','${data.user_id}', this)">APPLY</button></div>
    </div>
  `).join('');

  out.innerHTML = header + rows;
}

async function applyYuan(guildId, userId, btn) {
  const row = btn.closest('[data-guild]');
  const amtInput = row.querySelector('.ul-amt');
  const amount = parseInt(amtInput.value, 10);
  if (!amount) { alert('Enter a non-zero amount.'); return; }

  const res = await fetch('/api/admin/user-yuan-adjust', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ guild_id: guildId, user_id: userId, amount }),
  });
  if (res.status === 401 || res.status === 403) { location.href = '/social-credit/login?next=/social-credit/admin'; return; }
  const data = await res.json();
  if (data.error) { alert(data.error); return; }

  const sub = document.getElementById('ul-sub-' + guildId);
  sub.innerHTML = sub.innerHTML.replace(/&yen;[\d,]+/, '&yen;' + data.yuan.toLocaleString());
  amtInput.value = '';
}

let ebFields = [];

function _esc(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function addEmbedField() {
  if (ebFields.length >= 25) return;
  ebFields.push({ name: '', value: '', inline: false });
  renderEmbedFields();
  renderEmbedPreview();
}

function removeEmbedField(i) {
  ebFields.splice(i, 1);
  renderEmbedFields();
  renderEmbedPreview();
}

function updateEmbedField(i, key, val) {
  ebFields[i][key] = val;
  renderEmbedPreview();
}

function renderEmbedFields() {
  const container = document.getElementById('eb-fields');
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
      <div class="col-auto"><button class="btn btn-danger-soft btn-sm" onclick="removeEmbedField(${i})">&times;</button></div>
    `;
    container.appendChild(row);
  });
}

function renderEmbedPreview() {
  const title = v('eb-title');
  const desc = v('eb-desc');
  const color = document.getElementById('eb-color').value;
  const image = v('eb-image');
  const thumb = v('eb-thumb');
  const btnLabel = v('eb-btn-label');
  const btnUrl = v('eb-btn-url');

  const fieldsHtml = ebFields.filter(f => f.name && f.value).map(f =>
    `<div style="flex:${f.inline ? '0 0 auto;min-width:120px' : '1 0 100%'};margin-top:8px">
       <div style="font-weight:600;font-size:.8rem">${_esc(f.name)}</div>
       <div style="font-size:.8rem;color:var(--text-muted);white-space:pre-wrap">${_esc(f.value)}</div>
     </div>`
  ).join('');

  document.getElementById('eb-preview').innerHTML = `
    <div style="border-left:4px solid ${color};background:var(--bg-recessed);border-radius:4px;padding:12px 14px;display:flex;gap:12px">
      <div style="flex:1;min-width:0">
        ${title ? `<div style="font-weight:700;margin-bottom:4px">${_esc(title)}</div>` : ''}
        ${desc ? `<div style="font-size:.85rem;color:var(--text-muted);white-space:pre-wrap">${_esc(desc)}</div>` : ''}
        <div style="display:flex;flex-wrap:wrap;gap:8px">${fieldsHtml}</div>
        ${image ? `<img src="${image}" style="max-width:100%;border-radius:4px;margin-top:10px" onerror="this.style.display='none'">` : ''}
        ${btnLabel && btnUrl ? `<div style="margin-top:10px"><span style="display:inline-block;padding:6px 14px;border:1px solid var(--text-muted);border-radius:4px;font-size:.8rem;color:var(--text)">&#128279; ${_esc(btnLabel)}</span></div>` : ''}
        <div style="font-size:.7rem;color:var(--text-faint);margin-top:10px">GLORY TO THE CCP! (footer added automatically)</div>
      </div>
      ${thumb ? `<img src="${thumb}" style="width:64px;height:64px;border-radius:4px;object-fit:cover" onerror="this.style.display='none'">` : ''}
    </div>
  `;
}

async function loadGuildListForBroadcast() {
  const res = await fetch('/api/admin/guild-list');
  if (res.status === 401 || res.status === 403) { location.href = '/social-credit/login?next=/social-credit/admin'; return; }
  const data = await res.json();
  const sel = document.getElementById('eb-target');
  sel.innerHTML = '<option value="all">All servers</option>';
  (data.guilds || []).forEach(g => {
    const opt = document.createElement('option');
    opt.value = g.id;
    opt.textContent = `${g.name} (${g.member_count} members)`;
    sel.appendChild(opt);
  });
}

async function sendBroadcastEmbed() {
  const title = v('eb-title');
  const desc = v('eb-desc');
  if (!title && !desc) { alert('Add a title or description first.'); return; }

  const sel = document.getElementById('eb-target');
  const target = sel.value;
  const targetLabel = sel.selectedOptions[0].textContent;

  if (!confirm(`Send this embed to ${targetLabel}? This sends once, immediately, and cannot be undone.`)) return;

  const payload = {
    target,
    title,
    description: desc,
    color: document.getElementById('eb-color').value.replace('#', ''),
    image_url: v('eb-image'),
    thumbnail_url: v('eb-thumb'),
    fields: ebFields.filter(f => f.name && f.value),
    button_label: v('eb-btn-label'),
    button_url: v('eb-btn-url'),
  };

  const out = document.getElementById('eb-result');
  out.style.color = 'var(--text-muted)';
  out.textContent = 'Sending...';

  const res = await fetch('/api/admin/broadcast-embed', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (res.status === 401 || res.status === 403) { location.href = '/social-credit/login?next=/social-credit/admin'; return; }
  const data = await res.json();

  if (data.error) {
    out.style.color = 'var(--red)';
    out.textContent = 'Error: ' + data.error;
    return;
  }

  out.style.color = 'var(--text)';
  out.textContent = `Sent to ${data.sent}/${data.total} guild(s):\n` +
    data.results.map(r => `${r.guild_name} (${r.guild_id}) -- ${r.status}${r.detail ? ': ' + r.detail : ''}`).join('\n');
}

async function loadAnnouncement() {
  const res = await fetch('/api/announcement');
  const data = await res.json();
  document.getElementById('an-enabled').checked = !!data.enabled;
  document.getElementById('an-severity').value = data.severity || 'info';
  document.getElementById('an-message').value = data.message || '';
  renderAnnouncementPreview();
}

function renderAnnouncementPreview() {
  const enabled = document.getElementById('an-enabled').checked;
  const severity = document.getElementById('an-severity').value;
  const message = v('an-message');
  const preview = document.getElementById('an-preview');
  if (!enabled || !message) {
    preview.innerHTML = '<div style="color:var(--text-faint);font-size:.75rem">Banner hidden (disabled or empty message).</div>';
    return;
  }
  preview.innerHTML = `<div class="announce-banner announce-${severity}">${_esc(message)}</div>`;
}

async function saveAnnouncement() {
  const payload = {
    enabled: document.getElementById('an-enabled').checked,
    severity: document.getElementById('an-severity').value,
    message: v('an-message'),
  };
  const out = document.getElementById('an-result');
  out.style.color = 'var(--text-muted)';
  out.textContent = 'Saving...';

  const res = await fetch('/api/admin/announcement', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (res.status === 401 || res.status === 403) { location.href = '/social-credit/login?next=/social-credit/admin'; return; }
  const data = await res.json();
  if (data.error) {
    out.style.color = 'var(--red)';
    out.textContent = 'Error: ' + data.error;
    return;
  }
  out.style.color = 'var(--green)';
  out.textContent = 'Saved. Live on the dashboard immediately, no restart needed.';
}

let _voteChart = null;

function _formatBucket(ts, period) {
  const d = new Date(ts * 1000);
  if (period === '1D') return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  return d.toLocaleDateString([], {month: 'short', day: 'numeric'});
}

async function loadVoteChart(period) {
  document.querySelectorAll('[data-period]').forEach(b => {
    b.classList.toggle('active', b.dataset.period === period);
  });

  const res = await fetch('/api/admin/topgg-votes?period=' + period);
  if (res.status === 401 || res.status === 403) { location.href = '/social-credit/login?next=/social-credit/admin'; return; }
  const data = await res.json();

  document.getElementById('vote-total').textContent =
    data.total + ' vote' + (data.total === 1 ? '' : 's') + ' · ' + period;

  const labels = data.buckets.map(b => _formatBucket(b.bucket, period));
  const counts = data.buckets.map(b => b.votes);

  const ctx = document.getElementById('vote-chart').getContext('2d');
  if (_voteChart) _voteChart.destroy();
  _voteChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Votes',
        data: counts,
        backgroundColor: '#E6E6FA',
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        y: { beginAtZero: true, ticks: { precision: 0 } },
      },
    },
  });
}

// ── Requests (character submission review) ────────────────────────────────────

async function loadSubmitSettings() {
  const r = await fetch('/api/admin/submit-settings');
  if (!r.ok) return;
  const data = await r.json();
  const el = document.getElementById('submit-limit-val');
  if (el) el.value = data.submit_daily_limit ?? 25;
}

async function saveSubmitLimit() {
  const el  = document.getElementById('submit-limit-val');
  const res = document.getElementById('submit-limit-result');
  const val = parseInt(el?.value, 10);
  if (!el || isNaN(val) || val < 1 || val > 1000) {
    if (res) { res.style.color = 'var(--red)'; res.textContent = 'Enter a number between 1 and 1000.'; }
    return;
  }
  const r = await fetch('/api/admin/submit-settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ submit_daily_limit: val }),
  });
  const body = await r.json().catch(() => ({}));
  if (r.ok) {
    if (res) { res.style.color = 'var(--green)'; res.textContent = `Saved — limit is now ${val}/day.`; }
  } else {
    if (res) { res.style.color = 'var(--red)'; res.textContent = 'Error: ' + (body.error || r.status); }
  }
}

let _reqSort = 'votes';

function setReqSort(sort) {
  _reqSort = sort;
  document.getElementById('sort-votes').classList.toggle('active', sort === 'votes');
  document.getElementById('sort-newest').classList.toggle('active', sort === 'newest');
  loadPendingRequests();
}

async function loadPendingRequests() {
  const $list = document.getElementById('req-list');
  if (!$list) return;
  $list.innerHTML = '<div style="color:var(--text-muted);font-size:.82rem">Loading…</div>';
  const r = await fetch('/api/admin/requests?sort=' + _reqSort);
  if (!r.ok) { $list.innerHTML = '<div style="color:var(--red)">Failed to load.</div>'; return; }
  const data = await r.json();
  const rows = data.requests || [];
  const badge = document.getElementById('req-badge');
  if (badge) {
    if (rows.length) { badge.textContent = rows.length; badge.style.display = ''; }
    else badge.style.display = 'none';
  }
  if (!rows.length) {
    $list.innerHTML = '<div style="color:var(--text-muted);font-size:.82rem">No pending requests.</div>';
    return;
  }
  const RARITIES  = ['legendary','epic','rare','uncommon','common'];
  const GENDERS   = ['male','female','other'];
  const FACTIONS  = ['reds','strongmen','conquerors','icons','capitalists','wildcards'];
  $list.innerHTML = rows.map(req => {
    const curRarity  = req.override_rarity  || '';
    const curGender  = req.override_gender  || '';
    const curFaction = req.override_faction || '';
    const curTitle   = req.override_title   || '';
    const curUrls    = (req.override_image_urls || []).join('\n');
    const wikiLang   = req.wiki_lang || 'en';
    const badges    = [
      curRarity  ? `<span class="req-override-badge">${_re(curRarity)}</span>`  : '',
      curGender  ? `<span class="req-override-badge">${_re(curGender)}</span>`  : '',
      curFaction ? `<span class="req-override-badge">${_re(curFaction)}</span>` : '',
      curTitle   ? `<span class="req-override-badge" title="${_re(curTitle)}">${_re(curTitle.slice(0,20))}${curTitle.length>20?'…':''}</span>` : '',
      (req.override_image_urls || []).length ? `<span class="req-override-badge">${req.override_image_urls.length} img</span>` : '',
    ].join('');
    const rarityOpts  = RARITIES.map(v  => `<option value="${v}"${curRarity===v?' selected':''}>${v}</option>`).join('');
    const genderOpts  = GENDERS.map(v   => `<option value="${v}"${curGender===v?' selected':''}>${v}</option>`).join('');
    const factionOpts = FACTIONS.map(v  => `<option value="${v}"${curFaction===v?' selected':''}>${v}</option>`).join('');
    return `
      <div class="req-row" id="req-${req.id}">
        <div class="req-top">
          <div class="req-meta">
            <span class="req-title">${_re(req.wiki_title)}</span>
            <span class="req-votes">${req.vote_count || 0} vote${(req.vote_count || 0) !== 1 ? 's' : ''}</span>
            <span class="req-by">@${_re(req.discord_username)}</span>
            <a href="https://${wikiLang}.wikipedia.org/wiki/${encodeURIComponent(req.wiki_slug)}" target="_blank" rel="noopener" class="req-wiki">Wikipedia ↗</a>
            ${badges}
          </div>
          <div class="req-actions">
            <button class="req-btn req-approve" onclick="approveRequest(${req.id}, '${_re(req.wiki_title)}')">✓ Approve</button>
            <button class="req-btn req-reject"  onclick="toggleReqReject(${req.id})">✗ Reject</button>
            <button class="req-btn req-ban"     onclick="banSubmitter(${req.id}, ${req.discord_id})">⛔ Ban</button>
            <button class="req-btn req-edit"    onclick="toggleReqEdit(${req.id})">✏ Edit</button>
          </div>
        </div>
        <div class="req-edit-panel" id="req-edit-${req.id}" style="display:none">
          <div class="row g-2 align-items-end">
            <div class="col-auto">
              <label class="form-label">Faction</label>
              <select class="form-select form-select-sm" id="req-edit-faction-${req.id}" style="width:135px">
                <option value="">— auto —</option>
                ${factionOpts}
              </select>
            </div>
            <div class="col-auto">
              <label class="form-label">Rarity</label>
              <select class="form-select form-select-sm" id="req-edit-rarity-${req.id}" style="width:135px">
                <option value="">— auto —</option>
                ${rarityOpts}
              </select>
            </div>
            <div class="col-auto">
              <label class="form-label">Gender</label>
              <select class="form-select form-select-sm" id="req-edit-gender-${req.id}" style="width:115px">
                <option value="">— auto —</option>
                ${genderOpts}
              </select>
            </div>
            <div class="col-auto">
              <button class="btn btn-run btn-sm px-3" onclick="saveReqEdit(${req.id})">SAVE</button>
            </div>
            <div class="col-auto" id="req-edit-result-${req.id}" style="font-size:.75rem"></div>
          </div>
          <div class="mt-2">
            <label class="form-label">Description / Title <span style="color:var(--text-muted);font-weight:400">(shown on card)</span></label>
            <input type="text" class="form-control form-control-sm" id="req-edit-title-${req.id}" maxlength="100" value="${_re(curTitle)}" placeholder="e.g. German YouTuber">
          </div>
          <div class="mt-2">
            <label class="form-label">Image URLs — one per line (leave blank to use pipeline)</label>
            <textarea class="form-control form-control-sm" id="req-edit-urls-${req.id}" rows="3" style="font-size:.75rem;font-family:monospace">${_re(curUrls)}</textarea>
          </div>
        </div>
        <div class="req-reject-panel" id="req-reject-${req.id}" style="display:none">
          <label style="font-size:.75rem;color:var(--text-muted);display:block;margin-bottom:.3rem">Reason for rejecting <span style="opacity:.6">(optional · will be sent to the submitter via DM)</span></label>
          <textarea class="form-control form-control-sm" id="req-reject-reason-${req.id}" rows="2" style="font-size:.75rem" placeholder="e.g. Not a real historical figure, image quality too low…" maxlength="500"></textarea>
          <div style="display:flex;gap:.4rem;margin-top:.4rem">
            <button class="req-btn req-reject" onclick="confirmRejectRequest(${req.id})">✗ Confirm Reject</button>
            <button class="req-btn req-cancel" onclick="toggleReqReject(${req.id})">Cancel</button>
          </div>
        </div>
      </div>`;
  }).join('');
}

function toggleReqEdit(id) {
  const panel = document.getElementById('req-edit-' + id);
  if (panel) panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
}

function toggleReqReject(id) {
  const panel = document.getElementById('req-reject-' + id);
  if (!panel) return;
  const opening = panel.style.display === 'none';
  panel.style.display = opening ? 'block' : 'none';
  if (opening) {
    const ta = document.getElementById('req-reject-reason-' + id);
    if (ta) { ta.value = ''; ta.focus(); }
  }
}

async function confirmRejectRequest(requestId) {
  const ta = document.getElementById('req-reject-reason-' + requestId);
  const reason = ta ? ta.value.trim() : '';
  await _doReject(requestId, reason);
}

async function _doReject(requestId, reason) {
  const r = await fetch('/api/admin/requests/reject', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId, reason }),
  });
  const body = await r.json().catch(() => ({}));
  if (r.ok) {
    const row = document.getElementById('req-' + requestId);
    if (row) row.remove();
  } else {
    alert('Error: ' + (body.error || r.status));
  }
}

async function saveReqEdit(id) {
  const faction   = document.getElementById('req-edit-faction-' + id).value;
  const rarity    = document.getElementById('req-edit-rarity-' + id).value;
  const gender    = document.getElementById('req-edit-gender-' + id).value;
  const title     = (document.getElementById('req-edit-title-' + id).value || '').trim();
  const urlsRaw   = document.getElementById('req-edit-urls-' + id).value;
  const imageUrls = urlsRaw.split('\n').map(u => u.trim()).filter(Boolean);
  const out       = document.getElementById('req-edit-result-' + id);

  out.style.color = 'var(--text-muted)';
  out.textContent = 'Saving…';

  const r = await fetch('/api/admin/requests/edit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: id, faction: faction || null, rarity: rarity || null, gender: gender || null, title: title || null, image_urls: imageUrls }),
  });
  if (r.status === 401 || r.status === 403) { location.href = '/social-credit/login?next=/social-credit/admin'; return; }
  const body = await r.json().catch(() => ({}));
  if (r.ok) {
    out.style.color = 'var(--green)';
    out.textContent = 'Saved.';
  } else {
    out.style.color = 'var(--red)';
    out.textContent = 'Error: ' + (body.error || r.status);
  }
}

function _re(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function approveRequest(requestId, title) {
  const $panel = document.getElementById('req-pipeline');
  const $log   = document.getElementById('req-pipeline-log');
  if (!$panel || !$log) return;

  if (!confirm(`Approve "${title}" and run the full gacha pipeline?`)) return;

  $panel.style.display = 'block';
  $log.innerHTML = '';
  document.getElementById('req-pipeline-title').textContent = title;

  function addLine(msg, ok) {
    const d = document.createElement('div');
    d.className = ok === false ? 'pipe-line pipe-err' : 'pipe-line pipe-ok';
    d.textContent = msg;
    $log.appendChild(d);
    $log.scrollTop = $log.scrollHeight;
  }

  const res = await fetch('/api/admin/requests/approve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId }),
  });

  if (res.headers.get('content-type')?.includes('event-stream')) {
    const reader = res.body.getReader();
    const dec    = new TextDecoder();
    let buf = '';
    let succeeded = false;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const part of parts) {
        const line = part.replace(/^data: /, '');
        try {
          const ev = JSON.parse(line);
          addLine((ev.ok === false ? '⚠ ' : '✓ ') + ev.msg, ev.ok !== false);
          if (ev.stage === 'done' && ev.ok !== false) succeeded = true;
        } catch (_) {}
      }
    }
    if (succeeded) {
      const row = document.getElementById('req-' + requestId);
      if (row) row.remove();
    }
  } else {
    const body = await res.json().catch(() => ({}));
    addLine('Error: ' + (body.error || res.status), false);
  }
}

// ── Live log viewer ───────────────────────────────────────────────────────────

let _logEs = null;
let _logSvc = null;
const _LOG_MAX = 1000;

function switchLogService(svc) {
  document.querySelectorAll('.log-svc-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.svc === svc);
  });
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

  _logEs.onopen = () => {
    status.textContent = svc + ' \xb7 live';
    status.className = 'log-status-bar log-status-live';
  };

  _logEs.onmessage = (e) => {
    try {
      const d = JSON.parse(e.data);
      _appendLogLine(panel, d.line || '');
    } catch (_) {}
  };

  _logEs.onerror = () => {
    status.textContent = svc + ' \xb7 disconnected — retrying…';
    status.className = 'log-status-bar log-status-err';
  };
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

function clearLog() {
  const panel = document.getElementById('log-panel');
  if (panel) panel.innerHTML = '';
}

async function banSubmitter(requestId, discordId) {
  if (!confirm('Ban this submitter? They will no longer be able to submit requests.')) return;
  const r = await fetch('/api/admin/requests/ban', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ discord_id: discordId }),
  });
  if (r.ok) {
    await _doReject(requestId, '');
    alert('Submitter banned.');
  } else {
    const body = await r.json().catch(() => ({}));
    alert('Error: ' + (body.error || r.status));
  }
}

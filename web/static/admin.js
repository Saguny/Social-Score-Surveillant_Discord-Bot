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
  if (res.status === 401 || res.status === 403) { location.href = '/login?next=/admin'; return; }
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
  if (res.status === 401 || res.status === 403) { location.href = '/login?next=/admin'; return; }
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
  if (res.status === 401 || res.status === 403) { location.href = '/login?next=/admin'; return; }
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
  if (res.status === 401 || res.status === 403) { location.href = '/login?next=/admin'; return; }
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
  if (res.status === 401 || res.status === 403) { location.href = '/login?next=/admin'; return; }
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

let _voteChart = null;

function _formatBucket(ts, period) {
  const d = new Date(ts * 1000);
  if (period === '1D') return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  return d.toLocaleDateString([], {month: 'short', day: 'numeric'});
}

async function loadVoteChart(period) {
  document.querySelectorAll('#vote-period-group button').forEach(b => {
    b.classList.toggle('active', b.dataset.period === period);
  });

  const res = await fetch('/api/admin/topgg-votes?period=' + period);
  if (res.status === 401 || res.status === 403) { location.href = '/login?next=/admin'; return; }
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

import webbrowser
from aiohttp import web
from database.db import Database

PORT = 8080
_runner = None

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Social Credit Dashboard</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  :root {
    --navy:  #111844;
    --blue:  #4B5694;
    --mid:   #7288AE;
    --beige: #EAE0CF;
  }
  body { background: var(--navy); color: var(--beige); font-family: 'Segoe UI', sans-serif; }
  .navbar { background: var(--navy); border-bottom: 1px solid var(--blue); }
  .navbar-brand { color: var(--beige) !important; letter-spacing: 2px; font-weight: 700; }
  h1, h2, h5 { color: var(--beige); }
  .guild-card {
    background: #1a2356;
    border: 1px solid var(--blue);
    border-radius: 8px;
    cursor: pointer;
    transition: border-color .2s, transform .15s;
  }
  .guild-card:hover { background: var(--beige); border-color: var(--beige); color: var(--navy); transform: translateY(-2px); }
  .guild-card:hover div[style*="color:var(--mid)"] { color: var(--blue) !important; }
  .badge-positive { background: #2a5c3f; color: #7dffb3; }
  .badge-negative { background: #5c1a1a; color: #ff7d7d; }
  .badge-neutral  { background: #2a2f4a; color: var(--mid); }
  .log-row td { background: #111844 !important; color: var(--beige) !important; border-color: #1e2a50 !important; font-size: .875rem; vertical-align: middle; }
  .log-row:hover td { background: var(--beige) !important; color: var(--navy) !important; }
  .log-row td[style*="color:var(--mid)"] { color: var(--mid) !important; }
  .log-row:hover td[style*="color:var(--mid)"] { color: var(--blue) !important; }
  #log-table { color: var(--beige); }
  #log-table thead th { background: #0d1535; color: var(--mid); border-color: var(--blue) !important; font-size: .8rem; text-transform: uppercase; letter-spacing: 1px; }
  .content-cell { max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .back-btn { color: var(--mid); cursor: pointer; }
  .back-btn:hover { color: var(--beige); }
  .spinner-wrapper { display: flex; justify-content: center; padding: 3rem; }
  #no-guilds { display: none; }
  #guild-view { display: none; }
  .auto-refresh-label { color: var(--mid); font-size: .8rem; }
  .form-check-input:checked { background-color: var(--blue); border-color: var(--blue); }
  .page-meta { color: var(--mid); font-size: .8rem; }
  .load-more-btn { border-color: var(--blue); color: var(--mid); background: transparent; }
  .load-more-btn:hover { background: var(--blue); color: var(--beige); }
  ::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-track { background: var(--navy); } ::-webkit-scrollbar-thumb { background: var(--blue); border-radius: 3px; }
</style>
</head>
<body>

<nav class="navbar px-4 py-3 mb-4">
  <span class="navbar-brand">&#x4e2d;&#x534e;&#x4eba;&#x6c11;&#x5171;&#x548c;&#x56fd; &nbsp;&middot;&nbsp; SOCIAL CREDIT DASHBOARD</span>
  <span class="page-meta" id="nav-meta"></span>
</nav>

<div class="container-fluid px-4">

  <!-- Guild Picker -->
  <div id="guild-view-picker">
    <h5 class="mb-3">SELECT SERVER</h5>
    <div id="spinner-guilds" class="spinner-wrapper">
      <div class="spinner-border" style="color:var(--mid)" role="status"></div>
    </div>
    <div id="no-guilds" class="text-center py-5" style="color:var(--mid)">
      No servers have enabled web consent.<br>
      <small>Use <code>ccp webconsent on</code> in Discord to allow logging.</small>
    </div>
    <div id="guild-cards" class="row g-3"></div>
  </div>

  <!-- Log View -->
  <div id="guild-view">
    <div class="d-flex align-items-center gap-3 mb-3">
      <span class="back-btn" onclick="showPicker()">&#8592; Back</span>
      <h5 class="mb-0" id="guild-title"></h5>
      <div class="ms-auto d-flex align-items-center gap-3">
        <div class="form-check form-switch mb-0">
          <input class="form-check-input" type="checkbox" id="auto-refresh" checked>
          <label class="form-check-label auto-refresh-label" for="auto-refresh">Auto-refresh</label>
        </div>
        <span class="page-meta" id="log-count"></span>
      </div>
    </div>
    <div class="table-responsive">
      <table class="table table-borderless" id="log-table">
        <thead>
          <tr>
            <th>TIME</th>
            <th>USER</th>
            <th>MESSAGE</th>
            <th>REASON</th>
            <th class="text-end">DELTA</th>
          </tr>
        </thead>
        <tbody id="log-body"></tbody>
      </table>
    </div>
    <div id="spinner-logs" class="spinner-wrapper" style="display:none">
      <div class="spinner-border" style="color:var(--mid)" role="status"></div>
    </div>
    <div class="text-center mt-2 mb-5" id="load-more-wrapper" style="display:none">
      <button class="btn load-more-btn px-4" onclick="loadMore()">Load more</button>
    </div>
  </div>

</div>

<script>
let currentGuildId = null;
let currentGuildName = '';
let oldestId = null;
let refreshTimer = null;
let knownIds = new Set();

function fmt(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleString([], {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
}

function deltaBadge(delta) {
  if (delta > 0) return `<span class="badge badge-positive">+${delta.toFixed(2)}</span>`;
  if (delta < 0) return `<span class="badge badge-negative">${delta.toFixed(2)}</span>`;
  return `<span class="badge badge-neutral">0.00</span>`;
}

function escape(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function loadGuilds() {
  const res = await fetch('/api/guilds');
  const guilds = await res.json();
  document.getElementById('spinner-guilds').style.display = 'none';
  const container = document.getElementById('guild-cards');
  if (!guilds.length) { document.getElementById('no-guilds').style.display = 'block'; return; }
  guilds.forEach(g => {
    const col = document.createElement('div');
    col.className = 'col-auto';
    col.innerHTML = `<div class="guild-card p-4" onclick="openGuild('${g.guild_id}', '${escape(g.guild_name || g.guild_id)}')">
      <div style="font-size:1.1rem;font-weight:600">${escape(g.guild_name || 'Server')}</div>
      <div style="color:var(--mid);font-size:.8rem;margin-top:4px">${g.guild_id}</div>
    </div>`;
    container.appendChild(col);
  });
}

async function openGuild(guildId, guildName) {
  currentGuildId = guildId;
  currentGuildName = guildName;
  oldestId = null;
  knownIds = new Set();
  document.getElementById('log-body').innerHTML = '';
  document.getElementById('guild-title').textContent = guildName;
  document.getElementById('guild-view-picker').style.display = 'none';
  document.getElementById('guild-view').style.display = 'block';
  document.getElementById('nav-meta').textContent = guildName;
  await fetchLogs();
  scheduleRefresh();
}

function showPicker() {
  clearTimeout(refreshTimer);
  currentGuildId = null;
  document.getElementById('guild-view').style.display = 'none';
  document.getElementById('guild-view-picker').style.display = 'block';
  document.getElementById('nav-meta').textContent = '';
}

async function fetchLogs(before = null, prepend = false) {
  let url = `/api/guild/${currentGuildId}/logs?limit=50`;
  if (before) url += `&before=${before}`;
  const res = await fetch(url);
  const logs = await res.json();

  if (!before) {
    const newLogs = logs.filter(r => !knownIds.has(r.id));
    if (newLogs.length) prependRows(newLogs.reverse());
  } else {
    appendRows(logs);
  }

  if (logs.length === 50) {
    oldestId = logs[logs.length - 1].id;
    document.getElementById('load-more-wrapper').style.display = 'block';
  } else {
    document.getElementById('load-more-wrapper').style.display = 'none';
  }
  document.getElementById('log-count').textContent = `${knownIds.size} entries`;
}

function makeRow(r) {
  knownIds.add(r.id);
  const tr = document.createElement('tr');
  tr.className = 'log-row';
  tr.style.background = 'transparent';
  tr.innerHTML = `
    <td style="color:var(--mid);white-space:nowrap">${fmt(r.timestamp)}</td>
    <td style="white-space:nowrap;font-weight:500">${escape(r.username)}</td>
    <td class="content-cell" title="${escape(r.content)}">${escape(r.content)}</td>
    <td style="color:var(--mid)">${escape(r.reason)}</td>
    <td class="text-end">${deltaBadge(r.delta)}</td>
  `;
  return tr;
}

function prependRows(rows) {
  const tbody = document.getElementById('log-body');
  rows.forEach(r => tbody.insertBefore(makeRow(r), tbody.firstChild));
}

function appendRows(rows) {
  const tbody = document.getElementById('log-body');
  rows.forEach(r => tbody.appendChild(makeRow(r)));
}

function loadMore() {
  if (oldestId) fetchLogs(oldestId);
}

function scheduleRefresh() {
  clearTimeout(refreshTimer);
  if (!document.getElementById('auto-refresh').checked || !currentGuildId) return;
  refreshTimer = setTimeout(async () => {
    await fetchLogs();
    scheduleRefresh();
  }, 5000);
}

document.getElementById('auto-refresh').addEventListener('change', scheduleRefresh);

loadGuilds();
</script>
</body>
</html>"""


async def _handle_index(request):
    return web.Response(text=HTML, content_type="text/html")


async def _handle_guilds(request):
    db = request.app["db"]
    rows = await db.get_guilds_with_consent()
    return web.json_response([{"guild_id": str(r["guild_id"]), "guild_name": r["guild_name"]} for r in rows])


async def _handle_logs(request):
    db = request.app["db"]
    gid = int(request.match_info["guild_id"])
    limit = int(request.rel_url.query.get("limit", 50))
    before = request.rel_url.query.get("before")
    rows = await db.get_message_logs(gid, limit=limit, before=int(before) if before else None)
    return web.json_response([
        {
            "id": r["id"],
            "guild_id": str(r["guild_id"]),
            "user_id": str(r["user_id"]),
            "username": r["username"],
            "content": r["content"],
            "delta": r["delta"],
            "reason": r["reason"],
            "timestamp": r["timestamp"],
        }
        for r in rows
    ])


async def start_web_server(db: Database):
    global _runner
    if _runner:
        print(f"Web dashboard already running at http://localhost:{PORT}")
        webbrowser.open(f"http://localhost:{PORT}")
        return

    app = web.Application()
    app["db"] = db
    app.router.add_get("/", _handle_index)
    app.router.add_get("/api/guilds", _handle_guilds)
    app.router.add_get("/api/guild/{guild_id}/logs", _handle_logs)

    _runner = web.AppRunner(app)
    await _runner.setup()
    site = web.TCPSite(_runner, "localhost", PORT)
    await site.start()
    print(f"Web dashboard running at http://localhost:{PORT}")
    webbrowser.open(f"http://localhost:{PORT}")

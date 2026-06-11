import os
import asyncio
import webbrowser
from aiohttp import web

PORT = int(os.getenv("PORT", 8080))
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
  .nav-link { color: var(--mid) !important; font-size: .85rem; letter-spacing: 1px; }
  .nav-link:hover, .nav-link.active { color: var(--beige) !important; }
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
  <div class="d-flex gap-3 align-items-center">
    <a class="nav-link active" href="/">LOGS</a>
    <a class="nav-link" href="/admin">ADMIN</a>
    <span class="page-meta" id="nav-meta"></span>
  </div>
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


ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Admin Console · Social Credit</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  :root { --navy:#111844; --blue:#4B5694; --mid:#7288AE; --beige:#EAE0CF; --green:#7dffb3; --red:#ff7d7d; }
  body { background:var(--navy); color:var(--beige); font-family:'Segoe UI',sans-serif; }
  .navbar { background:var(--navy); border-bottom:1px solid var(--blue); }
  .navbar-brand { color:var(--beige)!important; letter-spacing:2px; font-weight:700; }
  .nav-link { color:var(--mid)!important; font-size:.85rem; letter-spacing:1px; }
  .nav-link:hover,.nav-link.active { color:var(--beige)!important; }
  .card-panel { background:#0d1535; border:1px solid var(--blue); border-radius:8px; }
  .form-control, .form-select {
    background:#1a2356; border:1px solid var(--blue); color:var(--beige);
    font-size:.875rem;
  }
  .form-control:focus, .form-select:focus {
    background:#1a2356; border-color:var(--beige); color:var(--beige); box-shadow:none;
  }
  .form-control::placeholder { color:var(--mid); }
  .form-label { color:var(--mid); font-size:.75rem; text-transform:uppercase; letter-spacing:1px; margin-bottom:4px; }
  .btn-run { background:var(--blue); border:none; color:var(--beige); font-weight:600; letter-spacing:1px; }
  .btn-run:hover { background:#5a67a8; color:var(--beige); }
  .btn-run:disabled { opacity:.4; }
  .btn-danger-soft { background:#5c1a1a; border:1px solid #8b2020; color:var(--red); }
  .btn-danger-soft:hover { background:#7a2020; color:var(--red); }
  #terminal {
    background:#060c20; border:1px solid var(--blue); border-radius:6px;
    font-family:'Courier New',monospace; font-size:.8rem;
    min-height:260px; max-height:480px; overflow-y:auto;
    padding:12px 16px; color:var(--beige);
  }
  .t-prompt { color:var(--mid); }
  .t-out { color:var(--beige); white-space:pre-wrap; }
  .t-ok  { color:var(--green); }
  .t-err { color:var(--red); }
  .cmd-section { border-bottom:1px solid #1e2a50; padding-bottom:16px; margin-bottom:16px; }
  .cmd-section:last-child { border-bottom:none; margin-bottom:0; padding-bottom:0; }
  ::-webkit-scrollbar{width:6px} ::-webkit-scrollbar-track{background:var(--navy)} ::-webkit-scrollbar-thumb{background:var(--blue);border-radius:3px}
  #token-gate { display:none; }
</style>
</head>
<body>

<nav class="navbar px-4 py-3 mb-4">
  <span class="navbar-brand">&#x4e2d;&#x534e;&#x4eba;&#x6c11;&#x5171;&#x548c;&#x56fd; &nbsp;&middot;&nbsp; SOCIAL CREDIT DASHBOARD</span>
  <div class="d-flex gap-3 align-items-center">
    <a class="nav-link" href="/">LOGS</a>
    <a class="nav-link active" href="/admin">ADMIN</a>
  </div>
</nav>

<div class="container px-4" style="max-width:860px">

  <!-- Auth gate -->
  <div id="auth-gate" class="card-panel p-4 mb-4">
    <div class="mb-3" style="color:var(--mid);font-size:.8rem;text-transform:uppercase;letter-spacing:1px">Admin Token</div>
    <div class="d-flex gap-2">
      <input type="password" id="token-input" class="form-control" placeholder="Enter ADMIN_TOKEN" style="max-width:320px">
      <button class="btn btn-run px-4" onclick="authenticate()">UNLOCK</button>
    </div>
    <div id="auth-err" class="mt-2" style="color:var(--red);font-size:.8rem;display:none">Invalid token.</div>
  </div>

  <div id="token-gate">

    <!-- Terminal output -->
    <div class="mb-3">
      <div style="color:var(--mid);font-size:.75rem;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Output</div>
      <div id="terminal"><span class="t-prompt">Ready.</span></div>
    </div>

    <!-- Commands -->
    <div class="card-panel p-4">

      <div class="cmd-section">
        <div class="row g-2 align-items-end">
          <div class="col-auto">
            <button class="btn btn-run px-4" onclick="run('sync')">SYNC SLASH COMMANDS</button>
          </div>
          <div class="col-auto">
            <button class="btn btn-run px-4" onclick="run('guilds')">LIST GUILDS</button>
          </div>
        </div>
      </div>

      <div class="cmd-section">
        <div class="row g-2 align-items-end">
          <div class="col-auto">
            <label class="form-label">Cog name</label>
            <input type="text" id="arg-cog" class="form-control" placeholder="cogs.scoring" style="width:200px">
          </div>
          <div class="col-auto">
            <button class="btn btn-run px-4" onclick="run('reload', [v('arg-cog')])">RELOAD COG</button>
          </div>
        </div>
      </div>

      <div class="cmd-section">
        <div class="row g-2 align-items-end">
          <div class="col-3">
            <label class="form-label">Guild ID</label>
            <input type="text" id="arg-fr-gid" class="form-control" placeholder="guild_id">
          </div>
          <div class="col-3">
            <label class="form-label">User ID</label>
            <input type="text" id="arg-fr-uid" class="form-control" placeholder="user_id">
          </div>
          <div class="col-auto">
            <button class="btn btn-run px-4" onclick="run('force_reset', [v('arg-fr-gid'), v('arg-fr-uid')])">FORCE RESET SCORE</button>
          </div>
        </div>
      </div>

      <div class="cmd-section">
        <div class="row g-2 align-items-end">
          <div class="col-3">
            <label class="form-label">Guild ID</label>
            <input type="text" id="arg-db-gid" class="form-control" placeholder="guild_id">
          </div>
          <div class="col-auto">
            <button class="btn btn-run btn-danger-soft px-4" onclick="run('db_reset', [v('arg-db-gid')])">DB RESET GUILD</button>
          </div>
        </div>
      </div>

      <div class="cmd-section">
        <div class="row g-2 align-items-end">
          <div class="col-auto">
            <button class="btn btn-danger-soft px-4" onclick="confirmRun('restart', [], 'Restart the bot?')">RESTART</button>
          </div>
          <div class="col-auto">
            <button class="btn btn-danger-soft px-4" onclick="confirmRun('shutdown', [], 'Shut down the bot?')">SHUTDOWN</button>
          </div>
        </div>
      </div>

    </div>
  </div>

</div>

<script>
let token = sessionStorage.getItem('admin_token') || '';
if (token) unlockUI();

function v(id) { return document.getElementById(id).value.trim(); }

function unlockUI() {
  document.getElementById('auth-gate').style.display = 'none';
  document.getElementById('token-gate').style.display = 'block';
}

async function authenticate() {
  const t = document.getElementById('token-input').value.trim();
  const res = await fetch('/api/admin/command', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({token: t, command: 'ping', args: []})
  });
  const data = await res.json();
  if (res.status === 403) {
    document.getElementById('auth-err').style.display = 'block';
    return;
  }
  token = t;
  sessionStorage.setItem('admin_token', token);
  document.getElementById('auth-err').style.display = 'none';
  unlockUI();
}

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
    body: JSON.stringify({token, command, args})
  });
  const data = await res.json();
  if (res.status === 403) {
    sessionStorage.removeItem('admin_token');
    location.reload();
    return;
  }
  log(command + (args.length ? ' ' + args.join(' ') : ''), data.output || data.error, res.ok && !data.error);
}

function confirmRun(command, args, msg) {
  if (confirm(msg)) run(command, args);
}

document.getElementById('token-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') authenticate();
});
</script>
</body>
</html>"""


async def _handle_index(request):
    return web.Response(text=HTML, content_type="text/html")


async def _handle_admin(request):
    return web.Response(text=ADMIN_HTML, content_type="text/html")


async def _handle_admin_command(request):
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token:
        return web.json_response({"error": "ADMIN_TOKEN not set on server"}, status=500)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    if body.get("token") != admin_token:
        return web.json_response({"error": "Forbidden"}, status=403)

    command = body.get("command", "")
    args = body.get("args", [])
    bot = request.app["bot"]

    if command == "ping":
        return web.json_response({"output": "ok"})

    elif command == "sync":
        await bot.tree.sync()
        return web.json_response({"output": "Slash commands synced."})

    elif command == "guilds":
        lines = [f"{g.id}  {g.name}  ({g.member_count} members)" for g in bot.guilds]
        return web.json_response({"output": "\n".join(lines) or "No guilds."})

    elif command == "reload":
        if not args:
            return web.json_response({"error": "Usage: reload <cog>"})
        try:
            await bot.reload_extension(args[0])
            return web.json_response({"output": f"{args[0]} reloaded."})
        except Exception as e:
            return web.json_response({"error": str(e)})

    elif command == "force_reset":
        if len(args) < 2:
            return web.json_response({"error": "Usage: force_reset <guild_id> <user_id>"})
        try:
            gid, uid = int(args[0]), int(args[1])
            user = await bot.db.get_user(gid, uid)
            delta = 750.0 - user["score"]
            await bot.db.update_score(gid, uid, delta, "admin force reset")
            return web.json_response({"output": f"User {uid} in guild {gid} reset to 750."})
        except Exception as e:
            return web.json_response({"error": str(e)})

    elif command == "db_reset":
        if not args:
            return web.json_response({"error": "Usage: db_reset <guild_id>"})
        try:
            gid = int(args[0])
            await bot.db.reset_guild_db(gid)
            return web.json_response({"output": f"Guild {gid} wiped."})
        except Exception as e:
            return web.json_response({"error": str(e)})

    elif command == "restart":
        asyncio.create_task(_delayed_restart(bot))
        return web.json_response({"output": "Restarting..."})

    elif command == "shutdown":
        asyncio.create_task(_delayed_shutdown(bot))
        return web.json_response({"output": "Shutting down..."})

    return web.json_response({"error": f"Unknown command: {command}"}, status=400)


async def _delayed_restart(bot):
    await asyncio.sleep(0.5)
    await bot.close()
    import os as _os
    _os._exit(42)


async def _delayed_shutdown(bot):
    await asyncio.sleep(0.5)
    await bot.close()


async def _handle_guilds(request):
    db = request.app["bot"].db
    rows = await db.get_guilds_with_consent()
    return web.json_response([{"guild_id": str(r["guild_id"]), "guild_name": r["guild_name"]} for r in rows])


async def _handle_logs(request):
    db = request.app["bot"].db
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


async def start_web_server(bot):
    global _runner
    if _runner:
        print(f"Web dashboard already running at http://localhost:{PORT}")
        return

    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", _handle_index)
    app.router.add_get("/admin", _handle_admin)
    app.router.add_post("/api/admin/command", _handle_admin_command)
    app.router.add_get("/api/guilds", _handle_guilds)
    app.router.add_get("/api/guild/{guild_id}/logs", _handle_logs)

    _runner = web.AppRunner(app)
    await _runner.setup()
    site = web.TCPSite(_runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web dashboard running on port {PORT}")

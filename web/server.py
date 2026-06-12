import os
import hmac
import time
import secrets
import asyncio
import webbrowser
from aiohttp import web

PORT = int(os.getenv("PORT", 8080))
_runner = None

_RATE_WINDOW  = 60 * 5
_RATE_LIMIT   = 5
_failed_attempts: dict[str, list[float]] = {}

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Social Credit Dashboard</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  :root { --navy:#120810; --blue:#97124B; --mid:#C4849A; --beige:#F5E6D3; --yellow:#F4E557; --orange:#F5A855; }
  body { background:var(--navy); color:var(--beige); font-family:'Segoe UI',sans-serif; }
  .navbar { background:var(--navy); border-bottom:1px solid var(--blue); }
  .navbar-brand { color:var(--beige)!important; letter-spacing:2px; font-weight:700; }
  .nav-link { color:var(--mid)!important; font-size:.85rem; letter-spacing:1px; }
  .nav-link:hover,.nav-link.active { color:var(--beige)!important; }
  .stat-card { background:#1E0D16; border:1px solid var(--blue); border-radius:8px; padding:1.25rem 1.5rem; height:100%; }
  .stat-label { color:var(--mid); font-size:.7rem; text-transform:uppercase; letter-spacing:1.5px; margin-bottom:.35rem; }
  .stat-value { font-size:1.75rem; font-weight:700; color:var(--beige); line-height:1; }
  .stat-sub   { color:var(--mid); font-size:.75rem; margin-top:.3rem; }
  .section-hdr { color:var(--mid); font-size:.65rem; text-transform:uppercase; letter-spacing:2px; margin:1.25rem 0 .6rem; border-bottom:1px solid #3D1525; padding-bottom:.4rem; }
  .dist-row { display:flex; align-items:center; gap:.75rem; margin-bottom:.45rem; font-size:.8rem; }
  .dist-label { width:90px; color:var(--mid); flex-shrink:0; text-align:right; font-size:.75rem; }
  .dist-bar-wrap { flex:1; background:#0D0509; border-radius:3px; height:13px; overflow:hidden; }
  .dist-bar  { height:100%; background:var(--blue); border-radius:3px; transition:width .5s ease; }
  .dist-bar.reason-bar { background:#4B5694; }
  .dist-count { width:44px; text-align:right; color:var(--beige); flex-shrink:0; font-size:.75rem; }
  .spinner-wrapper { display:flex; justify-content:center; padding:4rem; }
  .refresh-meta { color:var(--mid); font-size:.75rem; }
  ::-webkit-scrollbar{width:6px} ::-webkit-scrollbar-track{background:var(--navy)} ::-webkit-scrollbar-thumb{background:var(--blue);border-radius:3px}
</style>
</head>
<body>

<nav class="navbar px-4 py-3 mb-3">
  <span class="navbar-brand">&#x4e2d;&#x534e;&#x4eba;&#x6c11;&#x5171;&#x548c;&#x56fd; &nbsp;&middot;&nbsp; SOCIAL CREDIT DASHBOARD</span>
  <div class="d-flex gap-3 align-items-center">
    <a class="nav-link active" href="/">STATS</a>
    <a class="nav-link" href="/admin">ADMIN</a>
    <span class="refresh-meta" id="last-updated"></span>
  </div>
</nav>

<div class="container-fluid px-4" id="main" style="display:none">

  <div class="section-hdr">Bot Health</div>
  <div class="row g-3 mb-1">
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Servers</div><div class="stat-value" id="s-guilds">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Citizens</div><div class="stat-value" id="s-users">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">DAU</div><div class="stat-value" id="s-dau">—</div>
      <div class="stat-sub">daily active</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">WAU</div><div class="stat-value" id="s-wau">—</div>
      <div class="stat-sub">weekly active</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Uptime</div><div class="stat-value" id="s-uptime">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Most Active Guild</div>
      <div class="stat-value" style="font-size:1rem;word-break:break-word" id="s-mag-name">—</div>
      <div class="stat-sub" id="s-mag-msgs"></div>
    </div></div>
  </div>

  <div class="section-hdr">Messaging</div>
  <div class="row g-3 mb-1">
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Messages Rated</div><div class="stat-value" id="s-msgs">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Msgs / sec</div><div class="stat-value" id="s-mps">—</div>
      <div class="stat-sub">lifetime avg</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Avg Msgs / User</div><div class="stat-value" id="s-ampu">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">+Score Events</div><div class="stat-value" style="color:var(--yellow)" id="s-pos">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">-Score Events</div><div class="stat-value" style="color:var(--orange)" id="s-neg">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Avg Delta / Event</div><div class="stat-value" id="s-avd">—</div>
    </div></div>
  </div>

  <div class="section-hdr">Economy</div>
  <div class="row g-3 mb-1">
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">In Circulation</div><div class="stat-value" id="s-yuan">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Total Earned</div><div class="stat-value" id="s-earned">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Total Spent</div><div class="stat-value" id="s-spent">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Items Purchased</div><div class="stat-value" id="s-items">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Active Effects</div><div class="stat-value" id="s-fx">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Fundraiser Yuan</div><div class="stat-value" id="s-fryuan">—</div>
      <div class="stat-sub">total raised</div>
    </div></div>
  </div>

  <div class="section-hdr">Scores</div>
  <div class="row g-3 mb-1">
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Avg Score</div><div class="stat-value" id="s-avg">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">All-time High</div><div class="stat-value" style="color:var(--yellow)" id="s-high">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">All-time Low</div><div class="stat-value" style="color:var(--orange)" id="s-low">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Endorsements</div><div class="stat-value" style="color:var(--yellow)" id="s-end">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Rebukes</div><div class="stat-value" style="color:var(--orange)" id="s-reb">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">E/R Ratio</div><div class="stat-value" id="s-er">—</div>
      <div class="stat-sub">% endorsements</div>
    </div></div>
  </div>

  <div class="section-hdr">Check-ins</div>
  <div class="row g-3 mb-1">
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Today</div><div class="stat-value" id="s-checkins">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Highest Streak</div><div class="stat-value" id="s-streak">—</div>
      <div class="stat-sub">days</div>
    </div></div>
  </div>

  <div class="section-hdr">Propaganda</div>
  <div class="row g-3 mb-1">
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Events Run</div><div class="stat-value" id="s-pevents">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Total Submissions</div><div class="stat-value" id="s-psubs">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Avg Subs / Event</div><div class="stat-value" id="s-pavg">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="stat-card">
      <div class="stat-label">Winners Enshrined</div><div class="stat-value" id="s-pwins">—</div>
    </div></div>
  </div>

  <div class="section-hdr">Score Distribution</div>
  <div class="row g-3 mb-1">
    <div class="col-md-6"><div class="stat-card"><div id="dist-chart"></div></div></div>
    <div class="col-md-6"><div class="stat-card">
      <div class="stat-label" style="margin-bottom:.6rem">Top Scoring Reasons</div>
      <div id="reason-chart"></div>
    </div></div>
  </div>

  <div style="height:2rem"></div>

</div>

<div class="spinner-wrapper" id="spinner">
  <div class="spinner-border" style="color:var(--mid)" role="status"></div>
</div>

<script>
const TIERS = [
  {label:'600–649',key:'t1'},{label:'650–699',key:'t2'},{label:'700–749',key:'t3'},
  {label:'750–799',key:'t4'},{label:'800–849',key:'t5'},{label:'850–899',key:'t6'},
  {label:'900–999',key:'t7'},{label:'1000+',  key:'t8'},
];

function fmt(n) {
  if (n >= 1e6) return (n/1e6).toFixed(1)+'M';
  if (n >= 1e3) return (n/1e3).toFixed(1)+'K';
  return String(n);
}
function fmt_uptime(s) {
  const d=Math.floor(s/86400), h=Math.floor((s%86400)/3600), m=Math.floor((s%3600)/60);
  if(d>0) return d+'d '+h+'h';
  if(h>0) return h+'h '+m+'m';
  return m+'m';
}
function trunc(s,n){return s.length>n?s.slice(0,n)+'…':s;}
function set(id,val){const el=document.getElementById(id);if(el)el.textContent=val;}

function barChart(containerId, rows, barClass='') {
  const max = Math.max(...rows.map(r=>r.n)) || 1;
  document.getElementById(containerId).innerHTML = rows.map(r=>`
    <div class="dist-row">
      <div class="dist-label">${r.label}</div>
      <div class="dist-bar-wrap"><div class="dist-bar ${barClass}" style="width:${(r.n/max*100).toFixed(1)}%"></div></div>
      <div class="dist-count">${fmt(r.n)}</div>
    </div>`).join('');
}

async function load() {
  const res = await fetch('/api/stats');
  if (res.status===401||res.status===403){location.href='/login?next=/';return;}
  const d = await res.json();

  const uptime = d.uptime_seconds||0;
  const mps    = uptime>0?(d.total_messages/uptime).toFixed(4):'—';
  const total_social = (d.endorsements||0)+(d.rebukes||0);
  const er_pct = total_social>0?((d.endorsements/total_social)*100).toFixed(1)+'%':'—';
  const avg_subs = d.prop_events>0?(d.prop_subs/d.prop_events).toFixed(1):'—';
  const avg_delta_str = (d.avg_delta>=0?'+':'')+d.avg_delta.toFixed(4);

  set('s-guilds',  fmt(d.total_guilds));
  set('s-users',   fmt(d.total_users));
  set('s-dau',     fmt(d.dau));
  set('s-wau',     fmt(d.wau));
  set('s-uptime',  fmt_uptime(uptime));
  set('s-msgs',    fmt(d.total_messages));
  set('s-mps',     mps);
  set('s-ampu',    d.avg_msgs_per_user.toFixed(1));
  set('s-pos',     fmt(d.positive_events));
  set('s-neg',     fmt(d.negative_events));
  set('s-avd',     avg_delta_str);
  set('s-yuan',    fmt(d.total_yuan));
  set('s-earned',  fmt(d.total_earned));
  set('s-spent',   fmt(d.total_spent));
  set('s-items',   fmt(d.total_items));
  set('s-fx',      fmt(d.active_effects));
  set('s-fryuan',  fmt(d.fundraiser_yuan));
  set('s-avg',     d.avg_score.toFixed(2));
  set('s-high',    d.highest_score.toFixed(2));
  set('s-low',     d.lowest_score.toFixed(2));
  set('s-end',     fmt(d.endorsements));
  set('s-reb',     fmt(d.rebukes));
  set('s-er',      er_pct);
  set('s-checkins',fmt(d.checkins_today));
  set('s-streak',  fmt(d.highest_streak));
  set('s-pevents', fmt(d.prop_events));
  set('s-psubs',   fmt(d.prop_subs));
  set('s-pavg',    avg_subs);
  set('s-pwins',   fmt(d.prop_winners));

  const mag = d.most_active_guild||{};
  set('s-mag-name', mag.guild_name||mag.guild_id||'—');
  set('s-mag-msgs', mag.total?fmt(mag.total)+' msgs':'');

  barChart('dist-chart', TIERS.map(t=>({label:t.label, n:(d.score_dist||{})[t.key]||0})));
  barChart('reason-chart', (d.top_reasons||[]).map(r=>({label:trunc(r.reason,28), n:r.cnt})), 'reason-bar');

  document.getElementById('spinner').style.display='none';
  document.getElementById('main').style.display='block';
  set('last-updated','Updated '+new Date().toLocaleTimeString());
}

load();
setInterval(load, 30000);
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
  :root { --navy:#120810; --blue:#97124B; --mid:#C4849A; --beige:#F5E6D3; --green:#F4E557; --red:#F5A855; }
  body { background:var(--navy); color:var(--beige); font-family:'Segoe UI',sans-serif; }
  .navbar { background:var(--navy); border-bottom:1px solid var(--blue); }
  .navbar-brand { color:var(--beige)!important; letter-spacing:2px; font-weight:700; }
  .nav-link { color:var(--mid)!important; font-size:.85rem; letter-spacing:1px; }
  .nav-link:hover,.nav-link.active { color:var(--beige)!important; }
  .card-panel { background:#0D0509; border:1px solid var(--blue); border-radius:8px; }
  .form-control, .form-select {
    background:#1E0D16; border:1px solid var(--blue); color:var(--beige);
    font-size:.875rem;
  }
  .form-control:focus, .form-select:focus {
    background:#1E0D16; border-color:var(--beige); color:var(--beige); box-shadow:none;
  }
  .form-control::placeholder { color:var(--mid); }
  .form-label { color:var(--mid); font-size:.75rem; text-transform:uppercase; letter-spacing:1px; margin-bottom:4px; }
  .btn-run { background:var(--blue); border:none; color:var(--beige); font-weight:600; letter-spacing:1px; }
  .btn-run:hover { background:#DC4444; color:var(--beige); }
  .btn-run:disabled { opacity:.4; }
  .btn-danger-soft { background:#3D0808; border:1px solid #97124B; color:var(--red); }
  .btn-danger-soft:hover { background:#5C1525; color:var(--red); }
  #terminal {
    background:#080306; border:1px solid var(--blue); border-radius:6px;
    font-family:'Courier New',monospace; font-size:.8rem;
    min-height:260px; max-height:480px; overflow-y:auto;
    padding:12px 16px; color:var(--beige);
  }
  .t-prompt { color:var(--mid); }
  .t-out { color:var(--beige); white-space:pre-wrap; }
  .t-ok  { color:var(--green); }
  .t-err { color:var(--red); }
  .cmd-section { border-bottom:1px solid #3D1525; padding-bottom:16px; margin-bottom:16px; }
  .cmd-section:last-child { border-bottom:none; margin-bottom:0; padding-bottom:0; }
  ::-webkit-scrollbar{width:6px} ::-webkit-scrollbar-track{background:var(--navy)} ::-webkit-scrollbar-thumb{background:var(--blue);border-radius:3px}
  #token-gate { display:none; }
</style>
</head>
<body>

<nav class="navbar px-4 py-3 mb-4">
  <span class="navbar-brand">&#x4e2d;&#x534e;&#x4eba;&#x6c11;&#x5171;&#x548c;&#x56fd; &nbsp;&middot;&nbsp; SOCIAL CREDIT DASHBOARD</span>
  <div class="d-flex gap-3 align-items-center">
    <a class="nav-link" href="/">STATS</a>
    <a class="nav-link active" href="/admin">ADMIN</a>
  </div>
</nav>

<div class="container px-4" style="max-width:860px">

  <div id="token-gate" style="display:block">

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
</script>
</body>
</html>"""


LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Login · Social Credit</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  :root{--navy:#120810;--blue:#97124B;--mid:#C4849A;--beige:#F5E6D3;}
  body{background:var(--navy);color:var(--beige);font-family:'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;}
  .box{background:#0D0509;border:1px solid var(--blue);border-radius:8px;padding:2rem;width:100%;max-width:360px;}
  .brand{letter-spacing:2px;font-weight:700;font-size:.9rem;color:var(--mid);text-align:center;margin-bottom:1.5rem;}
  .form-control{background:#1E0D16;border:1px solid var(--blue);color:var(--beige);}
  .form-control:focus{background:#1E0D16;border-color:var(--beige);color:var(--beige);box-shadow:none;}
  .form-control::placeholder{color:var(--mid);}
  .btn-login{background:var(--blue);border:none;color:var(--beige);font-weight:600;letter-spacing:1px;width:100%;}
  .btn-login:hover{background:#DC4444;color:var(--beige);}
  .err{color:#F5A855;font-size:.8rem;margin-top:.5rem;display:none;}
</style>
</head>
<body>
<div class="box">
  <div class="brand">中华人民共和国 · SOCIAL CREDIT</div>
  <form id="form">
    <input type="password" id="token" class="form-control mb-3" placeholder="Access token" autofocus>
    <button type="submit" class="btn btn-login">ENTER</button>
    <div class="err" id="err">Invalid token.</div>
  </form>
</div>
<script>
const next = new URLSearchParams(location.search).get("next") || "/";
document.getElementById("form").addEventListener("submit", async e => {
  e.preventDefault();
  const res = await fetch("/api/auth", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({token: document.getElementById("token").value})
  });
  if (res.ok) { location.href = next; }
  else {
    const err = document.getElementById("err");
    err.textContent = res.status === 429 ? "Too many attempts. Try again later." : "Invalid token.";
    err.style.display = "block";
  }
});
</script>
</body>
</html>"""


def _is_authed(request):
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token:
        return True
    session_id = request.app.get("session_id", "")
    cookie = request.cookies.get("auth", "")
    return bool(session_id) and hmac.compare_digest(cookie, session_id)


def _require_auth(handler):
    async def middleware(request):
        if not _is_authed(request):
            next_url = str(request.rel_url)
            raise web.HTTPFound(f"/login?next={next_url}")
        return await handler(request)
    return middleware


async def _handle_login(request):
    return web.Response(text=LOGIN_HTML, content_type="text/html")


async def _handle_auth(request):
    admin_token = os.getenv("ADMIN_TOKEN", "")
    ip = request.headers.get("X-Forwarded-For", request.remote or "").split(",")[0].strip()

    now = time.time()
    attempts = _failed_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _RATE_WINDOW]
    if len(attempts) >= _RATE_LIMIT:
        return web.Response(status=429)

    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400)

    provided = body.get("token", "")
    if not admin_token or not hmac.compare_digest(provided, admin_token):
        attempts.append(now)
        _failed_attempts[ip] = attempts
        return web.Response(status=403)

    _failed_attempts.pop(ip, None)
    response = web.Response(status=200)
    session_id = request.app["session_id"]
    response.set_cookie("auth", session_id, httponly=True, secure=True, samesite="Strict", max_age=60 * 60 * 24 * 30)
    return response


async def _handle_index(request):
    return web.Response(text=HTML, content_type="text/html")


async def _handle_admin(request):
    return web.Response(text=ADMIN_HTML, content_type="text/html")


async def _handle_admin_command(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    command = body.get("command", "")
    args = body.get("args", [])
    bot = request.app["bot"]

    if command == "sync":
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


async def _handle_stats(request):
    bot = request.app["bot"]
    stats = await bot.db.get_global_stats()
    uptime = int(time.time() - bot.start_time.timestamp()) if hasattr(bot, "start_time") and bot.start_time else 0
    stats["uptime_seconds"] = uptime
    return web.json_response(stats)


async def start_web_server(bot):
    global _runner
    if _runner:
        print(f"Web dashboard already running at http://localhost:{PORT}")
        return

    app = web.Application()
    app["bot"] = bot
    app["session_id"] = secrets.token_hex(32)
    app.router.add_get("/login", _handle_login)
    app.router.add_post("/api/auth", _handle_auth)
    app.router.add_get("/", _require_auth(_handle_index))
    app.router.add_get("/admin", _require_auth(_handle_admin))
    app.router.add_post("/api/admin/command", _require_auth(_handle_admin_command))
    app.router.add_get("/api/stats", _require_auth(_handle_stats))

    _runner = web.AppRunner(app)
    await _runner.setup()
    site = web.TCPSite(_runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web dashboard running on port {PORT}")

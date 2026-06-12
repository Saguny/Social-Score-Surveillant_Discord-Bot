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
  :root {
    --navy:#120810; --blue:#97124B; --mid:#C4849A; --beige:#F5E6D3;
    --green:#3DAA6E; --red:#E85454; --yellow:#F4E557; --orange:#F5A855;
    --card-bg:#160C12; --border:#2D1020;
  }
  body { background:var(--navy); color:var(--beige); font-family:'Segoe UI',sans-serif; }
  .navbar { background:var(--navy); border-bottom:1px solid var(--border); }
  .navbar-brand { color:var(--beige)!important; letter-spacing:2px; font-weight:700; }
  .nav-link { color:var(--mid)!important; font-size:.85rem; letter-spacing:1px; }
  .nav-link:hover,.nav-link.active { color:var(--beige)!important; }

  .sc { background:var(--card-bg); border:1px solid var(--border); border-radius:8px; padding:1.4rem 1.6rem; height:100%; }
  .sc.hero { padding:2rem 2.2rem; }
  .lbl { color:var(--mid); font-size:.65rem; text-transform:uppercase; letter-spacing:1.5px; margin-bottom:.3rem; }
  .val { font-size:1.6rem; font-weight:700; line-height:1.1; }
  .val.xl { font-size:2.8rem; }
  .sub { color:var(--mid); font-size:.75rem; margin-top:.3rem; }
  .trend-up   { color:var(--green)!important; }
  .trend-down { color:var(--red)!important; }
  .trend-flat { color:var(--mid)!important; }

  .shdr { color:var(--mid); font-size:.65rem; text-transform:uppercase; letter-spacing:2px;
          margin:1.8rem 0 .7rem; padding-bottom:.4rem; border-bottom:1px solid var(--border); }

  .anomaly-item { display:flex; align-items:center; gap:.6rem; padding:.45rem .9rem;
                  border-radius:6px; font-size:.82rem; margin-bottom:.35rem; }
  .anomaly-warn { background:#2D1008; border:1px solid #7A3310; color:#F5A855; }
  .anomaly-ok   { background:#0A2115; border:1px solid #1A6040; color:var(--green); }

  .drow { display:flex; align-items:center; gap:.7rem; margin-bottom:.55rem; }
  .dlbl { width:72px; color:var(--mid); flex-shrink:0; text-align:right; font-size:.7rem; }
  .dbar-wrap { flex:1; background:#0A0508; border-radius:4px; height:20px; overflow:hidden; position:relative; }
  .dbar { height:100%; border-radius:4px; transition:width .5s; }
  .dpct { width:34px; text-align:right; flex-shrink:0; font-size:.7rem; }
  .dcount { width:36px; text-align:right; flex-shrink:0; font-size:.7rem; color:var(--mid); }
  .avg-tag { font-size:.58rem; color:var(--beige); background:rgba(0,0,0,.5);
             padding:1px 4px; border-radius:2px; position:absolute; right:4px; top:50%;
             transform:translateY(-50%); pointer-events:none; }

  .rrow { display:flex; align-items:center; gap:.6rem; margin-bottom:.4rem; }
  .rlbl { flex:1; font-size:.75rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .rbar-wrap { width:110px; background:#0A0508; border-radius:3px; height:12px; flex-shrink:0; }
  .rbar { height:100%; border-radius:3px; transition:width .5s; }
  .rcnt { width:34px; text-align:right; color:var(--mid); flex-shrink:0; font-size:.7rem; }

  details summary { color:var(--mid); font-size:.72rem; cursor:pointer; user-select:none;
                    padding:.4rem 0; letter-spacing:1px; list-style:none; text-transform:uppercase; }
  details summary::-webkit-details-marker { display:none; }
  details summary::before { content:'▶  '; font-size:.6rem; }
  details[open] summary::before { content:'▼  '; }

  .ping-good { color:var(--green)!important; }
  .ping-warn { color:var(--orange)!important; }
  .ping-bad  { color:var(--red)!important; }

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

  <div id="anomaly-wrap"></div>

  <div class="shdr">Mission Control</div>
  <div class="row g-3 mb-2">
    <div class="col-md-4">
      <div class="sc hero">
        <div class="lbl">Servers</div>
        <div class="val xl" id="mc-guilds">—</div>
        <div class="sub" id="mc-guilds-sub"></div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="sc hero">
        <div class="lbl">Citizens</div>
        <div class="val xl" id="mc-users">—</div>
        <div class="sub" id="mc-users-sub"></div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="sc hero">
        <div class="lbl">Most Active Guild</div>
        <div class="val" style="font-size:1.3rem;word-break:break-word" id="mc-mag">—</div>
        <div class="sub" id="mc-mag-sub"></div>
      </div>
    </div>
  </div>
  <div class="row g-3 mb-1">
    <div class="col-6 col-sm-4 col-lg-2"><div class="sc">
      <div class="lbl">Uptime</div><div class="val" id="mc-uptime">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-lg-2"><div class="sc">
      <div class="lbl">Msgs / sec</div><div class="val" id="mc-mps">—</div><div class="sub">lifetime avg</div>
    </div></div>
    <div class="col-6 col-sm-4 col-lg-2"><div class="sc">
      <div class="lbl">Discord Ping</div><div class="val" id="mc-ping">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-lg-2"><div class="sc">
      <div class="lbl">DB Query</div><div class="val" id="mc-db">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-lg-2"><div class="sc">
      <div class="lbl">DAU</div><div class="val" id="mc-dau">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-lg-2"><div class="sc">
      <div class="lbl">WAU</div><div class="val" id="mc-wau">—</div>
    </div></div>
  </div>

  <div class="shdr">Activity · Last 24h vs Prior 24h</div>
  <div class="row g-3 mb-1">
    <div class="col-6 col-md-3"><div class="sc">
      <div class="lbl">Score Events</div><div class="val" id="act-ev">—</div><div class="sub" id="act-ev-t"></div>
    </div></div>
    <div class="col-6 col-md-3"><div class="sc">
      <div class="lbl">Positive</div><div class="val trend-up" id="act-pos">—</div><div class="sub" id="act-pos-t"></div>
    </div></div>
    <div class="col-6 col-md-3"><div class="sc">
      <div class="lbl">Negative</div><div class="val trend-down" id="act-neg">—</div><div class="sub" id="act-neg-t"></div>
    </div></div>
    <div class="col-6 col-md-3"><div class="sc">
      <div class="lbl">Net Delta · 7 Days</div>
      <div class="val" id="act-net7">—</div>
      <div id="sparkline-wrap" class="mt-2"></div>
    </div></div>
  </div>

  <div class="shdr">Economy</div>
  <div class="row g-3 mb-1">
    <div class="col-6 col-sm-4 col-md-2"><div class="sc">
      <div class="lbl">In Circulation</div><div class="val" id="ec-circ">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="sc">
      <div class="lbl">Total Earned</div><div class="val" id="ec-earn">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="sc">
      <div class="lbl">Total Spent</div><div class="val" id="ec-spent">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="sc">
      <div class="lbl">Items Purchased</div><div class="val" id="ec-items">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="sc">
      <div class="lbl">Active Effects</div><div class="val" id="ec-fx">—</div>
    </div></div>
    <div class="col-6 col-sm-4 col-md-2"><div class="sc">
      <div class="lbl">Fundraiser Yuan</div><div class="val" id="ec-fr">—</div><div class="sub">total raised</div>
    </div></div>
  </div>

  <div class="shdr">Scores</div>
  <div class="row g-3 mb-1">
    <div class="col-md-5"><div class="sc h-100">
      <div class="lbl" style="margin-bottom:.7rem">Distribution</div>
      <div id="dist-chart"></div>
    </div></div>
    <div class="col-md-3">
      <div class="row g-3">
        <div class="col-12"><div class="sc">
          <div class="lbl">Avg Score</div><div class="val" id="sc-avg">—</div>
        </div></div>
        <div class="col-12"><div class="sc">
          <div class="lbl">All-time High</div><div class="val trend-up" id="sc-high">—</div>
        </div></div>
        <div class="col-12"><div class="sc">
          <div class="lbl">All-time Low</div><div class="val trend-down" id="sc-low">—</div>
        </div></div>
      </div>
    </div>
    <div class="col-md-4"><div class="sc h-100">
      <div class="lbl">Messages Rated</div>
      <div class="val" id="sc-msgs">—</div>
      <div class="sub" style="margin-bottom:.7rem">all-time</div>
      <div class="lbl">Avg Msgs / User</div>
      <div class="val" style="font-size:1.2rem" id="sc-ampu">—</div>
      <hr style="border-color:var(--border);margin:.8rem 0">
      <div class="row g-2">
        <div class="col-6">
          <div class="lbl">Endorsements</div>
          <div class="val trend-up" style="font-size:1.2rem" id="sc-end">—</div>
        </div>
        <div class="col-6">
          <div class="lbl">Rebukes</div>
          <div class="val trend-down" style="font-size:1.2rem" id="sc-reb">—</div>
        </div>
      </div>
      <div class="sub mt-1" id="sc-er"></div>
    </div></div>
  </div>

  <div class="shdr">Top Scoring Reasons</div>
  <div class="row g-3 mb-1">
    <div class="col-md-6"><div class="sc h-100">
      <div class="lbl" style="margin-bottom:.6rem;color:var(--green)">▲ Positive</div>
      <div id="reasons-pos"></div>
    </div></div>
    <div class="col-md-6"><div class="sc h-100">
      <div class="lbl" style="margin-bottom:.6rem;color:var(--red)">▼ Negative</div>
      <div id="reasons-neg"></div>
    </div></div>
  </div>

  <div class="shdr">Check-ins &amp; Propaganda</div>
  <div class="row g-3 mb-1">
    <div class="col-6 col-sm-3"><div class="sc">
      <div class="lbl">Check-ins Today</div><div class="val" id="ci-today">—</div><div class="sub" id="ci-t"></div>
    </div></div>
    <div class="col-6 col-sm-3"><div class="sc">
      <div class="lbl">Highest Streak</div><div class="val" id="ci-streak">—</div><div class="sub">days</div>
    </div></div>
    <div class="col-6 col-sm-3"><div class="sc">
      <div class="lbl">Events Run</div><div class="val" id="pr-ev">—</div>
    </div></div>
    <div class="col-6 col-sm-3"><div class="sc">
      <div class="lbl">Submissions</div><div class="val" id="pr-subs">—</div><div class="sub" id="pr-avg"></div>
    </div></div>
  </div>

  <div class="shdr">
    <details>
      <summary>Advanced Metrics</summary>
      <div class="row g-3 mt-2">
        <div class="col-6 col-sm-4 col-md-2"><div class="sc">
          <div class="lbl">+Events All-time</div><div class="val" style="font-size:1.2rem" id="adv-pos">—</div>
        </div></div>
        <div class="col-6 col-sm-4 col-md-2"><div class="sc">
          <div class="lbl">-Events All-time</div><div class="val" style="font-size:1.2rem" id="adv-neg">—</div>
        </div></div>
        <div class="col-6 col-sm-4 col-md-2"><div class="sc">
          <div class="lbl">Avg Delta / Event</div><div class="val" style="font-size:1.2rem" id="adv-avd">—</div>
        </div></div>
        <div class="col-6 col-sm-4 col-md-2"><div class="sc">
          <div class="lbl">Propaganda Winners</div><div class="val" style="font-size:1.2rem" id="adv-pw">—</div>
        </div></div>
        <div class="col-6 col-sm-4 col-md-2"><div class="sc">
          <div class="lbl">Avg Subs / Event</div><div class="val" style="font-size:1.2rem" id="adv-pe">—</div>
        </div></div>
        <div class="col-6 col-sm-4 col-md-2"><div class="sc">
          <div class="lbl">E/R Ratio</div><div class="val" style="font-size:1.2rem" id="adv-er">—</div>
          <div class="sub">% endorsements</div>
        </div></div>
      </div>
    </details>
  </div>

  <div style="height:2rem"></div>
</div>

<div class="spinner-wrapper" id="spinner">
  <div class="spinner-border" style="color:var(--mid)" role="status"></div>
</div>

<script>
const TIERS = [
  {label:'600–649', key:'t1', min:600,  max:650,  color:'#E85454'},
  {label:'650–699', key:'t2', min:650,  max:700,  color:'#D47030'},
  {label:'700–749', key:'t3', min:700,  max:750,  color:'#C49030'},
  {label:'750–799', key:'t4', min:750,  max:800,  color:'#4B8EAF'},
  {label:'800–849', key:'t5', min:800,  max:850,  color:'#3A9A60'},
  {label:'850–899', key:'t6', min:850,  max:900,  color:'#3DAA6E'},
  {label:'900–999', key:'t7', min:900,  max:1000, color:'#45C07A'},
  {label:'1000+',   key:'t8', min:1000, max:1300, color:'#F4E557'},
];

function fmt(n) {
  n = Number(n);
  if (n >= 1e6) return (n/1e6).toFixed(1)+'M';
  if (n >= 1e3) return (n/1e3).toFixed(1)+'K';
  return String(n);
}
function fmtUptime(s) {
  const d=Math.floor(s/86400), h=Math.floor((s%86400)/3600), m=Math.floor((s%3600)/60);
  if(d>0) return d+'d '+h+'h'; if(h>0) return h+'h '+m+'m'; return m+'m';
}
function trunc(s,n){return s.length>n?s.slice(0,n)+'\\u2026':s;}
function set(id,v){const e=document.getElementById(id);if(e)e.textContent=v;}
function setHtml(id,v){const e=document.getElementById(id);if(e)e.innerHTML=v;}

function trendHtml(now, prev) {
  if (!prev) return '';
  const pct = (now - prev) / prev * 100;
  if (Math.abs(pct) < 2) return '<span class="trend-flat">\\u2192 stable</span>';
  const arrow = pct > 0 ? '\\u2191' : '\\u2193';
  const cls   = pct > 0 ? 'trend-up' : 'trend-down';
  return `<span class="${cls}">${arrow} ${Math.abs(pct).toFixed(0)}% vs prev 24h</span>`;
}

function sparkSvg(vals, w=90, h=26) {
  if (!vals || vals.length < 2) return '';
  const max  = Math.max(...vals, 1);
  const step = w / (vals.length - 1);
  const pts  = vals.map((v,i) => `${(i*step).toFixed(1)},${(h - v/max*(h-2)).toFixed(1)}`).join(' ');
  const lx   = ((vals.length-1)*step).toFixed(1);
  const ly   = (h - vals[vals.length-1]/max*(h-2)).toFixed(1);
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="display:block;overflow:visible">
    <polyline points="${pts}" fill="none" stroke="var(--mid)" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${lx}" cy="${ly}" r="2.5" fill="var(--mid)"/>
  </svg>`;
}

function build7d(daily7d) {
  const today = Math.floor(Date.now() / 86400000);
  const map = {};
  (daily7d||[]).forEach(r => map[r[0]] = r[1]);
  const vals = [];
  for (let i = 6; i >= 0; i--) vals.push(map[today - i] || 0);
  return vals;
}

function renderDist(dist, avg) {
  const total = TIERS.reduce((s,t) => s+(dist[t.key]||0), 0) || 1;
  const maxN  = Math.max(...TIERS.map(t => dist[t.key]||0)) || 1;
  document.getElementById('dist-chart').innerHTML = TIERS.map(t => {
    const n   = dist[t.key] || 0;
    const pct = Math.round(n/total*100);
    const w   = (n/maxN*100).toFixed(1);
    const isAvg = avg >= t.min && avg < t.max;
    return `<div class="drow">
      <div class="dlbl">${t.label}</div>
      <div class="dbar-wrap">
        <div class="dbar" style="width:${w}%;background:${t.color}"></div>
        ${isAvg ? '<span class="avg-tag">AVG</span>' : ''}
      </div>
      <div class="dpct" style="color:${t.color}">${pct}%</div>
      <div class="dcount">${fmt(n)}</div>
    </div>`;
  }).join('');
}

function renderReasons(reasons) {
  const pos = reasons.filter(r => r.avg_delta > 0).sort((a,b) => b.cnt-a.cnt);
  const neg = reasons.filter(r => r.avg_delta <= 0).sort((a,b) => b.cnt-a.cnt);
  const maxP = Math.max(...pos.map(r=>r.cnt), 1);
  const maxN = Math.max(...neg.map(r=>r.cnt), 1);
  function row(r, mx, color) {
    return `<div class="rrow">
      <div class="rlbl" title="${r.reason}">${trunc(r.reason,30)}</div>
      <div class="rbar-wrap"><div class="rbar" style="width:${(r.cnt/mx*100).toFixed(1)}%;background:${color}"></div></div>
      <div class="rcnt">${fmt(r.cnt)}</div>
    </div>`;
  }
  setHtml('reasons-pos', pos.length ? pos.map(r=>row(r,maxP,'var(--green)')).join('') : '<div class="sub">No data yet</div>');
  setHtml('reasons-neg', neg.length ? neg.map(r=>row(r,maxN,'var(--red)')).join('')   : '<div class="sub">No data yet</div>');
}

function renderAnomalies(d) {
  const ev_trend = d.events_prev_24h > 0 ? (d.events_24h - d.events_prev_24h)/d.events_prev_24h : 0;
  const items = [];
  if (ev_trend < -0.3)
    items.push({cls:'anomaly-warn', t:`\\u26a0 Score event activity down ${Math.abs(ev_trend*100).toFixed(0)}% vs yesterday`});
  if (d.events_24h > 0 && d.neg_24h > d.pos_24h)
    items.push({cls:'anomaly-warn', t:`\\u26a0 More negative events than positive today — ${d.neg_24h} vs ${d.pos_24h} positive`});
  if (d.wau > 0 && d.dau < d.wau/7 * 0.4)
    items.push({cls:'anomaly-warn', t:`\\u26a0 DAU (${d.dau}) well below weekly average (${Math.round(d.wau/7)})`});
  if (d.net_delta_7d < -10)
    items.push({cls:'anomaly-warn', t:`\\u26a0 Net score delta negative this week (${d.net_delta_7d.toFixed(1)})`});
  if (d.discord_ping_ms && d.discord_ping_ms > 250)
    items.push({cls:'anomaly-warn', t:`\\u26a0 Discord ping elevated: ${d.discord_ping_ms}ms`});
  if (d.db_query_ms > 800)
    items.push({cls:'anomaly-warn', t:`\\u26a0 DB stats query slow: ${d.db_query_ms}ms`});
  if (!items.length && d.uptime_seconds > 604800)
    items.push({cls:'anomaly-ok', t:`\\u2713 Uptime stable for ${Math.floor(d.uptime_seconds/86400)} days`});
  setHtml('anomaly-wrap', items.map(a=>`<div class="anomaly-item ${a.cls}">${a.t}</div>`).join(''));
}

function pingClass(ms) {
  if (!ms) return '';
  return ms < 100 ? 'ping-good' : ms < 200 ? 'ping-warn' : 'ping-bad';
}

async function load() {
  const res = await fetch('/api/stats');
  if (res.status===401||res.status===403){location.href='/login?next=/';return;}
  const d = await res.json();

  const uptime  = d.uptime_seconds || 0;
  const mps     = uptime > 0 ? (d.total_messages/uptime).toFixed(4) : '—';
  const tot_soc = (d.endorsements||0)+(d.rebukes||0);

  renderAnomalies(d);

  set('mc-guilds',  fmt(d.total_guilds));
  set('mc-users',   fmt(d.total_users));
  set('mc-uptime',  fmtUptime(uptime));
  set('mc-mps',     mps);
  set('mc-dau',     fmt(d.dau));
  set('mc-wau',     fmt(d.wau));
  setHtml('mc-users-sub', `DAU <b>${fmt(d.dau)}</b> &middot; WAU <b>${fmt(d.wau)}</b>`);

  const mag = d.most_active_guild || {};
  set('mc-mag',     mag.guild_name || mag.guild_id || '—');
  set('mc-mag-sub', mag.total ? fmt(mag.total)+' msgs rated' : '');

  const pingEl = document.getElementById('mc-ping');
  if (pingEl) { pingEl.textContent = d.discord_ping_ms ? d.discord_ping_ms+'ms' : '—'; pingEl.className = 'val '+pingClass(d.discord_ping_ms); }
  const dbEl = document.getElementById('mc-db');
  if (dbEl)   { dbEl.textContent = d.db_query_ms+'ms'; dbEl.className = 'val '+(d.db_query_ms>500?'ping-bad':d.db_query_ms>200?'ping-warn':'ping-good'); }

  setHtml('act-ev',    fmt(d.events_24h));
  setHtml('act-ev-t',  trendHtml(d.events_24h, d.events_prev_24h));
  setHtml('act-pos',   fmt(d.pos_24h));
  setHtml('act-pos-t', trendHtml(d.pos_24h, d.pos_prev_24h));
  setHtml('act-neg',   fmt(d.neg_24h));
  setHtml('act-neg-t', trendHtml(d.neg_24h, d.neg_prev_24h));

  const net7   = d.net_delta_7d;
  const net7El = document.getElementById('act-net7');
  if (net7El) { net7El.textContent = (net7>=0?'+':'')+net7.toFixed(1); net7El.className = 'val '+(net7>0?'trend-up':net7<0?'trend-down':'trend-flat'); }
  setHtml('sparkline-wrap', sparkSvg(build7d(d.daily_7d)));

  set('ec-circ',  fmt(d.total_yuan));
  set('ec-earn',  fmt(d.total_earned));
  set('ec-spent', fmt(d.total_spent));
  set('ec-items', fmt(d.total_items));
  set('ec-fx',    fmt(d.active_effects));
  set('ec-fr',    fmt(d.fundraiser_yuan));

  renderDist(d.score_dist||{}, d.avg_score);
  set('sc-avg',  d.avg_score.toFixed(2));
  set('sc-high', d.highest_score.toFixed(2));
  set('sc-low',  d.lowest_score.toFixed(2));
  set('sc-msgs', fmt(d.total_messages));
  set('sc-ampu', d.avg_msgs_per_user.toFixed(1));
  set('sc-end',  fmt(d.endorsements));
  set('sc-reb',  fmt(d.rebukes));
  set('sc-er',   tot_soc > 0 ? ((d.endorsements/tot_soc)*100).toFixed(1)+'% endorsements' : '');

  renderReasons(d.top_reasons||[]);

  set('ci-today',  fmt(d.checkins_today));
  setHtml('ci-t',  trendHtml(d.checkins_today, d.checkins_yday));
  set('ci-streak', fmt(d.highest_streak));
  set('pr-ev',     fmt(d.prop_events));
  set('pr-subs',   fmt(d.prop_subs));
  set('pr-avg',    d.prop_events > 0 ? 'avg '+(d.prop_subs/d.prop_events).toFixed(1)+'/event' : '');

  set('adv-pos', fmt(d.positive_events));
  set('adv-neg', fmt(d.negative_events));
  set('adv-avd', (d.avg_delta>=0?'+':'')+d.avg_delta.toFixed(4));
  set('adv-pw',  fmt(d.prop_winners));
  set('adv-pe',  d.prop_events > 0 ? (d.prop_subs/d.prop_events).toFixed(1) : '—');
  set('adv-er',  tot_soc > 0 ? ((d.endorsements/tot_soc)*100).toFixed(1)+'%' : '—');

  document.getElementById('spinner').style.display = 'none';
  document.getElementById('main').style.display    = 'block';
  set('last-updated', 'Updated '+new Date().toLocaleTimeString());
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
    t0 = time.time()
    stats = await bot.db.get_global_stats()
    stats["db_query_ms"]     = round((time.time() - t0) * 1000, 1)
    stats["uptime_seconds"]  = int(time.time() - bot.start_time.timestamp()) if getattr(bot, "start_time", None) else 0
    stats["discord_ping_ms"] = round(bot.latency * 1000, 1) if bot.latency else None
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

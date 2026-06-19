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
function trunc(s,n){return s.length>n?s.slice(0,n)+'…':s;}
function set(id,v){const e=document.getElementById(id);if(e)e.textContent=v;}
function setHtml(id,v){const e=document.getElementById(id);if(e)e.innerHTML=v;}

function trendHtml(now, prev) {
  if (!prev) return '';
  const pct = (now - prev) / prev * 100;
  if (Math.abs(pct) < 2) return '<span class="trend-flat">-> stable</span>';
  const arrow = pct > 0 ? '↑' : '↓';
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
    items.push({cls:'anomaly-warn', t:`⚠ Score event activity down ${Math.abs(ev_trend*100).toFixed(0)}% vs yesterday`});
  if (d.events_24h > 0 && d.neg_24h > d.pos_24h)
    items.push({cls:'anomaly-warn', t:`⚠ More negative events than positive today — ${d.neg_24h} vs ${d.pos_24h} positive`});
  if (d.wau > 0 && d.dau < d.wau/7 * 0.4)
    items.push({cls:'anomaly-warn', t:`⚠ DAU (${d.dau}) well below weekly average (${Math.round(d.wau/7)})`});
  if (d.net_delta_7d < -10)
    items.push({cls:'anomaly-warn', t:`⚠ Net score delta negative this week (${d.net_delta_7d.toFixed(1)})`});
  if (d.discord_ping_ms && d.discord_ping_ms > 250)
    items.push({cls:'anomaly-warn', t:`⚠ Discord ping elevated: ${d.discord_ping_ms}ms`});
  if (d.db_query_ms > 800)
    items.push({cls:'anomaly-warn', t:`⚠ DB stats query slow: ${d.db_query_ms}ms`});
  if (!items.length && d.uptime_seconds > 604800)
    items.push({cls:'anomaly-ok', t:`✓ Uptime stable for ${Math.floor(d.uptime_seconds/86400)} days`});
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

  set('mk-stocks', fmt(d.yuan_in_stocks || 0));
  set('mk-turbos', fmt(d.yuan_in_turbos || 0));
  set('mk-ko',     fmt(d.total_knockouts || 0));
  set('mk-trades', fmt(d.total_stock_trades || 0));

  set('ec-circ',  fmt(d.total_yuan));
  set('ec-earn',  fmt(d.total_earned));
  set('ec-spent', fmt(d.total_spent));
  set('ec-items', fmt(d.total_items));
  set('ec-fx',    fmt(d.active_effects));
  set('ec-fr',    fmt(d.fundraiser_yuan));
  set('ec-rich',  fmt(d.highest_yuan));

  const ltPlayed = d.lottery_played || 0;
  const ltWon    = d.lottery_won    || 0;
  const ltLost   = d.lottery_lost   || 0;
  const ltNet    = d.lottery_net    || 0;
  set('lt-played', fmt(ltPlayed));
  set('lt-won',    fmt(ltWon));
  set('lt-lost',   fmt(ltLost));
  set('lt-wr',     ltPlayed > 0 ? ((ltWon/ltPlayed)*100).toFixed(1)+'% win rate' : '');
  const ltNetEl = document.getElementById('lt-net');
  if (ltNetEl) {
    ltNetEl.textContent = (ltNet >= 0 ? '+' : '') + '¥' + fmt(Math.abs(ltNet));
    ltNetEl.className = 'val ' + (ltNet >= 0 ? 'trend-up' : 'trend-down');
  }
  const ltEdgeEl = document.getElementById('lt-edge');
  if (ltEdgeEl) {
    const edge = ltPlayed > 0 ? ltNet / ltPlayed : 0;
    ltEdgeEl.textContent = (edge >= 0 ? '+' : '') + '¥' + Math.abs(edge).toFixed(0) + '/ticket';
    ltEdgeEl.className = 'val ' + (edge >= 0 ? 'trend-up' : 'trend-down');
  }

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

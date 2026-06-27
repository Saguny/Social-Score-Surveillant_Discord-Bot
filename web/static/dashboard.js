if (window.Chart) {
  Chart.defaults.color = '#D8D9DA';
  Chart.defaults.borderColor = 'rgba(97,103,122,.25)';
  Chart.defaults.font.family = "'Segoe UI',sans-serif";
}

const _charts = {};
let _activityRange = '7d';

function _dayLabel(ts) {
  return new Date(ts * 1000).toLocaleDateString([], {month: 'short', day: 'numeric'});
}
function _hourLabel(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], {hour: 'numeric'});
}

function _sparkChart(canvasId, labels, data, color, minPoints = 3, yFormat = v => v) {
  const el = document.getElementById(canvasId);
  if (!el) return;
  const wrap = el.parentElement;
  if (_charts[canvasId]) { _charts[canvasId].destroy(); delete _charts[canvasId]; }
  wrap.querySelectorAll('.spark-empty').forEach(e => e.remove());
  if (labels.length < minPoints) {
    el.style.display = 'none';
    const msg = document.createElement('div');
    msg.className = 'spark-empty';
    msg.textContent = labels.length ? 'Collecting data…' : 'No data yet';
    wrap.appendChild(msg);
    return;
  }
  el.style.display = 'block';
  _charts[canvasId] = new Chart(el.getContext('2d'), {
    type: 'line',
    data: { labels, datasets: [{ data, borderColor: color, backgroundColor: color + '22', fill: true, tension: .3 }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: 0 },
      plugins: {
        legend: { display: false },
        tooltip: { displayColors: false, callbacks: { title: items => items[0].label } },
      },
      scales: {
        x: { display: true, offset: false, grid: { display: false }, border: { display: false },
             ticks: { autoSkip: true, maxTicksLimit: 3, font: { size: 9 }, color: '#61677A' } },
        y: { display: true, grid: { color: 'rgba(97,103,122,.15)' }, border: { display: false },
             ticks: { maxTicksLimit: 3, font: { size: 9 }, color: '#61677A', callback: yFormat } },
      },
      elements: { point: { radius: 0, hoverRadius: 3 }, line: { borderWidth: 2 } },
      interaction: { intersect: false, mode: 'index' },
    },
  });
}

function _hideIfEmpty(canvasId, points) {
  const el = document.getElementById(canvasId);
  if (!el) return;
  const col = el.closest('.spark-tile-col');
  if (col) col.classList.toggle('d-none', points === 0);
}

function _trendValClass(n) {
  return n > 0 ? 'trend-up' : n < 0 ? 'trend-down' : '';
}

function _multiLineChart(canvasId, labels, datasets) {
  const el = document.getElementById(canvasId);
  if (!el) return;
  if (_charts[canvasId]) { _charts[canvasId].destroy(); delete _charts[canvasId]; }
  const wrap = el.parentElement;
  wrap.querySelectorAll('.chart-empty').forEach(e => e.remove());
  if (labels.length < 2) {
    el.style.display = 'none';
    const msg = document.createElement('div');
    msg.className = 'chart-empty';
    msg.textContent = 'Collecting data…';
    wrap.appendChild(msg);
    return;
  }
  el.style.display = 'block';
  const scales = {
    x: { grid: { color: 'rgba(97,103,122,.15)' } },
    y: { grid: { color: 'rgba(97,103,122,.15)' } },
  };
  _charts[canvasId] = new Chart(el.getContext('2d'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { boxWidth: 10, font: { size: 11 } } },
        tooltip: { mode: 'index', intersect: false },
      },
      scales,
      elements: { point: { radius: 0, hoverRadius: 3 }, line: { borderWidth: 2 } },
      interaction: { intersect: false, mode: 'index' },
    },
  });
}

async function loadActivity(range) {
  _activityRange = range;
  document.querySelectorAll('#activity-range-group button').forEach(b => {
    b.classList.toggle('active', b.dataset.range === range);
  });

  const res = await fetch('/api/stats/timeline?range=' + range);
  if (!res.ok) return;
  const d = await res.json();
  const labelFn = range === '24h' ? _hourLabel : _dayLabel;

  const eng = d.engagement || [];
  const labels = eng.map(r => labelFn(r.bucket));
  const msgVals = eng.map(r => Math.max(0, r.events - r.checkins - r.endorsements - r.rebukes));
  const scoreMap = {};
  (d.score || []).forEach(r => scoreMap[r[0]] = r[1]);
  const scoreVals = eng.map(r => scoreMap[r.bucket] ?? 0);
  const dauVals = eng.map(r => r.active_users);
  const ciVals = eng.map(r => r.checkins);

  _multiLineChart('chart-activity-msgs', labels, [
    { label: 'Messages',    data: msgVals,   borderColor: '#7D9D9C', backgroundColor: '#7D9D9C22', fill: false, tension: .3 },
  ]);

  _multiLineChart('chart-activity-score', labels, [
    { label: 'Score Delta', data: scoreVals, borderColor: '#3DAA6E', backgroundColor: '#3DAA6E22', fill: false, tension: .3 },
  ]);

  _multiLineChart('chart-activity-dau', labels, [
    { label: 'DAU',         data: dauVals,   borderColor: '#F5A855', backgroundColor: '#F5A85522', fill: false, tension: .3 },
    { label: 'Check-ins',   data: ciVals,    borderColor: '#F4E557', backgroundColor: '#F4E55722', fill: false, tension: .3 },
  ]);

  const socVals = eng.map(r => r.endorsements + r.rebukes);
  set('tl-social-val', socVals.length ? fmt(socVals.reduce((a, b) => a + b, 0)) : '—');
  _sparkChart('chart-social', labels, socVals, '#7D9D9C', 3, v => v);
  _hideIfEmpty('chart-social', socVals.length);

  const port = d.portfolio || [];
  const portLabels = port.map(r => labelFn(r[0]));
  const portVals = port.map(r => r[1]);
  set('tl-portfolio-val', portVals.length ? '¥' + fmt(portVals[portVals.length - 1]) : '—');
  _sparkChart('chart-portfolio', portLabels, portVals, '#F5A855', 3, v => '¥' + fmt(v));
  _hideIfEmpty('chart-portfolio', portVals.length);

  const joins = d.joins || [];
  const joinLabels = joins.map(r => labelFn(r[0]));
  const joinVals = joins.map(r => r[1]);
  set('tl-joins-val', joinVals.length ? fmt(joinVals.reduce((a, b) => a + b, 0)) : '—');
  _sparkChart('chart-joins', joinLabels, joinVals, '#7D9D9C', 3, v => v);
  _hideIfEmpty('chart-joins', joinVals.length);
}

async function loadYuanCirculation() {
  const res = await fetch('/api/stats/timeline?range=7d');
  if (!res.ok) return;
  const d = await res.json();
  const yuan = d.yuan || [];
  const yuanLabels = yuan.map(r => _dayLabel(r[0]));
  const yuanVals = yuan.map(r => r[1]);
  set('tl-yuan-val', yuanVals.length ? '¥' + fmt(yuanVals[yuanVals.length - 1]) : '—');
  _sparkChart('chart-yuan', yuanLabels, yuanVals, '#F4E557', 3, v => '¥' + fmt(v));
  _hideIfEmpty('chart-yuan', yuanVals.length);
}

const _dbLatencyBuf = [];
const _pingBuf = [];
const _LATENCY_BUF_MAX = 60;

function _pushLatencySample(dbMs, pingMs) {
  if (typeof dbMs !== 'number' || !isFinite(dbMs)) return;
  const t = new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});
  _dbLatencyBuf.push([t, dbMs]);
  _pingBuf.push([t, pingMs || 0]);
  if (_dbLatencyBuf.length > _LATENCY_BUF_MAX) _dbLatencyBuf.shift();
  if (_pingBuf.length > _LATENCY_BUF_MAX) _pingBuf.shift();
  set('tl-dblatency-val', dbMs + 'ms');
  _sparkChart('chart-dblatency', _dbLatencyBuf.map(r => r[0]), _dbLatencyBuf.map(r => r[1]), '#7D9D9C', 2, v => v + 'ms');
}

const TIERS = [
  {label:'Enemy of the State',   key:'t1', min:600,  max:700,  color:'#E85454'},
  {label:'Person of Interest',   key:'t2', min:700,  max:775,  color:'#D47030'},
  {label:'Unremarkable Citizen', key:'t3', min:775,  max:850,  color:'#C49030'},
  {label:'Compliant Citizen',    key:'t4', min:850,  max:925,  color:'#7D9D9C'},
  {label:'Model Citizen',        key:'t5', min:925,  max:1000, color:'#3A9A60'},
  {label:'Party Loyalist',       key:'t6', min:1000, max:1100, color:'#3DAA6E'},
  {label:'Cadre Member',         key:'t7', min:1100, max:1200, color:'#45C07A'},
  {label:'General Secretary',    key:'t8', min:1200, max:1301, color:'#F4E557'},
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

function _escAnnounce(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function loadAnnouncement() {
  try {
    const res = await fetch('/api/announcement');
    if (!res.ok) return;
    const d = await res.json();
    if (d.enabled && d.message) {
      setHtml('announce-wrap', `<div class="announce-banner announce-${d.severity || 'info'}">${_escAnnounce(d.message)}</div>`);
    } else {
      setHtml('announce-wrap', '');
    }
  } catch (e) {}
}

function trendHtml(now, prev) {
  if (!prev) return '';
  const pct = (now - prev) / prev * 100;
  if (Math.abs(pct) < 2) return '<span class="trend-flat">-> stable</span>';
  const arrow = pct > 0 ? '↑' : '↓';
  const cls   = pct > 0 ? 'trend-up' : 'trend-down';
  return `<span class="${cls}">${arrow} ${Math.abs(pct).toFixed(0)}% vs prev 24h</span>`;
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

function _setStatusClass(id, cls) {
  const e = document.getElementById(id);
  if (e) e.className = cls ? 'val ' + cls : 'val val-white';
}

function _feedRow(ev) {
  const sign = ev.delta > 0 ? 'trend-up' : ev.delta < 0 ? 'trend-down' : 'trend-flat';
  const deltaStr = (ev.delta > 0 ? '+' : '') + ev.delta.toFixed(2);
  const t = new Date(ev.timestamp * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  const countStr = ev._count > 1 ? ` <span class="feed-time">×${ev._count}</span>` : '';
  const reasonStr = ev.reason ? ` <span class="feed-reason">· ${ev.reason}</span>` : '';
  return `<div class="feed-row" data-user="${ev.user}" data-delta="${ev.delta}" data-count="${ev._count || 1}">
    <span class="feed-time">${t}</span>
    <span class="feed-delta ${sign}">${deltaStr}</span>
    <span class="feed-user">${ev.user}</span>${reasonStr}${countStr}
  </div>`;
}

const _FEED_MAX = 20;

function _feedPrepend(ev) {
  const el = document.getElementById('live-feed');
  if (!el) return;
  if (el.querySelector('.sub')) el.innerHTML = '';
  const top = el.firstElementChild;
  if (top && top.dataset.user === String(ev.user) && Number(top.dataset.delta) === ev.delta) {
    const count = (parseInt(top.dataset.count || '1', 10)) + 1;
    top.dataset.count = String(count);
    top.outerHTML = _feedRow({ ...ev, _count: count });
    return;
  }
  el.insertAdjacentHTML('afterbegin', _feedRow(ev));
  while (el.children.length > _FEED_MAX) el.removeChild(el.lastChild);
}

function _collapseRepeats(events) {
  const out = [];
  for (const ev of events) {
    const prev = out[out.length - 1];
    if (prev && prev.user === ev.user && prev.delta === ev.delta) {
      prev._count = (prev._count || 1) + 1;
    } else {
      out.push({ ...ev });
    }
  }
  return out;
}

async function loadFeed() {
  const res = await fetch('/api/stats/recent-events');
  if (!res.ok) return;
  const d = await res.json();
  const events = _collapseRepeats(d.events || []);
  setHtml('live-feed', events.length ? events.map(_feedRow).join('') : '<div class="sub">No data yet</div>');
}

function renderStats(d) {
  const uptime  = d.uptime_seconds || 0;
  const mps     = uptime > 0 ? (d.total_messages/uptime).toFixed(2) : '—';
  const tot_soc = (d.endorsements||0)+(d.rebukes||0);

  renderAnomalies(d);

  set('mc-users',  Number(d.total_users || 0).toLocaleString());
  set('mc-users-sub', '');
  set('mc-guilds', fmt(d.total_guilds));
  set('mc-uptime', fmtUptime(uptime));
  set('mc-mps',    mps);
  set('mc-dau',    fmt(d.dau));
  set('mc-dau-sub', d.wau ? 'WAU '+fmt(d.wau) : '');
  set('mc-wau',    fmt(d.wau));

  const mag = d.most_active_guild || {};
  set('mc-mag',     mag.guild_name || mag.guild_id || '—');
  set('mc-mag-sub', mag.total ? fmt(mag.total)+' msgs rated' : '');

  set('mc-ping', d.discord_ping_ms ? d.discord_ping_ms+'ms' : '—');
  _setStatusClass('mc-ping', pingClass(d.discord_ping_ms));

  const dbCls = d.db_query_ms>600?'ping-bad':d.db_query_ms>350?'ping-warn':'ping-good';
  set('mc-db', typeof d.db_query_ms === 'number' ? d.db_query_ms+'ms' : '—');
  _setStatusClass('mc-db', typeof d.db_query_ms === 'number' ? dbCls : '');

  set('mc-workers', d.sentiment_workers_max != null ? (d.sentiment_workers_active ?? 0)+'/'+d.sentiment_workers_max : '—');

  _pushLatencySample(d.db_query_ms, d.discord_ping_ms);

  setHtml('act-ev',    fmt(d.events_24h));
  setHtml('act-ev-t',  trendHtml(d.events_24h, d.events_prev_24h));
  setHtml('act-pos',   fmt(d.pos_24h));
  setHtml('act-pos-t', trendHtml(d.pos_24h, d.pos_prev_24h));
  setHtml('act-neg',   fmt(d.neg_24h));
  setHtml('act-neg-t', trendHtml(d.neg_24h, d.neg_prev_24h));

  const net7   = d.net_delta_7d;
  const net7El = document.getElementById('act-net7');
  if (net7El) { net7El.textContent = (net7>=0?'+':'')+net7.toFixed(1); net7El.className = 'val '+(net7>0?'trend-up':net7<0?'trend-down':'trend-flat'); }

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
  set('ec-treasury', fmt(d.treasury_total || 0));
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
    ltNetEl.textContent = (ltNet >= 0 ? '+' : '-') + '¥' + fmt(Math.abs(ltNet));
    ltNetEl.className = 'val ' + (ltNet >= 0 ? 'trend-up' : 'trend-down');
  }
  const ltEdgeEl = document.getElementById('lt-edge');
  if (ltEdgeEl) {
    const edge = ltPlayed > 0 ? -(ltNet / ltPlayed) : 0;
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
  set('ci-rate',   d.dau > 0 ? Math.round(d.checkins_today / d.dau * 100) + '%' : '—');
  set('ci-streak', fmt(d.highest_streak));
  set('ci-votes',  fmt(d.total_votes || 0));
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
  const _now = new Date();
  const _ts = _now.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
  const _ds = _now.toLocaleDateString([], {month:'short', day:'numeric'});
  set('last-updated', `Updated ${_ds} at ${_ts}`);
}

async function load() {
  const res = await fetch('/api/stats');
  if (!res.ok) return;
  renderStats(await res.json());
}

let _streamConnected = false;
let _pollFallback = null;

function _startPollFallback() {
  if (_pollFallback) return;
  _pollFallback = setInterval(() => { if (!_streamConnected) { load(); loadFeed(); } }, 30000);
}

function _connectStream() {
  const stream = new EventSource('/api/stream');
  stream.addEventListener('stats', e => renderStats(JSON.parse(e.data)));
  stream.addEventListener('latency', e => {
    const d = JSON.parse(e.data);
    _pushLatencySample(d.db_query_ms, d.discord_ping_ms);
  });
  stream.addEventListener('feed', e => _feedPrepend(JSON.parse(e.data)));
  stream.onopen  = () => { _streamConnected = true; };
  stream.onerror = () => { _streamConnected = false; _startPollFallback(); };
}

const STAT_TIPS = {
  'mc-users':   'Citizens who have sent at least one rated message, across every server.',
  'mc-guilds':  'Number of Discord servers currently running this bot.',
  'mc-dau':     'Citizens with at least one rated message in the last 24 hours.',
  'mc-mps':     'Lifetime average messages processed per second since the bot first started.',
  'mc-ping':    'Round-trip latency to Discord\'s gateway.',
  'mc-db':      'Time for a trivial query to round-trip to the database.',
  'mc-uptime':  'Time since the bot process last started.',
  'mc-workers': 'Active / max sentiment-analysis worker processes.',
  'mc-mag':     'The server with the most rated messages all-time. Server identity is anonymized.',
  'mc-wau':     'Citizens with at least one rated message in the last 7 days.',
  'tl-joins-val':       'New servers added over the selected time range.',
  'act-ev':     'Score-changing events (messages, endorsements, etc.) in the last 24 hours.',
  'act-pos':    'Positive score events in the last 24 hours.',
  'act-neg':    'Negative score events in the last 24 hours.',
  'act-net7':   'Sum of every citizen\'s score change over the last 7 days.',
  'ci-today':   'Citizens who have checked in today.',
  'ci-rate':    'Check-ins today divided by daily active users.',
  'ci-streak':  'Longest check-in streak ever recorded by any single citizen.',
  'ci-votes':   'Total top.gg votes received, all-time.',
  'pr-ev':      'Propaganda events that have been run.',
  'pr-subs':    'Total submissions across all propaganda events.',
  'ec-circ':    'Total yuan currently held by all citizens combined.',
  'ec-earn':    'Total yuan ever earned, all-time.',
  'ec-spent':   'Total yuan ever spent in the shop, all-time.',
  'ec-items':   'Total shop items purchased, all-time.',
  'ec-fx':      'Currently active shop effects (freezes, etc.) across all citizens.',
  'ec-fr':      'Total yuan raised through fundraisers, all-time.',
  'ec-treasury': 'Total yuan seized by the Bureau wealth tax on high-balance citizens, all-time.',
  'tl-yuan-val':      'Yuan in circulation trend, sampled once daily — may lag the live "In Circulation" total above by up to 24h.',
  'tl-portfolio-val': 'Combined value of every citizen\'s stock and turbo holdings over the selected time range.',
  'ec-rich':    'The highest yuan balance currently held by any single citizen.',
  'mk-stocks':  'Total yuan currently invested in stocks across all portfolios.',
  'mk-turbos':  'Total yuan currently committed to open turbo certificate positions.',
  'mk-trades':  'Total stock trades executed, all-time.',
  'lt-played':  'Total lottery tickets purchased, all-time.',
  'lt-won':     'Lottery tickets won, all-time.',
  'lt-net':     'Net yuan won or lost by all citizens combined, all-time.',
  'lt-edge':    'House edge: net winnings or losses divided by tickets played.',
  'mk-ko':      'Turbo certificate positions knocked out, all-time.',
  'sc-avg':     'Average social credit score across all citizens who have chatted.',
  'sc-high':    'Highest score ever reached by any citizen.',
  'sc-low':     'Lowest score ever reached by any citizen.',
  'sc-msgs':    'Total messages that have been scored, all-time.',
  'sc-ampu':    'Average rated messages per citizen.',
  'sc-end':     'Total endorsements given, all-time.',
  'adv-pos':    'Total positive score events, all-time.',
  'adv-neg':    'Total negative score events, all-time.',
  'adv-avd':    'Average score change per event, all-time.',
  'adv-pw':     'Citizens who have won a propaganda event.',
  'adv-pe':     'Average submissions per propaganda event.',
  'adv-er':     'Share of all endorsements and rebukes that were endorsements.',
  'tl-social-val': 'Endorsements plus rebukes given over the selected time range.',
  'sc-reb':     'Total rebukes given, all-time.',
  'tl-dblatency-val': 'Rolling database round-trip time, sampled live.',
  'cmd-today': 'Commands run since midnight UTC. Resets to 0 at 00:00 UTC.',
  'cmd-24h':   'Rolling window: commands run in the last 24 hours, regardless of the calendar day.',
};

function _initTooltips() {
  Object.entries(STAT_TIPS).forEach(([id, text]) => {
    const valEl = document.getElementById(id);
    if (!valEl) return;
    const tile = valEl.closest('.sc');
    if (!tile) return;
    const lbl = tile.querySelector('.lbl');
    if (!lbl || lbl.querySelector('.stat-tip')) return;
    const icon = document.createElement('span');
    icon.className = 'stat-tip';
    icon.textContent = '?';
    icon.setAttribute('data-bs-toggle', 'tooltip');
    icon.setAttribute('data-bs-placement', 'top');
    icon.setAttribute('title', text);
    lbl.appendChild(icon);
    if (window.bootstrap) new bootstrap.Tooltip(icon);
  });
}

// ── Command Analytics ────────────────────────────────────────────────────────

let _cmdRange = '7d';
let _cmdLoaded = false;

function _barChart(canvasId, labels, datasets, opts = {}) {
  const el = document.getElementById(canvasId);
  if (!el) return;
  if (_charts[canvasId]) { _charts[canvasId].destroy(); delete _charts[canvasId]; }
  const horiz = !!opts.horizontal;
  // For the category axis (labels), don't set a callback — Chart.js handles it.
  // Only apply a format callback to the value axis.
  const xTicks = { font: { size: 9 }, color: '#61677A', ...(horiz && opts.xFmt ? { callback: opts.xFmt } : {}) };
  const yTicks = { font: { size: 9 }, color: '#61677A', ...(!horiz && opts.yFmt ? { callback: opts.yFmt } : {}) };
  _charts[canvasId] = new Chart(el.getContext('2d'), {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: horiz ? 'y' : 'x',
      plugins: {
        legend: { display: !!opts.legend, position: 'top', labels: { boxWidth: 10, font: { size: 10 } } },
        tooltip: { mode: 'nearest', axis: horiz ? 'y' : 'x', intersect: true },
      },
      scales: {
        x: { grid: { color: 'rgba(97,103,122,.15)' }, ticks: xTicks },
        y: { grid: { color: 'rgba(97,103,122,.15)' }, ticks: yTicks },
      },
    },
  });
}

async function loadCommandAnalytics(range) {
  if (range) {
    _cmdRange = range;
    document.querySelectorAll('#cmd-range-group button').forEach(b => {
      b.classList.toggle('active', b.dataset.range === range);
    });
  }

  const res = await fetch('/api/stats/commands?range=' + _cmdRange);
  if (!res.ok) return;
  const d = await res.json();
  _cmdLoaded = true;

  // Overview cards
  const t = d.totals || {};
  set('cmd-total',   fmt(t.total_executions || 0));
  set('cmd-today',   fmt(t.executions_today || 0));
  set('cmd-24h',     fmt(t.executions_24h || 0));
  set('cmd-users',   fmt(t.unique_users || 0));
  set('cmd-avgms',   (t.avg_execution_time_ms || 0).toFixed(0) + 'ms');
  set('cmd-success', (t.overall_success_rate || 100).toFixed(1) + '%');

  // Usage over time (line chart)
  const days      = d.usage_per_day || [];
  const dayLabels = days.map(r => _dayLabel(r.day));
  const dayUses   = days.map(r => r.uses);
  _multiLineChart('chart-cmd-timeline', dayLabels, [
    { label: 'Executions', data: dayUses, borderColor: '#F5A855', backgroundColor: '#F5A85522', fill: true, tension: .3 },
  ]);

  // Usage by hour bar chart
  const hourBuckets = Array.from({ length: 24 }, (_, i) => ({ hour: i, uses: 0 }));
  (d.usage_per_hour || []).forEach(r => { if (r.hour >= 0 && r.hour < 24) hourBuckets[r.hour].uses = r.uses; });
  const hourLabels = hourBuckets.map(r => r.hour + ':00');
  const hourUses   = hourBuckets.map(r => r.uses);
  _barChart('chart-cmd-hour', hourLabels, [
    { label: 'Uses', data: hourUses, backgroundColor: '#45C07A', borderRadius: 2 },
  ], { xFmt: v => v });

  // Avg execution time (horizontal bar)
  const execRows    = (d.average_execution_time || []).slice(0, 8);
  const execLabels  = execRows.map(r => r.command);
  const execValues  = execRows.map(r => r.avg_ms);
  _barChart('chart-cmd-exectime', execLabels, [
    { label: 'Avg ms', data: execValues, backgroundColor: '#F4E557', borderRadius: 3 },
  ], { horizontal: true, yFmt: v => v, xFmt: v => v + 'ms' });

  // Success vs error rate (stacked bar per command, top 8)
  const rateRows    = (d.per_command_rates || []).slice(0, 8);
  const rateLabels  = rateRows.map(r => r.command);
  const successPcts = rateRows.map(r => r.success_pct);
  const errorPcts   = rateRows.map(r => r.error_pct);
  _barChart('chart-cmd-rates', rateLabels, [
    { label: 'Success %', data: successPcts, backgroundColor: '#3DAA6E', borderRadius: 2, stack: 'r' },
    { label: 'Error %',   data: errorPcts,   backgroundColor: '#E85454', borderRadius: 2, stack: 'r' },
  ], { legend: true, horizontal: true, yFmt: v => v, xFmt: v => v + '%' });

  // Build unique-users and avg-exec-time maps for the top-commands table
  const uniqueMap  = {};
  (d.unique_users_per_command || []).forEach(r => { uniqueMap[r.command] = r.unique_users; });
  const execMap    = {};
  (d.average_execution_time || []).forEach(r => { execMap[r.command] = r.avg_ms; });
  const rateMap    = {};
  (d.per_command_rates || []).forEach(r => { rateMap[r.command] = r; });

  // Top commands table
  const tbody = document.getElementById('cmd-table-top-body');
  if (tbody) {
    if (!topCmds.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="sub text-center py-3">No data yet — commands will appear once the bot is used.</td></tr>';
    } else {
      tbody.innerHTML = topCmds.map((r, i) => {
        const rate    = rateMap[r.command] || {};
        const sucPct  = rate.success_pct != null ? rate.success_pct.toFixed(1) + '%' : '—';
        const avgMs   = execMap[r.command] != null ? execMap[r.command].toFixed(0) + 'ms' : '—';
        const uniq    = uniqueMap[r.command] != null ? fmt(uniqueMap[r.command]) : '—';
        const rankCls = i === 0 ? 'gold' : i === 1 ? 'silver' : i === 2 ? 'bronze' : '';
        return `<tr>
          <td class="rank-cell lb-rank ${rankCls}">${i + 1}</td>
          <td><strong>/${r.command}</strong></td>
          <td>${fmt(r.uses)}</td>
          <td>${uniq}</td>
          <td class="${rate.success_pct >= 95 ? 'trend-up' : rate.success_pct < 80 ? 'trend-down' : ''}">${sucPct}</td>
          <td>${avgMs}</td>
        </tr>`;
      }).join('');
    }
  }

  // All commands table
  const allBody = document.getElementById('cmd-table-all');
  if (allBody) {
    const allRows = d.all_commands || [];
    if (!allRows.length) {
      allBody.innerHTML = '<tr><td colspan="5" class="sub text-center py-3">No commands recorded yet.</td></tr>';
    } else {
      let rank = 0;
      let prevCmd = null;
      allBody.innerHTML = allRows.map(r => {
        const isNewCmd = r.command !== prevCmd;
        if (isNewCmd) { rank++; prevCmd = r.command; }
        const rankCell = isNewCmd
          ? `<td class="rank-cell lb-rank" rowspan="1">${rank}</td>`
          : '<td class="rank-cell lb-rank" style="color:transparent">·</td>';
        const cmdCell = isNewCmd
          ? `<td><strong>/${r.command}</strong></td>`
          : '<td></td>';
        const sub = r.subcommand ? `<span class="text-muted" style="font-size:.78rem">${r.subcommand}</span>` : '<span class="text-muted">—</span>';
        return `<tr>${rankCell}${cmdCell}<td>${sub}</td><td>${fmt(r.uses)}</td><td>${fmt(r.unique_users)}</td></tr>`;
      }).join('');
    }
  }

  // Recent activity table
  const recentBody = document.getElementById('cmd-table-recent');
  if (recentBody) {
    const rows = d.newest_commands || [];
    if (!rows.length) {
      recentBody.innerHTML = '<tr><td colspan="6" class="sub text-center py-3">No recent activity.</td></tr>';
    } else {
      recentBody.innerHTML = rows.map(r => {
        const dt    = new Date(r.timestamp * 1000);
        const t     = dt.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const user  = r.user || (r.user_id ? `User #${String(r.user_id).slice(-6)}` : '—');
        const sub   = r.subcommand ? `<span class="text-muted">${r.subcommand}</span>` : '<span class="text-muted">—</span>';
        const ms    = r.execution_time_ms != null ? r.execution_time_ms + 'ms' : '—';
        const badge = r.success
          ? '<span class="cmd-badge-ok">OK</span>'
          : `<span class="cmd-badge-err">${r.error_code || 'ERR'}</span>`;
        return `<tr>
          <td class="text-muted" style="font-size:.68rem">${t}</td>
          <td class="text-muted" style="font-size:.72rem">${user}</td>
          <td><strong>/${r.command_name}</strong></td>
          <td>${sub}</td>
          <td>${ms}</td>
          <td>${badge}</td>
        </tr>`;
      }).join('');
    }
  }
}

// ── End Command Analytics ────────────────────────────────────────────────────

load();
loadAnnouncement();
loadActivity('7d');
loadYuanCirculation();
loadFeed();
_connectStream();
_initTooltips();
setInterval(() => loadActivity(_activityRange), 300000);
setInterval(loadYuanCirculation, 300000);
setInterval(loadAnnouncement, 60000);
setInterval(() => { if (_cmdLoaded) loadCommandAnalytics(); }, 30000);

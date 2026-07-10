/* account.js v2 */
(function () {
  'use strict';

  function _esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _timeAgo(ts) {
    if (!ts) return '';
    const diff = Math.floor(Date.now() / 1000) - ts;
    if (diff < 60)    return t('just now');
    if (diff < 3600)  return Math.floor(diff/60) + t('m_ago');
    if (diff < 86400) return Math.floor(diff/3600) + t('h_ago');
    const d = Math.floor(diff / 86400);
    return d === 1 ? '1' + t('day_ago') : d + t('days_ago');
  }

  function _hex(n) {
    return '#' + ('000000' + (n >>> 0).toString(16)).slice(-6);
  }

  // ── Live Trade-Republic-style chart helpers ────────────────────────────────

  const _COLOR_UP   = '#26a69a';
  const _COLOR_DOWN = '#ef5350';
  const _COLOR_FLAT = '#7D9D9C';

  const _chartCrosshairPlugin = {
    id: 'crosshair',
    afterDatasetsDraw(chart) {
      if (chart._hoverIdx == null) return;
      const { ctx, chartArea } = chart;
      const meta = chart.getDatasetMeta(0);
      if (!meta.data[chart._hoverIdx]) return;
      const { x, y } = meta.data[chart._hoverIdx].getProps(['x', 'y'], true);
      if (!isFinite(x) || !isFinite(y)) return;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.strokeStyle = 'rgba(255,255,255,.2)';
      ctx.lineWidth   = 1;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fillStyle = chart._dotColor || _COLOR_UP;
      ctx.fill();
      ctx.restore();
    },
  };

  function _trendColor(values, dayOpen) {
    if (dayOpen == null || !values.length) return _COLOR_FLAT;
    return values[values.length - 1] >= dayOpen ? _COLOR_UP : _COLOR_DOWN;
  }

  function _hexAlpha(hex, a) {
    const n = parseInt(hex.replace('#', ''), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  function _makeGradientFn(color) {
    return function(context) {
      const chart = context.chart;
      const { ctx, chartArea } = chart;
      if (!chartArea) return _hexAlpha(color, 0.15);
      const g = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
      g.addColorStop(0, _hexAlpha(color, 0.28));
      g.addColorStop(1, _hexAlpha(color, 0.00));
      return g;
    };
  }

  function _startDotAnim(chart, overlayId) {
    if (!chart || chart._dotAnimId) return;
    const oc = document.getElementById(overlayId);
    if (!oc) return;
    const oct = oc.getContext('2d');

    function frame() {
      if (!chart.canvas || !chart.canvas.isConnected) { chart._dotAnimId = null; return; }

      // Keep overlay sized to match the chart canvas (handles resizes).
      if (oc.width !== chart.canvas.width || oc.height !== chart.canvas.height) {
        oc.width        = chart.canvas.width;
        oc.height       = chart.canvas.height;
        oc.style.width  = chart.canvas.style.width;
        oc.style.height = chart.canvas.style.height;
      }

      const meta = chart.getDatasetMeta(0);
      if (!meta || !meta.data.length) { chart._dotAnimId = requestAnimationFrame(frame); return; }

      const { x, y } = meta.data[meta.data.length - 1].getProps(['x', 'y'], true);
      if (!isFinite(x) || !isFinite(y)) { chart._dotAnimId = requestAnimationFrame(frame); return; }

      const dpr   = window.devicePixelRatio || 1;
      const pulse = (Math.sin(Date.now() / 550) + 1) / 2;

      oct.clearRect(0, 0, oc.width, oc.height);
      oct.save();
      oct.scale(dpr, dpr);

      oct.beginPath();
      oct.arc(x, y, 5 + pulse * 7, 0, Math.PI * 2);
      oct.fillStyle = _hexAlpha(chart._dotColor, 0.06 + pulse * 0.18);
      oct.fill();

      oct.beginPath();
      oct.arc(x, y, 4.5, 0, Math.PI * 2);
      oct.fillStyle = chart._dotColor;
      oct.fill();

      oct.restore();

      chart._dotAnimId    = requestAnimationFrame(frame);
      chart._dotOverlayId = overlayId;
    }

    chart._dotAnimId = requestAnimationFrame(frame);
  }

  function _stopDotAnim(chart) {
    if (!chart || !chart._dotAnimId) return;
    cancelAnimationFrame(chart._dotAnimId);
    chart._dotAnimId = null;
    const oc = chart._dotOverlayId && document.getElementById(chart._dotOverlayId);
    if (oc) oc.getContext('2d').clearRect(0, 0, oc.width, oc.height);
  }

  function _setWealth(yuan, holdings, turbos, market) {
    const wrap = document.getElementById('port-wealth');
    if (!wrap) return;
    wrap.style.display = '';
    document.getElementById('port-yuan').textContent = _fmtYuan(yuan);
    const hv = (holdings || []).reduce((s, h) => s + (h.value || 0), 0);
    const tv = (turbos   || []).reduce((s, p) => s + (p.value || 0), 0);
    document.getElementById('port-networth').textContent = _fmtYuan(Math.round(yuan + hv + tv));
    const $mkt = document.getElementById('port-mkt-status');
    if ($mkt && market) {
      const anyOpen = Object.values(market).some(m => m && m.open);
      $mkt.textContent = anyOpen ? t('Market Open') : t('Market Closed');
      $mkt.className   = 'port-mkt-status-pill ' + (anyOpen ? 'port-mkt-status-open' : 'port-mkt-status-closed');
    }
  }

  function _fmtYuan(n) {
    return '¥' + Number(n).toLocaleString();
  }

  function _fmtPrice(p) {
    if (p >= 100) return '¥' + Number(p).toFixed(2);
    if (p >= 1)   return '¥' + Number(p).toFixed(3);
    return '¥' + Number(p).toFixed(4);
  }

  function _pnlClass(n) { return n >= 0 ? 'pnl-pos' : 'pnl-neg'; }

  function _pnlFmt(n) {
    const sign = n >= 0 ? '+' : '-';
    return sign + '¥' + Math.abs(n).toLocaleString();
  }

  // ── Overview ──────────────────────────────────────────────────────────────

  function renderIdentity(d) {
    const $av  = document.getElementById('acc-avatar');
    const $un  = document.getElementById('acc-username');
    const $sub = document.getElementById('acc-sub');
    if (d.avatar) {
      $av.innerHTML = `<img src="https://cdn.discordapp.com/avatars/${_esc(d.id)}/${_esc(d.avatar)}.png?size=128" alt="">`;
    } else {
      $av.innerHTML = `<div class="acc-avatar-placeholder">${_esc(d.username.slice(0,2).toUpperCase())}</div>`;
    }
    $un.textContent  = '@' + d.username;
    $sub.textContent = 'Discord ID: ' + d.id;
  }

  function renderCounters(c) {
    document.getElementById('s-checkin').textContent      = c.checkin_streak      ?? 0;
    document.getElementById('s-checkin-best').textContent = c.checkin_best        ?? 0;
    document.getElementById('s-votes').textContent        = c.vote_total          ?? 0;
    document.getElementById('s-vote-streak').textContent  = c.vote_streak         ?? 0;
    document.getElementById('s-prestige').textContent     = c.prestige_level      ?? 0;
    document.getElementById('s-gacha').textContent        = c.gacha_contributions ?? 0;
  }

  function renderGuilds(guilds) {
    const $el = document.getElementById('acc-guilds');
    if (!guilds.length) {
      $el.innerHTML = `<div class="acc-empty">${t('No servers found.')}</div>`;
      return;
    }
    $el.innerHTML = `<table class="acc-guild-table">
      <thead><tr>
        <th>${t('Server')}</th><th>${t('Score')}</th><th>¥ Yuan</th><th>${t('Rank')}</th>
      </tr></thead>
      <tbody>
        ${guilds.map(g => {
          const name = g.guild_name || ('…' + g.guild_id.slice(-4));
          return `<tr>
            <td><span class="acc-guild-name">${_esc(name)}</span></td>
            <td>${(+g.score).toFixed(2)}</td>
            <td>¥${Number(g.yuan).toLocaleString()}</td>
            <td><span class="acc-rank-pill">${_esc(g.rank || '–')}</span></td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>`;
  }

  function renderRequests(requests) {
    const $el = document.getElementById('acc-requests');
    if (!requests.length) {
      $el.innerHTML = `<div class="acc-empty">${t('No submissions yet.')} <a href="/social-credit/submit" style="color:var(--sage)">${t('Suggest a character!')}</a></div>`;
      return;
    }
    $el.innerHTML = requests.map(r => {
      const pill     = `<span class="acc-status-pill acc-status-${_esc(r.status)}">${_esc(t(r.status))}</span>`;
      const wikiLink = `<a href="https://en.wikipedia.org/wiki/${encodeURIComponent(r.wiki_slug)}" target="_blank" rel="noopener" style="font-size:.72rem;color:var(--sage);text-decoration:none">Wikipedia ↗</a>`;
      const votes    = `<div class="acc-vote-badge">${r.vote_count} ${t(r.vote_count === 1 ? 'vote' : 'votes')}</div>`;
      const withdraw = r.status === 'pending'
        ? `<button class="acc-withdraw-btn" onclick="_withdrawRequest(${r.id}, this)">${t('Withdraw')}</button>`
        : '';
      return `<div class="acc-req-row" id="req-row-${r.id}">
        <div class="acc-req-meta">
          <div class="acc-req-title">${_esc(r.wiki_title)}</div>
          <div class="acc-req-sub">${t('submitted')} ${_timeAgo(r.submitted_at)}</div>
        </div>
        <div style="display:flex;align-items:center;gap:.6rem;flex-shrink:0;flex-wrap:wrap">
          ${votes}${pill}${withdraw}${wikiLink}
        </div>
      </div>`;
    }).join('');
  }

  window._withdrawRequest = async function(requestId, btn) {
    if (!confirm(t('Withdraw this character suggestion? This cannot be undone.'))) return;
    btn.disabled   = true;
    btn.textContent = t('Withdrawing…');

    const r = await fetch('/api/requests/delete', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId }),
    });
    const result = await r.json();

    if (!r.ok) {
      btn.disabled    = false;
      btn.textContent = t('Withdraw');
      alert(result.error || 'Failed to withdraw.');
      return;
    }

    const row = document.getElementById('req-row-' + requestId);
    if (row) row.remove();

    const $el = document.getElementById('acc-requests');
    if ($el && !$el.querySelector('.acc-req-row')) {
      $el.innerHTML = `<div class="acc-empty">${t('No submissions yet.')} <a href="/social-credit/submit" style="color:var(--sage)">${t('Suggest a character!')}</a></div>`;
    }
  };

  function renderAchievements(achievements) {
    const $el  = document.getElementById('acc-achievements');
    const $cnt = document.getElementById('acc-ach-count');
    $cnt.textContent = achievements.length + ' ' + t('unlocked');
    if (!achievements.length) {
      $el.innerHTML = `<div class="acc-empty">${t('No achievements unlocked yet.')}</div>`;
      return;
    }
    $el.innerHTML = achievements.map(a => {
      const tierClass = 'tier-' + (a.tier || 'silent');
      const date      = a.unlocked_at ? _timeAgo(a.unlocked_at) : '';
      const pct       = typeof a.pct === 'number' ? a.pct.toFixed(1) + '%' : null;
      return `<div class="acc-ach-card ${tierClass}">
        <div class="acc-ach-name">${_esc(a.name)}</div>
        <div class="acc-ach-desc">${_esc(a.description)}</div>
        ${date ? `<div class="acc-ach-date">${t('Unlocked')} ${date}</div>` : ''}
        ${pct ? `<div class="acc-ach-pct">${pct}</div>` : ''}
      </div>`;
    }).join('');
  }

  function renderBadges(badges, badgePref) {
    const $el = document.getElementById('acc-badges');
    if (!badges.length) {
      $el.innerHTML = `<div class="acc-empty">${t('No cosmetic badges yet.')}</div>`;
      return;
    }
    $el.innerHTML = badges.map(b => {
      const color    = _hex(b.color || 0x7D9D9C);
      const isActive = b.id === badgePref;
      return `<div class="acc-badge-card">
        ${isActive ? `<span class="acc-badge-active">${t('ACTIVE')}</span>` : ''}
        <div class="acc-badge-label">
          <span class="acc-badge-dot" style="background:${color}"></span>
          ${_esc(b.label)}
        </div>
        ${b.note ? `<div class="acc-badge-note">${_esc(b.note)}</div>` : ''}
      </div>`;
    }).join('');
  }

  function showContentError(msg) {
    ['acc-guilds','acc-requests','acc-achievements','acc-badges'].forEach(id => {
      document.getElementById(id).innerHTML = `<div class="acc-empty">${msg}</div>`;
    });
  }

  function showLoggedOut() {
    const identity = document.getElementById('acc-identity');
    if (identity) {
      identity.innerHTML = `
        <div class="acc-info" style="flex:1">
          <div class="acc-username">${t('You have been logged out.')}</div>
        </div>
        <a href="/social-credit/auth/discord?next=/social-credit/account" class="acc-logout-btn">${t('Log in')}</a>
      `;
    }
    ['acc-guilds','acc-requests','acc-achievements','acc-badges'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = `<div class="acc-empty">${t('Log in to view your account.')}</div>`;
    });
    const stats = document.getElementById('acc-stats-global');
    if (stats) stats.querySelectorAll('.n').forEach(el => { el.textContent = '–'; });
  }

  // ── Portfolio ─────────────────────────────────────────────────────────────

  let _accountData       = null;
  let _portLastData      = null;
  let _portTurbAvail     = null;
  let _portGuildId       = null;
  let _portChart         = null;
  let _portPeriod        = '1D';
  let _tradeMode         = null;
  let _tradeTicker       = null;
  let _tradePrice        = 0;
  let _tradeGuild        = null;
  let _turboOpenId       = null;
  let _turboGuild        = null;
  let _tradeModal        = null;
  let _turboModal        = null;
  let _portPrevPrices    = {};
  let _portPollInterval  = null;
  let _portPeriodStart   = null;
  let _portAnimateNext   = false;
  let _portLiveBuffer    = [];     // {ts, value} collected every 10s, up to 1h
  let _tickerLiveBuffer  = {};     // ticker → [{ts, price}]

  const _PERIOD_SECS = { '5M': 300, '1H': 3600, '6H': 21600, '1D': 86400, '7D': 604800, '1M': 2592000 };

  function _interpolatePoints(points, stepSecs) {
    if (points.length < 2) return points;
    const out = [];
    for (let i = 0; i < points.length - 1; i++) {
      const a = points[i], b = points[i + 1];
      out.push(a);
      const steps = Math.floor((b.ts - a.ts) / stepSecs);
      for (let s = 1; s < steps; s++) {
        const frac   = s / steps;
        const base   = a.value + (b.value - a.value) * frac;
        const jitter = (Math.random() - 0.5) * base * 0.002;
        out.push({ ts: a.ts + s * stepSecs, value: Math.max(0, base + jitter) });
      }
    }
    out.push(points[points.length - 1]);
    return out;
  }

  function _portChartFade(show) {
    const c = document.getElementById('port-chart');
    if (c) c.style.opacity = show ? '' : '0';
  }

  function _refreshPeriodReturn() {
    if (_portPeriodStart == null || !_portLastData) return;
    const currentVal = (_portLastData.holdings || []).reduce((s, h) => s + (h.value || 0), 0)
                     + (_portLastData.turbos   || []).reduce((s, p) => s + (p.value || 0), 0);
    if (!currentVal || !_portPeriodStart) return;
    const delta = currentVal - _portPeriodStart;
    const pct   = delta / _portPeriodStart * 100;
    const sign  = delta >= 0 ? '+' : '-';
    const $lbl  = document.getElementById('port-sum-pnl-label');
    const $pnl  = document.getElementById('port-summary-pnl');
    if ($lbl) $lbl.textContent = _portPeriod + ' Return';
    if ($pnl) {
      $pnl.className   = delta >= 0 ? 'port-sum-pnl-pos' : 'port-sum-pnl-neg';
      $pnl.textContent = sign + '¥' + Math.abs(Math.round(delta)).toLocaleString()
                       + ' (' + (delta >= 0 ? '+' : '') + pct.toFixed(2) + '%)';
    }
  }

  function renderSummaryBar(holdings, turbos) {
    const totalValue   = holdings.reduce((s, h) => s + h.value, 0) + turbos.reduce((s, p) => s + p.value, 0);
    const hasSomething = holdings.length > 0 || turbos.length > 0;

    document.getElementById('port-summary').style.display = hasSomething ? '' : 'none';
    if (!hasSomething) return;

    document.getElementById('port-summary-value').textContent = _fmtYuan(Math.round(totalValue));
    _refreshPeriodReturn();
  }

  function _flashCell(cell, newPrice, prevPrice) {
    if (typeof prevPrice !== 'number' || prevPrice === newPrice) return;
    cell.classList.remove('price-flash-up', 'price-flash-down');
    void cell.offsetWidth;
    cell.classList.add(newPrice > prevPrice ? 'price-flash-up' : 'price-flash-down');
  }

  function _pushLiveChartPoint(currentVal) {
    if (currentVal != null) {
      _portLiveBuffer.push({ ts: Date.now() / 1000, value: currentVal });
      if (_portLiveBuffer.length > 360) _portLiveBuffer.shift();
    }
    if (!_portChart || _portPeriodStart == null || currentVal == null) return;
    const pct    = +((currentVal - _portPeriodStart) / _portPeriodStart * 100).toFixed(4);
    const now    = new Date();
    const _short = new Set(['5M', '1H', '6H', '1D', '5D']);
    const label  = _short.has(_portPeriod)
      ? now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      : now.toLocaleDateString([], { month: 'short', day: 'numeric' });
    _portChart.data.labels.push(label);
    _portChart.data.datasets[0].data.push(pct);
    _portChart.data.datasets[1].data.push(0);
    const color = pct >= 0 ? _COLOR_UP : _COLOR_DOWN;
    if (_portChart.data.datasets[0].borderColor !== color) {
      _portChart.data.datasets[0].borderColor = color;
      _portChart._dotColor = color;
    }
    _portChart.update('none');
  }

  function _pushLiveTurboChartPoint(price) {
    if (!_turboChart) return;
    const now    = new Date();
    const _short = new Set(['5M', '1H', '6H', '1D', '5D']);
    const label  = _short.has(_turboChartPeriod)
      ? now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      : now.toLocaleDateString([], { month: 'short', day: 'numeric' });
    _turboChart.data.labels.push(label);
    const ds0 = _turboChart.data.datasets[0];
    ds0.data.push(price);
    for (let i = 1; i < _turboChart.data.datasets.length; i++) {
      const ds = _turboChart.data.datasets[i];
      ds.data.push(ds.data[ds.data.length - 1] ?? price);
    }
    const dayOpenDs = _turboChart.data.datasets.find(d => d.label === 'Day Open');
    const color = _trendColor(ds0.data, dayOpenDs?.data[0]);
    if (ds0.borderColor !== color) {
      ds0.borderColor       = color;
      _turboChart._dotColor = color;
    }
    _turboChart.update('none');
  }

  function _applyPriceUpdates(data) {
    renderMarketStatus(data.market);
    renderSummaryBar(data.holdings, data.turbos);
    const liveVal = (data.holdings || []).reduce((s, h) => s + (h.value || 0), 0)
                  + (data.turbos   || []).reduce((s, p) => s + (p.value || 0), 0);
    _pushLiveChartPoint(liveVal);

    if (_turboChartTicker && _turboChart) {
      const td = (data.all_tickers || []).find(t => t.ticker === _turboChartTicker);
      if (td) _pushLiveTurboChartPoint(td.current_price);
    }

    for (const h of data.holdings) {
      const row = document.querySelector(`#port-holdings [data-ticker="${h.ticker}"]`);
      if (!row) { renderHoldings(data.holdings, _portGuildId, data.market); break; }
      const priceCell = row.querySelector('.port-cell-price');
      if (priceCell) {
        _flashCell(priceCell, h.current_price, _portPrevPrices[h.ticker]);
        priceCell.textContent = _fmtPrice(h.current_price);
      }
      const valCell = row.querySelector('.port-cell-value');
      if (valCell) valCell.textContent = _fmtYuan(h.value);
      const dayEl = row.querySelector('.hold-day');
      if (dayEl && h.day_pct != null) {
        const sign = h.day_pct >= 0 ? '+' : '';
        dayEl.textContent = sign + h.day_pct.toFixed(2) + '%';
        dayEl.className = 'hold-day ' + (h.day_pct >= 0 ? 'hold-up' : 'hold-dn');
      }
      const totEl = row.querySelector('.hold-total');
      if (totEl) {
        const sign = h.pnl >= 0 ? '+' : '';
        totEl.textContent = sign + '¥' + Math.abs(h.pnl).toLocaleString() + ' (' + sign + h.pnl_pct.toFixed(2) + '%)';
        totEl.className = 'hold-total ' + (h.pnl >= 0 ? 'hold-up' : 'hold-dn');
      }
      _portPrevPrices[h.ticker] = h.current_price;
    }

    renderOpenTurbos(data.turbos, _portGuildId, data.market);

    for (const ticker of (data.all_tickers || [])) {
      const row = document.querySelector(`#port-market [data-ticker="${ticker.ticker}"]`);
      if (!row) continue;
      const key       = 'm:' + ticker.ticker;
      const priceCell = row.querySelector('.port-cell-price');
      if (priceCell) {
        _flashCell(priceCell, ticker.current_price, _portPrevPrices[key]);
        priceCell.textContent = _fmtPrice(ticker.current_price);
      }
      _portPrevPrices[key] = ticker.current_price;
      if (!_tickerLiveBuffer[ticker.ticker]) _tickerLiveBuffer[ticker.ticker] = [];
      _tickerLiveBuffer[ticker.ticker].push({ ts: Date.now() / 1000, price: ticker.current_price });
      if (_tickerLiveBuffer[ticker.ticker].length > 360) _tickerLiveBuffer[ticker.ticker].shift();
    }
  }

  async function _silentRefreshPortfolio() {
    if (!_portGuildId) return;
    try {
      const portRes = await fetch(`/api/account/portfolio?guild_id=${_portGuildId}`, { credentials: 'same-origin' });
      if (!portRes.ok) return;
      const data = await portRes.json();
      _portLastData = data;
      _setWealth(data.yuan, data.holdings, data.turbos, data.market);
      _applyPriceUpdates(data);
    } catch (_) {}
  }

  function _startPortPoll() {
    if (_portPollInterval) return;
    _portPollInterval = setInterval(_silentRefreshPortfolio, 10000);
  }

  function _stopPortPoll() {
    if (_portPollInterval) { clearInterval(_portPollInterval); _portPollInterval = null; }
  }

  function _marketBadge(exchange, market) {
    if (!market || !market[exchange]) return '';
    const open  = market[exchange].open;
    return `<span class="${open ? 'port-mkt-open' : 'port-mkt-closed'}">${open ? t('OPEN') : t('CLOSED')}</span>`;
  }

  const _EX_DISPLAY = { NYSE: 'NYSE · New York', LSE: 'LSE · London', TSE: 'TSE · Tokyo' };

  function _exTimingText(info) {
    if (!info || !info.next_ts) return '';
    const diff  = info.next_ts - Date.now() / 1000;
    let rel;
    if (diff < 60)         rel = t('in <1 min');
    else if (diff < 3600)  rel = `in ${Math.round(diff / 60)}m`;
    else if (diff < 86400) rel = `in ${Math.floor(diff / 3600)}h ${Math.round((diff % 3600) / 60)}m`;
    else                   rel = `in ${Math.floor(diff / 86400)}d`;
    const d     = new Date(info.next_ts * 1000);
    const time  = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const label = info.open ? t('Closes') : t('Opens');
    return `${label} ${time} (${rel})`;
  }

  function renderMarketStatus(market) {
    const $el = document.getElementById('port-market-status');
    if (!$el || !market) return;
    const pills = Object.entries(_EX_DISPLAY).map(([ex, label]) => {
      const info = market[ex];
      if (!info) return '';
      const tip   = _exTimingText(info);
      const badge = `<span class="${info.open ? 'port-mkt-open' : 'port-mkt-closed'}">${info.open ? t('OPEN') : t('CLOSED')}</span>`;
      return `<div class="port-ex-pill"${tip ? ` data-tip="${tip}"` : ''}><span class="port-ex-name">${label}</span>${badge}</div>`;
    }).filter(Boolean);
    if (!pills.length) return;
    $el.innerHTML  = pills.join('');
    $el.style.display = '';
  }

  function initPortfolio(guilds) {
    const sel = document.getElementById('port-guild-select');
    guilds.forEach(g => {
      const name = g.guild_name || ('Server …' + String(g.guild_id).slice(-4));
      const opt  = document.createElement('option');
      opt.value       = g.guild_id;
      opt.textContent = name;
      sel.appendChild(opt);
    });

    sel.addEventListener('change', () => {
      const gid = sel.value;
      _stopPortPoll();
      _portPrevPrices   = {};
      _portPeriodStart  = null;
      _portLiveBuffer   = [];
      _tickerLiveBuffer = {};
      if (!gid) {
        document.getElementById('port-content').style.display   = 'none';
        document.getElementById('port-no-server').style.display = '';
        return;
      }
      _portGuildId = gid;
      document.getElementById('port-content').style.display   = '';
      document.getElementById('port-no-server').style.display = 'none';
      loadPortfolio(gid);
    });

    document.querySelectorAll('#port-chart-periods .port-period').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('#port-chart-periods .port-period').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        _portPeriod = btn.dataset.period;
        if (_portGuildId) {
          _portAnimateNext = true;
          _portChartFade(false);
          loadPortfolioHistory(_portGuildId, _portPeriod);
        }
      });
    });

    document.getElementById('port-no-server').style.display = guilds.length ? '' : 'none';
    if (!guilds.length) {
      document.getElementById('port-content').innerHTML = `<div class="acc-empty">${t('You have no servers with this bot.')}</div>`;
    }

    document.querySelectorAll('[data-port-view]').forEach(btn => {
      btn.addEventListener('click', () => {
        const view = btn.dataset.portView;
        document.querySelectorAll('[data-port-view]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('port-view-portfolio').style.display = view === 'portfolio' ? '' : 'none';
        document.getElementById('port-view-stocks').style.display    = view === 'stocks'    ? '' : 'none';
        document.getElementById('port-view-turbos').style.display    = view === 'turbos'    ? '' : 'none';
      });
    });

    const tabLink = document.getElementById('tab-portfolio-link');
    if (tabLink) {
      tabLink.addEventListener('shown.bs.tab', () => { if (_portGuildId) _startPortPoll(); });
      tabLink.addEventListener('hide.bs.tab',  _stopPortPoll);
    }

    const chartModal = document.getElementById('turboChartModal');
    if (chartModal) {
      chartModal.addEventListener('hidden.bs.modal', () => {
        if (_turboChart) { _turboChart._hoverIdx = null; _turboChart.update('none'); }
        document.getElementById('turbo-chart-meta').textContent = '';
      });
    }
  }

  async function loadPortfolio(guildId) {
    document.getElementById('port-holdings').innerHTML     = `<div class="acc-empty">${t('Loading…')}</div>`;
    document.getElementById('port-turbos').innerHTML       = `<div class="acc-empty">${t('Loading…')}</div>`;
    document.getElementById('port-market').innerHTML       = `<div class="acc-empty">${t('Loading…')}</div>`;
    document.getElementById('port-turbos-avail').innerHTML = `<div class="acc-empty">${t('Loading…')}</div>`;

    const [portRes, turbAvailRes] = await Promise.all([
      fetch(`/api/account/portfolio?guild_id=${guildId}`, { credentials: 'same-origin' }),
      fetch(`/api/account/portfolio/turbos/available?guild_id=${guildId}`, { credentials: 'same-origin' }),
    ]);

    if (!portRes.ok) {
      const err = await portRes.json().catch(() => ({}));
      document.getElementById('port-holdings').innerHTML = `<div class="acc-empty">${_esc(err.error || t('Failed to load portfolio.'))}</div>`;
      return;
    }

    const data      = await portRes.json();
    const turbAvail = turbAvailRes.ok ? await turbAvailRes.json() : { turbos: [], min_cost: 100 };
    _portLastData  = data;
    _portTurbAvail = turbAvail;

    _setWealth(data.yuan, data.holdings, data.turbos, data.market);
    renderMarketStatus(data.market);
    renderSummaryBar(data.holdings, data.turbos);
    renderHoldings(data.holdings, guildId, data.market);
    renderOpenTurbos(data.turbos, guildId, data.market);
    renderAllStocks(data.all_tickers || [], guildId, data.market);
    renderTurbosGrouped(turbAvail.turbos, guildId, data.market);
    const minCost = turbAvail.min_cost || 100;
    document.getElementById('port-min-cost').textContent = `Min. ¥${Number(minCost).toLocaleString()}`;

    for (const h of data.holdings) _portPrevPrices[h.ticker] = h.current_price;
    for (const t of (data.all_tickers || [])) _portPrevPrices['m:' + t.ticker] = t.current_price;
    _startPortPoll();

    const _initVal = (data.holdings || []).reduce((s, h) => s + (h.value || 0), 0)
                   + (data.turbos   || []).reduce((s, p) => s + (p.value || 0), 0);
    _portLiveBuffer.push({ ts: Date.now() / 1000, value: _initVal });

    loadPortfolioHistory(guildId, _portPeriod);
  }

  async function loadPortfolioHistory(guildId, period) {
    const r = await fetch(`/api/account/portfolio/history?guild_id=${guildId}&period=${period}`, { credentials: 'same-origin' });
    if (!r.ok) return;
    const data  = await r.json();
    const empty = document.getElementById('port-chart-empty');

    if (!data.points || !data.points.length) {
      empty.style.display = '';
      if (_portChart) { _portChart.data.labels = []; _portChart.data.datasets[0].data = []; _portChart.update(); }
      return;
    }
    empty.style.display = 'none';

    const _shortPeriods = new Set(['5M', '1H', '6H', '1D', '5D']);
    const nowTs    = Date.now() / 1000;
    const cutoff   = nowTs - (_PERIOD_SECS[period] || 86400);
    const lastDbTs = data.points.length ? data.points[data.points.length - 1].ts : cutoff;
    const _interpSecs = { '5M': 10, '7D': 21600, '1M': 86400 };
    const merged = (() => {
      const raw = [
        ...data.points,
        ..._portLiveBuffer.filter(p => p.ts > lastDbTs && p.ts >= cutoff).map(p => ({ ts: p.ts, value: p.value })),
      ];
      const step = _interpSecs[period];
      return step ? _interpolatePoints(raw, step) : raw;
    })();
    const labels = merged.map(p => {
      const d = new Date(p.ts * 1000);
      return _shortPeriods.has(period)
        ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    });

    const values = merged.map(p => p.value);
    _portPeriodStart = values[0] || null;

    // Convert absolute values to % change from the first point in the period.
    // This makes the Y-axis meaningful regardless of portfolio size, matches
    // how Trade Republic / Robinhood display portfolio charts, and lets 0% act
    // as a natural baseline so color (green/red) is always unambiguous.
    const base = values[0] || 1;
    const pcts = values.map(v => +((v - base) / base * 100).toFixed(4));
    const last = pcts[pcts.length - 1] ?? 0;
    const color = last >= 0 ? _COLOR_UP : _COLOR_DOWN;

    const datasets = [
      {
        data:        pcts,
        borderColor: color,
        borderWidth: 2,
        pointRadius: 0,
        fill:        false,
        tension:     0.35,
        order:       1,
      },
      {
        label:       '0%',
        data:        labels.map(() => 0),
        borderColor: 'rgba(255,255,255,.18)',
        borderWidth: 1,
        borderDash:  [4, 4],
        pointRadius: 0,
        fill:        false,
        tension:     0,
        order:       2,
      },
    ];

    if (_portChart) {
      _portChart.data.labels   = labels;
      _portChart.data.datasets = datasets;
      _portChart._dotColor = color;
      _portChart._hoverIdx = null;
      if (_portAnimateNext) {
        _portAnimateNext = false;
        _portChart.update();
        requestAnimationFrame(() => _portChartFade(true));
      } else {
        _portChart.update('none');
      }
    } else {
      const canvas = document.getElementById('port-chart');
      canvas.style.cursor = 'crosshair';
      canvas.addEventListener('mousemove', e => {
        if (!_portChart) return;
        const rect = canvas.getBoundingClientRect();
        const xPos = e.clientX - rect.left;
        const meta = _portChart.getDatasetMeta(0);
        if (!meta.data.length) return;
        let nearIdx = 0, minDist = Infinity;
        for (let i = 0; i < meta.data.length; i++) {
          const { x } = meta.data[i].getProps(['x'], true);
          const d = Math.abs(x - xPos);
          if (d < minDist) { minDist = d; nearIdx = i; }
        }
        _portChart._hoverIdx = nearIdx;
        _portChart.update('none');
        const pct  = _portChart.data.datasets[0].data[nearIdx];
        const lbl  = _portChart.data.labels[nearIdx];
        const $lbl = document.getElementById('port-sum-pnl-label');
        const $pnl = document.getElementById('port-summary-pnl');
        if ($lbl && pct != null) {
          $lbl.textContent = lbl;
          const delta = _portPeriodStart ? pct / 100 * _portPeriodStart : null;
          const sign  = pct >= 0 ? '+' : '-';
          $pnl.textContent = delta != null
            ? sign + '¥' + Math.abs(Math.round(delta)).toLocaleString() + ' (' + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%)'
            : (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
          $pnl.className   = pct >= 0 ? 'port-sum-pnl-pos' : 'port-sum-pnl-neg';
        }
      });
      canvas.addEventListener('mouseleave', () => {
        if (!_portChart) return;
        _portChart._hoverIdx = null;
        _portChart.update('none');
        _refreshPeriodReturn();
      });

      const portCtx = canvas.getContext('2d');
      _portChart = new Chart(portCtx, {
        type:    'line',
        plugins: [_chartCrosshairPlugin],
        data:    { labels, datasets },
        options: {
          responsive:          true,
          maintainAspectRatio: false,
          animation: {
            x: {
              type: 'number', easing: 'linear',
              duration(ctx) { const n = Math.max((ctx.chart.data.labels ?? []).length, 1); return 500 / n; },
              from: NaN,
              delay(ctx) { if (ctx.type !== 'data' || ctx.xStarted) return 0; ctx.xStarted = true; const n = Math.max((ctx.chart.data.labels ?? []).length, 1); return ctx.index * (500 / n); },
            },
            y: {
              type: 'number', easing: 'linear',
              duration(ctx) { const n = Math.max((ctx.chart.data.labels ?? []).length, 1); return 500 / n; },
              from(ctx) { const prev = ctx.chart.getDatasetMeta(ctx.datasetIndex).data[ctx.index - 1]; return prev?.getProps(['y'], true).y; },
              delay(ctx) { if (ctx.type !== 'data' || ctx.yStarted) return 0; ctx.yStarted = true; const n = Math.max((ctx.chart.data.labels ?? []).length, 1); return ctx.index * (500 / n); },
            },
          },
          plugins: {
            legend:  { display: false },
            tooltip: { enabled: false },
          },
          scales: {
            x: { ticks: { color: '#666', font: { size: 11 }, maxTicksLimit: 8 }, grid: { display: false } },
            y: {
              ticks: { color: '#666', font: { size: 11 }, callback: v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%' },
              grid:  { color: 'rgba(255,255,255,.04)' },
            },
          },
        },
      });
      _portChart._dotColor = color;
      _portChart._hoverIdx = null;
      if (_portAnimateNext) {
        _portAnimateNext = false;
        requestAnimationFrame(() => _portChartFade(true));
      }
    }
    _refreshPeriodReturn();
  }

  const _LOGO_PALETTE = ['#c0392b','#8e44ad','#2980b9','#16a085','#d35400','#7f8c8d','#2471a3','#1e8449'];
  function _tickerColor(ticker) {
    let h = 0;
    for (let i = 0; i < ticker.length; i++) h = (h * 31 + ticker.charCodeAt(i)) >>> 0;
    return _LOGO_PALETTE[h % _LOGO_PALETTE.length];
  }
  function _tickerInitials(ticker) {
    return ticker.replace(/[^A-Z]/g, '').slice(0, 2) || ticker.slice(0, 2).toUpperCase();
  }
  const _PARQET_ALIAS = {
    'HSBA.L': 'HSBC',   // HSBC US OTC
    'ULVR.L': 'UL',     // Unilever US ADR
    '7203.T': 'TM',     // Toyota US ADR
    '6758.T': 'SONY',   // Sony US listing
    '9984.T': 'SFTBY',  // SoftBank US OTC
  };
  function _logoUrl(ticker) {
    const sym = _PARQET_ALIAS[ticker] || (/^\d/.test(ticker) ? null : ticker.replace(/\.[A-Z]+$/, ''));
    if (!sym) return null;
    return `https://assets.parqet.com/logos/symbol/${encodeURIComponent(sym)}?format=svg`;
  }
  function _logoHtml(ticker) {
    const color    = _tickerColor(ticker);
    const initials = _tickerInitials(ticker);
    const url      = _logoUrl(ticker);
    const img      = url ? `<img src="${url}" class="hold-logo-img" alt="" onerror="this.remove()">` : '';
    return `<div class="hold-logo" style="background:${color}">${img}<span class="hold-logo-init">${initials}</span></div>`;
  }

  function renderHoldings(holdings, guildId, market) {
    const $el = document.getElementById('port-holdings');
    if (!holdings.length) {
      $el.innerHTML = `<div class="acc-empty">${t('No holdings. Use /stocks buy in Discord to buy stocks.')}</div>`;
      return;
    }
    $el.innerHTML = `<div class="hold-list">
      ${holdings.map(h => {
        const isOpen    = market && market[h.exchange] && market[h.exchange].open;
        const shares    = h.shares % 1 === 0 ? h.shares : Number(h.shares).toFixed(4);
        const dayPct    = h.day_pct ?? 0;
        const daySign   = dayPct >= 0 ? '+' : '';
        const totSign   = h.pnl >= 0 ? '+' : '';
        const dayClass  = dayPct >= 0 ? 'hold-up' : 'hold-dn';
        const totClass  = h.pnl >= 0 ? 'hold-up' : 'hold-dn';
        return `<div class="hold-row" data-ticker="${_esc(h.ticker)}">
          ${_logoHtml(h.ticker)}
          <div class="hold-identity">
            <span class="hold-ticker">${_esc(h.ticker)}</span>
            <span class="hold-name">${_esc(h.name)}</span>
            <span class="hold-shares">${shares} ${t('shares')}</span>
          </div>
          <div class="hold-price-col">
            <span class="hold-price port-cell-price">${_fmtPrice(h.current_price)}</span>
            <span class="hold-day ${dayClass}">${daySign}${dayPct.toFixed(2)}%</span>
          </div>
          <div class="hold-return-col">
            <span class="hold-value port-cell-value">${_fmtYuan(h.value)}</span>
            <span class="hold-total ${totClass}">${totSign}¥${Math.abs(h.pnl).toLocaleString()} (${totSign}${h.pnl_pct.toFixed(2)}%)</span>
          </div>
          <div class="hold-actions">
            <button class="port-btn port-btn-ghost" onclick="_stockChart('${_esc(h.ticker)}','${_esc(h.name)}')">${t('Chart')}</button>
            <button class="port-btn port-btn-buy" ${isOpen ? '' : `disabled title="${t('Market closed')}"`} onclick="_portBuy('${_esc(h.ticker)}','${_esc(h.name)}',${h.current_price},'${_esc(guildId)}')">${t('Buy')}</button>
            <button class="port-btn port-btn-sell" onclick="_portSell('${_esc(h.ticker)}','${_esc(h.name)}',${h.current_price},'${_esc(guildId)}')">${t('Sell')}</button>
          </div>
        </div>`;
      }).join('')}
    </div>`;
  }

  function renderOpenTurbos(positions, guildId, market) {
    const $el = document.getElementById('port-turbos');
    if (!positions.length) {
      $el.innerHTML = `<div class="acc-empty">${t('No open turbo positions.')}</div>`;
      return;
    }
    $el.innerHTML = `<div class="hold-list">
      ${positions.map(p => {
        const isLong   = p.direction === 'LONG';
        const dirClass = isLong ? 'port-long' : 'port-short';
        const dirLabel = `<span class="${dirClass}">${p.direction}</span> ${p.leverage}x`;
        const pnlClass = _pnlClass(p.pnl);
        return `<div class="hold-row">
          ${_logoHtml(p.ticker)}
          <div class="hold-identity">
            <span class="hold-ticker">${_esc(p.ticker)} ${dirLabel}</span>
            <span class="hold-name">${_esc(p.name)}</span>
            <span class="hold-shares">Entry ${_fmtPrice(p.entry_price)} · KO <span class="pnl-neg">${_fmtPrice(p.knockout)}</span></span>
          </div>
          <div class="hold-price-col">
            <span class="hold-price">${_fmtPrice(p.current_price)}</span>
            <span class="hold-day" style="color:var(--text-muted)">${_fmtYuan(p.value)}</span>
          </div>
          <div class="hold-return-col">
            <span class="hold-value ${pnlClass}">${_pnlFmt(p.pnl)}</span>
          </div>
          <div class="hold-actions">
            <button class="port-btn port-btn-ghost" onclick="_portTurboChart('${_esc(p.ticker)}','${_esc(p.name)}','${_esc(p.direction)}',${p.leverage},${p.entry_price},${p.knockout})">${t('Chart')}</button>
            <button class="port-btn port-btn-sell" onclick="_portCloseT(${p.position_id},'${_esc(guildId)}')">${t('Close')}</button>
          </div>
        </div>`;
      }).join('')}
    </div>`;
  }

  function renderTurbosGrouped(turbos, guildId, market) {
    const $el = document.getElementById('port-turbos-avail');
    if (!turbos.length) {
      $el.innerHTML = `<div class="acc-empty">${t('No turbo certificates generated yet today.')}</div>`;
      return;
    }

    const byTicker = {};
    const order    = [];
    for (const turbo of turbos) {
      if (!byTicker[turbo.ticker]) { byTicker[turbo.ticker] = []; order.push(turbo.ticker); }
      byTicker[turbo.ticker].push(turbo);
    }

    $el.innerHTML = order.map(ticker => {
      const group  = byTicker[ticker];
      const sample = group[0];
      const ex     = sample.exchange;
      const open   = market && market[ex] && market[ex].open;
      const badge  = `<span class="${open ? 'port-mkt-open' : 'port-mkt-closed'}">${open ? t('OPEN') : t('CLOSED')}</span>`;
      return `
        <div class="port-exchange-hdr">
          ${_esc(ticker)}
          <span style="font-weight:400;text-transform:none;letter-spacing:0">${_esc(sample.name)}</span>
          ${badge}
          <span class="ms-auto" style="font-size:.83rem;font-weight:600;color:var(--cream);text-transform:none;letter-spacing:0">${_fmtPrice(sample.current_price)}</span>
        </div>
        <div class="hold-list">
          ${group.map(turbo => {
            const isLong      = turbo.direction === 'LONG';
            const dirClass    = isLong ? 'port-long' : 'port-short';
            const buyDisabled = open ? '' : `disabled title="${t('Market closed')}"`;
            return `<div class="hold-row">
              ${_logoHtml(turbo.ticker)}
              <div class="hold-identity">
                <span class="hold-ticker"><span class="${dirClass}">${turbo.direction}</span> ${turbo.leverage}x</span>
                <span class="hold-name">${_esc(turbo.name)}</span>
                <span class="hold-shares">${t('Entry')} ${_fmtPrice(turbo.entry_price)} · KO <span class="pnl-neg">${_fmtPrice(turbo.knockout)}</span></span>
              </div>
              <div class="hold-price-col">
                <span class="hold-price">${_fmtPrice(turbo.current_price)}</span>
                <span class="hold-day" style="color:var(--text-muted)">#${turbo.id}</span>
              </div>
              <div class="hold-actions">
                <button class="port-btn port-btn-ghost" onclick="_portTurboChart('${_esc(turbo.ticker)}','${_esc(turbo.name)}','${_esc(turbo.direction)}',${turbo.leverage},${turbo.entry_price},${turbo.knockout})">${t('Chart')}</button>
                <button class="port-btn port-btn-buy" ${buyDisabled} onclick="_portOpenT(${turbo.id},'${_esc(turbo.ticker)}','${_esc(turbo.name)}',${turbo.leverage},'${_esc(guildId)}')">${t('Open')}</button>
              </div>
            </div>`;
          }).join('')}
        </div>`;
    }).join('');
  }

  // ── Trade modal ───────────────────────────────────────────────────────────

  function _openTradeModal(mode, ticker, name, price, guildId) {
    _tradeMode   = mode;
    _tradeTicker = ticker;
    _tradePrice  = price;
    _tradeGuild  = guildId;

    document.getElementById('trade-modal-title').textContent = t(mode === 'buy' ? 'Buy' : 'Sell') + ' ' + ticker;
    document.getElementById('trade-modal-info').innerHTML =
      `<strong>${_esc(name)}</strong> · ${t('Current price:')} <strong>${_fmtPrice(price)}</strong>`;
    document.getElementById('trade-shares').value = '';
    document.getElementById('trade-cost-preview').textContent = '';
    document.getElementById('trade-modal-err').style.display  = 'none';
    document.getElementById('trade-confirm-btn').textContent  = t(mode === 'buy' ? 'Buy' : 'Sell');
    document.getElementById('trade-confirm-btn').className    =
      'port-btn ' + (mode === 'buy' ? 'port-btn-action' : 'port-btn-sell');
    document.getElementById('trade-confirm-btn').disabled = false;

    document.getElementById('trade-shares').oninput = () => {
      const s = parseFloat(document.getElementById('trade-shares').value) || 0;
      document.getElementById('trade-cost-preview').textContent =
        s > 0 ? t(mode === 'buy' ? 'Cost:' : 'Proceeds:') + ' ' + _fmtYuan(Math.round(s * price)) : '';
    };

    document.getElementById('trade-confirm-btn').onclick = _submitTrade;

    if (!_tradeModal) _tradeModal = new bootstrap.Modal(document.getElementById('tradeModal'));
    _tradeModal.show();
  }

  async function _submitTrade() {
    const shares = parseFloat(document.getElementById('trade-shares').value);
    if (!shares || shares <= 0) { _showTradeErr(t('Enter a valid share amount.')); return; }
    document.getElementById('trade-modal-err').style.display  = 'none';
    document.getElementById('trade-confirm-btn').disabled = true;

    const url = _tradeMode === 'buy' ? '/api/account/portfolio/buy' : '/api/account/portfolio/sell';
    const r   = await fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ guild_id: _tradeGuild, ticker: _tradeTicker, shares }),
    });
    const result = await r.json();
    document.getElementById('trade-confirm-btn').disabled = false;

    if (!r.ok) { _showTradeErr(result.error || t('Trade failed.')); return; }

    bootstrap.Modal.getInstance(document.getElementById('tradeModal')).hide();
    _setWealth(result.new_yuan, _portLastData?.holdings, _portLastData?.turbos, _portLastData?.market);
    loadPortfolio(_portGuildId);
  }

  function _showTradeErr(msg) {
    const el = document.getElementById('trade-modal-err');
    el.textContent   = msg;
    el.style.display = '';
  }

  // ── Turbo open modal ──────────────────────────────────────────────────────

  function _openTurboModal(turboId, ticker, name, leverage, guildId) {
    _turboOpenId = turboId;
    _turboGuild  = guildId;

    document.getElementById('turbo-modal-title').textContent = `Open ${ticker} Turbo`;
    document.getElementById('turbo-modal-info').innerHTML =
      `<strong>${_esc(name)}</strong> · <strong>${leverage}x leverage</strong>`;
    document.getElementById('turbo-cost').value = '';
    document.getElementById('turbo-modal-err').style.display = 'none';
    document.getElementById('turbo-confirm-btn').disabled    = false;
    document.getElementById('turbo-confirm-btn').onclick     = _submitTurboOpen;

    if (!_turboModal) _turboModal = new bootstrap.Modal(document.getElementById('turboModal'));
    _turboModal.show();
  }

  async function _submitTurboOpen() {
    const cost = parseInt(document.getElementById('turbo-cost').value);
    if (!cost || cost < 100) { _showTurboErr(t('Minimum ¥100.')); return; }
    document.getElementById('turbo-modal-err').style.display = 'none';
    document.getElementById('turbo-confirm-btn').disabled    = true;

    const r = await fetch('/api/account/portfolio/turbo/open', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ guild_id: _turboGuild, turbo_id: _turboOpenId, cost }),
    });
    const result = await r.json();
    document.getElementById('turbo-confirm-btn').disabled = false;

    if (!r.ok) { _showTurboErr(result.error || t('Failed to open position.')); return; }

    bootstrap.Modal.getInstance(document.getElementById('turboModal')).hide();
    _setWealth(result.new_yuan, _portLastData?.holdings, _portLastData?.turbos, _portLastData?.market);
    loadPortfolio(_portGuildId);
  }

  function _showTurboErr(msg) {
    const el = document.getElementById('turbo-modal-err');
    el.textContent   = msg;
    el.style.display = '';
  }

  // ── Turbo close ───────────────────────────────────────────────────────────

  async function _closeTurboPosition(positionId, guildId) {
    if (!confirm(t('Close this turbo position? Proceeds will be credited to your yuan balance.'))) return;

    const r = await fetch('/api/account/portfolio/turbo/close', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ guild_id: guildId, position_id: positionId }),
    });
    const result = await r.json();
    if (!r.ok) { alert(result.error || t('Failed to close position.')); return; }

    _setWealth(result.new_yuan, _portLastData?.holdings, _portLastData?.turbos, _portLastData?.market);
    loadPortfolio(_portGuildId);
  }

  // ── All stocks (market browser) ──────────────────────────────────────────

  const _EXCHANGE_ORDER = ['NYSE', 'LSE', 'TSE', 'BSE', 'Penny'];
  const _EXCHANGE_LABELS = { NYSE: 'NYSE · New York', LSE: 'LSE · London', TSE: 'TSE · Tokyo', BSE: 'BSE · Beijing ETF', Penny: 'BSE · Penny Stocks' };

  function renderAllStocks(tickers, guildId, market) {
    const $el = document.getElementById('port-market');
    if (!tickers.length) { $el.innerHTML = `<div class="acc-empty">${t('No market data available.')}</div>`; return; }

    const byGroup = {};
    for (const ticker of tickers) {
      const g = ticker.exchange_label;
      if (!byGroup[g]) byGroup[g] = [];
      byGroup[g].push(ticker);
    }

    function _mktTiming(ex) {
      if (!market || !market[ex]) return '';
      const { open, next_event, next_ts } = market[ex];
      if (!next_ts) return '';
      const d    = new Date(next_ts * 1000);
      const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const date = d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
      const now  = Date.now() / 1000;
      const diff = next_ts - now;
      let rel;
      if (diff < 60)          rel = 'in <1 min';
      else if (diff < 3600)   rel = `in ${Math.round(diff / 60)}m`;
      else if (diff < 86400)  rel = `in ${Math.floor(diff / 3600)}h ${Math.round((diff % 3600) / 60)}m`;
      else                    rel = `in ${Math.floor(diff / 86400)}d`;
      const label = open ? t('Closes') : t('Opens');
      return `<span class="port-mkt-time">${label} ${time} · ${date} (${rel})</span>`;
    }

    const html = _EXCHANGE_ORDER.filter(g => byGroup[g]).map(group => {
      const rows = byGroup[group];
      const ex   = rows[0].exchange;
      const open = market && market[ex] && market[ex].open;
      const badge = `<span class="${open ? 'port-mkt-open' : 'port-mkt-closed'}">${open ? t('OPEN') : t('CLOSED')}</span>`;
      return `
        <div class="port-exchange-hdr">${_EXCHANGE_LABELS[group] || group} ${badge} ${_mktTiming(ex)}</div>
        <div class="hold-list">
          ${rows.map(row => {
            const dayPct    = row.day_pct ?? 0;
            const daySign   = dayPct >= 0 ? '+' : '';
            const dayClass  = dayPct >= 0 ? 'hold-up' : 'hold-dn';
            const ownedShares = row.owned_shares > 0
              ? (row.owned_shares % 1 === 0 ? row.owned_shares : Number(row.owned_shares).toFixed(4)) + ' ' + t('shares')
              : '';
            const buyDisabled = open ? '' : `disabled title="${t('Market closed')}"`;
            return `<div class="hold-row" data-ticker="${_esc(row.ticker)}">
              ${_logoHtml(row.ticker)}
              <div class="hold-identity">
                <span class="hold-ticker">${_esc(row.ticker)}</span>
                <span class="hold-name">${_esc(row.name)}</span>
                ${ownedShares ? `<span class="hold-shares">${ownedShares}</span>` : ''}
              </div>
              <div class="hold-price-col">
                <span class="hold-price port-cell-price">${_fmtPrice(row.current_price)}</span>
                <span class="hold-day ${dayClass}">${daySign}${dayPct.toFixed(2)}%</span>
              </div>
              <div class="hold-actions">
                <button class="port-btn port-btn-ghost" onclick="_stockChart('${_esc(row.ticker)}','${_esc(row.name)}')">${t('Chart')}</button>
                <button class="port-btn port-btn-buy" ${buyDisabled} onclick="_portBuy('${_esc(row.ticker)}','${_esc(row.name)}',${row.current_price},'${_esc(guildId)}')">${t('Buy')}</button>
              </div>
            </div>`;
          }).join('')}
        </div>`;
    }).join('');

    $el.innerHTML = html;
  }

  // ── Turbo chart modal ────────────────────────────────────────────────────

  let _turboChart       = null;
  let _turboChartModal  = null;
  let _turboChartTicker = null;
  let _turboChartEntry  = null;
  let _turboChartKO     = null;
  let _turboChartPeriod = '1D';

  async function _openTurboChartModal(ticker, name, direction, leverage, entry, knockout) {
    _turboChartTicker = ticker;
    _turboChartEntry  = entry  != null ? entry  : null;
    _turboChartKO     = knockout != null ? knockout : null;
    _turboChartPeriod = '1D';

    const isTurbo = direction != null && leverage != null;
    document.getElementById('turbo-chart-logo').innerHTML = _logoHtml(ticker);
    document.getElementById('turbo-chart-title').textContent = isTurbo
      ? `${direction === 'LONG' ? '▲' : '▼'} ${leverage}x ${ticker} · ${name}`
      : `${ticker} · ${name}`;
    document.getElementById('turbo-chart-meta').innerHTML = isTurbo
      ? `Entry <strong>${_fmtPrice(entry)}</strong> · KO <span class="pnl-neg">${_fmtPrice(knockout)}</span>`
      : '';
    document.getElementById('turbo-chart-empty').style.display = 'none';

    document.querySelectorAll('#turbo-chart-periods .port-period').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.period === '1D');
    });

    if (!_turboChartModal) {
      _turboChartModal = new bootstrap.Modal(document.getElementById('turboChartModal'));
      document.querySelectorAll('#turbo-chart-periods .port-period').forEach(btn => {
        btn.addEventListener('click', () => {
          document.querySelectorAll('#turbo-chart-periods .port-period').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          _turboChartPeriod = btn.dataset.period;
          _loadTurboChart(_turboChartTicker, _turboChartPeriod, _turboChartEntry, _turboChartKO);
        });
      });
    }

    _turboChartModal.show();
    await _loadTurboChart(ticker, '1D', entry, knockout);
  }

  async function _loadTurboChart(ticker, period, entry, knockout) {
    const r = await fetch(`/api/account/stock/chart?ticker=${encodeURIComponent(ticker)}&period=${period}`, { credentials: 'same-origin' });
    if (!r.ok) return;
    const data = await r.json();

    const empty = document.getElementById('turbo-chart-empty');
    if (!data.points || !data.points.length) {
      empty.style.display = '';
      if (_turboChart) { _turboChart.data.labels = []; _turboChart.data.datasets.forEach(ds => ds.data = []); _turboChart.update(); }
      return;
    }
    empty.style.display = 'none';

    const _shortP = new Set(['5M', '1H', '6H', '1D', '5D']);

    // merge live buffer into DB points for short-period pre-population
    const nowTsT    = Date.now() / 1000;
    const cutoffT   = nowTsT - (_PERIOD_SECS[period] || 86400);
    const lastDbTsT = data.points.length ? data.points[data.points.length - 1].ts : cutoffT;
    const liveBuf   = (_tickerLiveBuffer[ticker] || []).filter(p => p.ts > lastDbTsT && p.ts >= cutoffT);
    const allPts    = [...data.points, ...liveBuf.map(p => ({ ts: p.ts, close: p.price }))];

    const labels    = allPts.map(p => {
      const d = new Date(p.ts * 1000);
      return _shortP.has(period)
        ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    });
    const prices    = allPts.map(p => p.close);
    const entryLine = entry    != null ? allPts.map(() => entry)    : null;
    const koLine    = knockout != null ? allPts.map(() => knockout) : null;

    const color = _trendColor(prices, data.day_open);

    const datasets = [
      {
        label:       'Price',
        data:        prices,
        borderColor: color,
        borderWidth: 2,
        pointRadius: 0,
        fill:        false,
        tension:     0.35,
        order:       1,
      },
    ];
    if (data.day_open != null) datasets.push({
      label:       'Day Open',
      data:        data.points.map(() => data.day_open),
      borderColor: 'rgba(255,255,255,.18)',
      borderWidth: 1,
      borderDash:  [4, 4],
      pointRadius: 0,
      fill:        false,
      tension:     0,
      order:       2,
    });
    if (entryLine) datasets.push({
      label:       'Entry',
      data:        entryLine,
      borderColor: 'rgba(255,255,255,.4)',
      borderWidth: 1,
      borderDash:  [4, 4],
      pointRadius: 0,
      fill:        false,
      tension:     0,
      order:       2,
    });
    if (koLine) datasets.push({
      label:       'Knockout',
      data:        koLine,
      borderColor: 'rgba(239,83,80,.65)',
      borderWidth: 1,
      borderDash:  [4, 4],
      pointRadius: 0,
      fill:        false,
      tension:     0,
      order:       2,
    });

    if (_turboChart) {
      _turboChart.data.labels   = labels;
      _turboChart.data.datasets = datasets;
      _turboChart._dotColor     = color;
      _turboChart._hoverIdx     = null;
      _turboChart.update('none');
    } else {
      const canvas = document.getElementById('turbo-chart-canvas');
      canvas.style.cursor = 'crosshair';
      canvas.addEventListener('mousemove', e => {
        if (!_turboChart) return;
        const rect = canvas.getBoundingClientRect();
        const xPos = e.clientX - rect.left;
        const meta = _turboChart.getDatasetMeta(0);
        if (!meta.data.length) return;
        let nearIdx = 0, minDist = Infinity;
        for (let i = 0; i < meta.data.length; i++) {
          const { x } = meta.data[i].getProps(['x'], true);
          const d = Math.abs(x - xPos);
          if (d < minDist) { minDist = d; nearIdx = i; }
        }
        _turboChart._hoverIdx = nearIdx;
        _turboChart.update('none');
        const price = _turboChart.data.datasets[0].data[nearIdx];
        const lbl   = _turboChart.data.labels[nearIdx];
        const $meta = document.getElementById('turbo-chart-meta');
        if ($meta && price != null) $meta.textContent = lbl + ' · ' + _fmtPrice(price);
      });
      canvas.addEventListener('mouseleave', () => {
        if (!_turboChart) return;
        _turboChart._hoverIdx = null;
        _turboChart.update('none');
        document.getElementById('turbo-chart-meta').textContent = '';
      });

      const ctx = canvas.getContext('2d');
      _turboChart = new Chart(ctx, {
        type:    'line',
        plugins: [_chartCrosshairPlugin],
        data:    { labels, datasets },
        options: {
          responsive:          true,
          maintainAspectRatio: false,
          animation: {
            x: {
              type: 'number', easing: 'linear',
              duration(ctx) { const n = Math.max((ctx.chart.data.labels ?? []).length, 1); return 500 / n; },
              from: NaN,
              delay(ctx) { if (ctx.type !== 'data' || ctx.xStarted) return 0; ctx.xStarted = true; const n = Math.max((ctx.chart.data.labels ?? []).length, 1); return ctx.index * (500 / n); },
            },
            y: {
              type: 'number', easing: 'linear',
              duration(ctx) { const n = Math.max((ctx.chart.data.labels ?? []).length, 1); return 500 / n; },
              from(ctx) { const prev = ctx.chart.getDatasetMeta(ctx.datasetIndex).data[ctx.index - 1]; return prev?.getProps(['y'], true).y; },
              delay(ctx) { if (ctx.type !== 'data' || ctx.yStarted) return 0; ctx.yStarted = true; const n = Math.max((ctx.chart.data.labels ?? []).length, 1); return ctx.index * (500 / n); },
            },
          },
          plugins: {
            legend:  { display: false },
            tooltip: { enabled: false },
          },
          scales: {
            x: { ticks: { color: '#666', font: { size: 10 }, maxTicksLimit: 8 }, grid: { display: false } },
            y: { ticks: { color: '#666', font: { size: 10 }, callback: v => _fmtPrice(v) }, grid: { color: 'rgba(255,255,255,.04)' } },
          },
        },
      });
      _turboChart._dotColor = color;
      _turboChart._hoverIdx = null;
    }
  }

  // Expose for inline onclick handlers
  window._portBuy        = (t, n, p, g) => _openTradeModal('buy',  t, n, p, g);
  window._portSell       = (t, n, p, g) => _openTradeModal('sell', t, n, p, g);
  window._portOpenT      = (id, t, n, l, g) => _openTurboModal(id, t, n, l, g);
  window._portCloseT     = (id, g) => _closeTurboPosition(id, g);
  window._portTurboChart = (t, n, d, l, e, k) => _openTurboChartModal(t, n, d, l, e, k);
  window._stockChart     = (t, n) => _openTurboChartModal(t, n, null, null, null, null);

  // ── Init ──────────────────────────────────────────────────────────────────

  async function init() {
    const r = await fetch('/api/account', { credentials: 'same-origin' }).catch(() => null);

    if (!r) { showContentError(t('Network error — please refresh.')); return; }
    if (r.status === 401) { window.location.href = '/social-credit/auth/discord?next=/social-credit/account'; return; }
    if (!r.ok) { showContentError(t('Failed to load account data — please refresh.')); return; }

    const d = await r.json();
    _accountData = d;
    renderIdentity(d.discord);
    renderCounters(d.counters || {});
    renderGuilds(d.guilds || []);
    renderRequests(d.requests || []);
    renderAchievements(d.achievements || []);
    renderBadges(d.badges || [], d.badge_preference);
    initPortfolio(d.guilds || []);
  }

  init();

  document.addEventListener('i18n:changed', () => {
    if (!_accountData) return;
    renderGuilds(_accountData.guilds || []);
    renderRequests(_accountData.requests || []);
    renderAchievements(_accountData.achievements || []);
    renderBadges(_accountData.badges || [], _accountData.badge_preference);
    if (_portGuildId && _portLastData) {
      renderHoldings(_portLastData.holdings, _portGuildId, _portLastData.market);
      renderOpenTurbos(_portLastData.turbos, _portGuildId, _portLastData.market);
      renderAllStocks(_portLastData.all_tickers || [], _portGuildId, _portLastData.market);
      if (_portTurbAvail) renderTurbosGrouped(_portTurbAvail.turbos, _portGuildId, _portLastData.market);
    }
  });

  document.addEventListener('click', async (e) => {
    const link = e.target.closest('a.acc-logout-btn');
    if (!link) return;
    e.preventDefault();
    await fetch('/social-credit/auth/discord/logout', { method: 'POST', credentials: 'same-origin' });
    showLoggedOut();
  });
})();

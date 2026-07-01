/* account.js v2 */
(function () {
  'use strict';

  function _esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _timeAgo(ts) {
    if (!ts) return '';
    const diff = Math.floor(Date.now() / 1000) - ts;
    if (diff < 60)    return 'just now';
    if (diff < 3600)  return Math.floor(diff/60) + 'm ago';
    if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
    const d = Math.floor(diff / 86400);
    return d === 1 ? '1 day ago' : d + ' days ago';
  }

  function _hex(n) {
    return '#' + ('000000' + (n >>> 0).toString(16)).slice(-6);
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
      $el.innerHTML = `<div class="acc-empty">No servers found.</div>`;
      return;
    }
    $el.innerHTML = `<table class="acc-guild-table">
      <thead><tr>
        <th>Server</th><th>Score</th><th>¥ Yuan</th><th>Rank</th>
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
      $el.innerHTML = `<div class="acc-empty">No submissions yet. <a href="/social-credit/submit" style="color:var(--sage)">Suggest a character!</a></div>`;
      return;
    }
    $el.innerHTML = requests.map(r => {
      const pill     = `<span class="acc-status-pill acc-status-${_esc(r.status)}">${_esc(r.status)}</span>`;
      const wikiLink = `<a href="https://en.wikipedia.org/wiki/${encodeURIComponent(r.wiki_slug)}" target="_blank" rel="noopener" style="font-size:.72rem;color:var(--sage);text-decoration:none">Wikipedia ↗</a>`;
      const votes    = `<div class="acc-vote-badge">${r.vote_count} vote${r.vote_count === 1 ? '' : 's'}</div>`;
      const withdraw = r.status === 'pending'
        ? `<button class="acc-withdraw-btn" onclick="_withdrawRequest(${r.id}, this)">Withdraw</button>`
        : '';
      return `<div class="acc-req-row" id="req-row-${r.id}">
        <div class="acc-req-meta">
          <div class="acc-req-title">${_esc(r.wiki_title)}</div>
          <div class="acc-req-sub">submitted ${_timeAgo(r.submitted_at)}</div>
        </div>
        <div style="display:flex;align-items:center;gap:.6rem;flex-shrink:0;flex-wrap:wrap">
          ${votes}${pill}${withdraw}${wikiLink}
        </div>
      </div>`;
    }).join('');
  }

  window._withdrawRequest = async function(requestId, btn) {
    if (!confirm('Withdraw this character suggestion? This cannot be undone.')) return;
    btn.disabled   = true;
    btn.textContent = 'Withdrawing…';

    const r = await fetch('/api/requests/delete', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId }),
    });
    const result = await r.json();

    if (!r.ok) {
      btn.disabled    = false;
      btn.textContent = 'Withdraw';
      alert(result.error || 'Failed to withdraw.');
      return;
    }

    const row = document.getElementById('req-row-' + requestId);
    if (row) row.remove();

    const $el = document.getElementById('acc-requests');
    if ($el && !$el.querySelector('.acc-req-row')) {
      $el.innerHTML = `<div class="acc-empty">No submissions yet. <a href="/social-credit/submit" style="color:var(--sage)">Suggest a character!</a></div>`;
    }
  };

  function renderAchievements(achievements) {
    const $el  = document.getElementById('acc-achievements');
    const $cnt = document.getElementById('acc-ach-count');
    $cnt.textContent = achievements.length + ' unlocked';
    if (!achievements.length) {
      $el.innerHTML = `<div class="acc-empty">No achievements unlocked yet.</div>`;
      return;
    }
    $el.innerHTML = achievements.map(a => {
      const tierClass = 'tier-' + (a.tier || 'silent');
      const date      = a.unlocked_at ? _timeAgo(a.unlocked_at) : '';
      return `<div class="acc-ach-card ${tierClass}">
        <div class="acc-ach-name">${_esc(a.name)}</div>
        <div class="acc-ach-desc">${_esc(a.description)}</div>
        ${date ? `<div class="acc-ach-date">Unlocked ${date}</div>` : ''}
      </div>`;
    }).join('');
  }

  function renderBadges(badges, badgePref) {
    const $el = document.getElementById('acc-badges');
    if (!badges.length) {
      $el.innerHTML = `<div class="acc-empty">No cosmetic badges yet.</div>`;
      return;
    }
    $el.innerHTML = badges.map(b => {
      const color    = _hex(b.color || 0x7D9D9C);
      const isActive = b.id === badgePref;
      return `<div class="acc-badge-card">
        ${isActive ? `<span class="acc-badge-active">ACTIVE</span>` : ''}
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

  // ── Portfolio ─────────────────────────────────────────────────────────────

  let _portGuildId = null;
  let _portChart   = null;
  let _portPeriod  = '1D';
  let _tradeMode   = null;
  let _tradeTicker = null;
  let _tradePrice  = 0;
  let _tradeGuild  = null;
  let _turboOpenId = null;
  let _turboGuild  = null;
  let _tradeModal  = null;
  let _turboModal  = null;

  function _marketBadge(exchange, market) {
    if (!market || !market[exchange]) return '';
    const open  = market[exchange].open;
    return `<span class="${open ? 'port-mkt-open' : 'port-mkt-closed'}">${open ? 'OPEN' : 'CLOSED'}</span>`;
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
      if (!gid) {
        document.getElementById('port-content').style.display    = 'none';
        document.getElementById('port-no-server').style.display  = '';
        return;
      }
      _portGuildId = gid;
      document.getElementById('port-content').style.display   = '';
      document.getElementById('port-no-server').style.display = 'none';
      loadPortfolio(gid);
    });

    document.querySelectorAll('.port-period').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.port-period').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        _portPeriod = btn.dataset.period;
        if (_portGuildId) loadPortfolioHistory(_portGuildId, _portPeriod);
      });
    });

    document.getElementById('port-no-server').style.display = guilds.length ? '' : 'none';
    if (!guilds.length) {
      document.getElementById('port-content').innerHTML = '<div class="acc-empty">You have no servers with this bot.</div>';
    }
  }

  async function loadPortfolio(guildId) {
    document.getElementById('port-holdings').innerHTML     = '<div class="acc-empty">Loading…</div>';
    document.getElementById('port-turbos').innerHTML       = '<div class="acc-empty">Loading…</div>';
    document.getElementById('port-market').innerHTML       = '<div class="acc-empty">Loading…</div>';
    document.getElementById('port-turbos-avail').innerHTML = '<div class="acc-empty">Loading…</div>';

    const [portRes, turbAvailRes] = await Promise.all([
      fetch(`/api/account/portfolio?guild_id=${guildId}`, { credentials: 'same-origin' }),
      fetch(`/api/account/portfolio/turbos/available?guild_id=${guildId}`, { credentials: 'same-origin' }),
    ]);

    if (!portRes.ok) {
      const err = await portRes.json().catch(() => ({}));
      document.getElementById('port-holdings').innerHTML = `<div class="acc-empty">${_esc(err.error || 'Failed to load portfolio.')}</div>`;
      return;
    }

    const data      = await portRes.json();
    const turbAvail = turbAvailRes.ok ? await turbAvailRes.json() : { turbos: [], min_cost: 100 };

    document.getElementById('port-yuan').textContent = _fmtYuan(data.yuan);
    renderHoldings(data.holdings, guildId, data.market);
    renderOpenTurbos(data.turbos, guildId, data.market);
    renderAllStocks(data.all_tickers || [], guildId, data.market);
    renderTurbosAvail(turbAvail.turbos, guildId, data.market);
    const minCost = turbAvail.min_cost || 100;
    document.getElementById('port-min-cost').textContent = `Min. ¥${Number(minCost).toLocaleString()}`;

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

    const labels = data.points.map(p => {
      const d = new Date(p.ts * 1000);
      return (period === '1D' || period === '5D')
        ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    });
    const values = data.points.map(p => p.value);

    if (_portChart) {
      _portChart.data.labels            = labels;
      _portChart.data.datasets[0].data  = values;
      _portChart.update();
    } else {
      const ctx = document.getElementById('port-chart').getContext('2d');
      _portChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            data:            values,
            borderColor:     '#7D9D9C',
            backgroundColor: 'rgba(125,157,156,.10)',
            borderWidth:     1.5,
            pointRadius:     0,
            fill:            true,
            tension:         0.3,
          }],
        },
        options: {
          responsive:          true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { callbacks: { label: ctx => _fmtYuan(ctx.parsed.y) } },
          },
          scales: {
            x: { ticks: { color: '#888', font: { size: 11 }, maxTicksLimit: 8 }, grid: { color: 'rgba(255,255,255,.04)' } },
            y: { ticks: { color: '#888', font: { size: 11 }, callback: v => _fmtYuan(v) }, grid: { color: 'rgba(255,255,255,.04)' } },
          },
        },
      });
    }
  }

  function renderHoldings(holdings, guildId, market) {
    const $el = document.getElementById('port-holdings');
    if (!holdings.length) {
      $el.innerHTML = '<div class="acc-empty">No holdings. Use <code>/stocks buy</code> in Discord to buy stocks.</div>';
      return;
    }
    $el.innerHTML = `<div class="port-table-wrap"><table class="port-table">
      <thead><tr>
        <th>Ticker</th><th>Shares</th><th>Avg Cost</th><th>Price</th><th>Value</th><th>P&amp;L</th><th></th>
      </tr></thead>
      <tbody>
        ${holdings.map(h => {
          const pnlStr = _pnlFmt(h.pnl) + ' (' + (h.pnl >= 0 ? '+' : '') + h.pnl_pct.toFixed(2) + '%)';
          const shares = h.shares % 1 === 0 ? h.shares : Number(h.shares).toFixed(4);
          return `<tr>
            <td>
              <span class="port-ticker">${_esc(h.ticker)}</span>
              ${_marketBadge(h.exchange, market)}
              <div class="port-ticker-name">${_esc(h.name)}</div>
            </td>
            <td>${shares}</td>
            <td>${_fmtPrice(h.avg_cost)}</td>
            <td>${_fmtPrice(h.current_price)}</td>
            <td>${_fmtYuan(h.value)}</td>
            <td class="${_pnlClass(h.pnl)}">${pnlStr}</td>
            <td class="port-actions">
              <button class="port-btn port-btn-buy" ${(market && market[h.exchange] && market[h.exchange].open) ? '' : 'disabled title="Market closed"'} onclick="_portBuy('${_esc(h.ticker)}','${_esc(h.name)}',${h.current_price},'${_esc(guildId)}')">Buy</button>
              <button class="port-btn port-btn-sell" onclick="_portSell('${_esc(h.ticker)}','${_esc(h.name)}',${h.current_price},'${_esc(guildId)}')">Sell</button>
            </td>
          </tr>`;
        }).join('')}
      </tbody>
    </table></div>`;
  }

  function renderOpenTurbos(positions, guildId, market) {
    const $el = document.getElementById('port-turbos');
    if (!positions.length) {
      $el.innerHTML = '<div class="acc-empty">No open turbo positions.</div>';
      return;
    }
    $el.innerHTML = `<div class="port-table-wrap"><table class="port-table">
      <thead><tr>
        <th>Ticker</th><th>Dir</th><th>Lev</th><th>Entry</th><th>Knockout</th><th>Current</th><th>Value</th><th>P&amp;L</th><th></th>
      </tr></thead>
      <tbody>
        ${positions.map(p => `<tr>
          <td>
            <span class="port-ticker">${_esc(p.ticker)}</span>
            <div class="port-ticker-name">${_esc(p.name)}</div>
          </td>
          <td><span class="${p.direction === 'LONG' ? 'port-long' : 'port-short'}">${p.direction}</span></td>
          <td>${p.leverage}x</td>
          <td>${_fmtPrice(p.entry_price)}</td>
          <td class="pnl-neg">${_fmtPrice(p.knockout)}</td>
          <td>${_fmtPrice(p.current_price)}</td>
          <td>${_fmtYuan(p.value)}</td>
          <td class="${_pnlClass(p.pnl)}">${_pnlFmt(p.pnl)}</td>
          <td class="port-actions">
            <button class="port-btn port-btn-ghost" onclick="_portTurboChart('${_esc(p.ticker)}','${_esc(p.name)}','${_esc(p.direction)}',${p.leverage},${p.entry_price},${p.knockout})">Chart</button>
            <button class="port-btn port-btn-sell" onclick="_portCloseT(${p.position_id},'${_esc(guildId)}')">Close</button>
          </td>
        </tr>`).join('')}
      </tbody>
    </table></div>`;
  }

  function renderTurbosAvail(turbos, guildId, market) {
    const $el = document.getElementById('port-turbos-avail');
    if (!turbos.length) {
      $el.innerHTML = '<div class="acc-empty">No turbo certificates generated yet today.</div>';
      return;
    }
    $el.innerHTML = `<div class="port-table-wrap"><table class="port-table">
      <thead><tr>
        <th>ID</th><th>Ticker</th><th>Dir</th><th>Lev</th><th>Entry</th><th>Knockout</th><th>Current</th><th></th>
      </tr></thead>
      <tbody>
        ${turbos.map(t => `<tr>
          <td class="port-dimmed">#${t.id}</td>
          <td>
            <span class="port-ticker">${_esc(t.ticker)}</span>
            ${_marketBadge(t.exchange, market)}
            <div class="port-ticker-name">${_esc(t.name)}</div>
          </td>
          <td><span class="${t.direction === 'LONG' ? 'port-long' : 'port-short'}">${t.direction}</span></td>
          <td>${t.leverage}x</td>
          <td>${_fmtPrice(t.entry_price)}</td>
          <td class="pnl-neg">${_fmtPrice(t.knockout)}</td>
          <td>${_fmtPrice(t.current_price)}</td>
          <td class="port-actions">
            <button class="port-btn port-btn-ghost" onclick="_portTurboChart('${_esc(t.ticker)}','${_esc(t.name)}','${_esc(t.direction)}',${t.leverage},${t.entry_price},${t.knockout})">Chart</button>
            <button class="port-btn port-btn-buy" onclick="_portOpenT(${t.id},'${_esc(t.ticker)}','${_esc(t.name)}',${t.leverage},'${_esc(guildId)}')">Open</button>
          </td>
        </tr>`).join('')}
      </tbody>
    </table></div>`;
  }

  // ── Trade modal ───────────────────────────────────────────────────────────

  function _openTradeModal(mode, ticker, name, price, guildId) {
    _tradeMode   = mode;
    _tradeTicker = ticker;
    _tradePrice  = price;
    _tradeGuild  = guildId;

    document.getElementById('trade-modal-title').textContent = (mode === 'buy' ? 'Buy ' : 'Sell ') + ticker;
    document.getElementById('trade-modal-info').innerHTML =
      `<strong>${_esc(name)}</strong> · Current price: <strong>${_fmtPrice(price)}</strong>`;
    document.getElementById('trade-shares').value = '';
    document.getElementById('trade-cost-preview').textContent = '';
    document.getElementById('trade-modal-err').style.display  = 'none';
    document.getElementById('trade-confirm-btn').textContent  = mode === 'buy' ? 'Buy' : 'Sell';
    document.getElementById('trade-confirm-btn').className    =
      'port-btn ' + (mode === 'buy' ? 'port-btn-action' : 'port-btn-sell');
    document.getElementById('trade-confirm-btn').disabled = false;

    document.getElementById('trade-shares').oninput = () => {
      const s = parseFloat(document.getElementById('trade-shares').value) || 0;
      document.getElementById('trade-cost-preview').textContent =
        s > 0 ? (mode === 'buy' ? 'Cost: ' : 'Proceeds: ') + _fmtYuan(Math.round(s * price)) : '';
    };

    document.getElementById('trade-confirm-btn').onclick = _submitTrade;

    if (!_tradeModal) _tradeModal = new bootstrap.Modal(document.getElementById('tradeModal'));
    _tradeModal.show();
  }

  async function _submitTrade() {
    const shares = parseFloat(document.getElementById('trade-shares').value);
    if (!shares || shares <= 0) { _showTradeErr('Enter a valid share amount.'); return; }
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

    if (!r.ok) { _showTradeErr(result.error || 'Trade failed.'); return; }

    bootstrap.Modal.getInstance(document.getElementById('tradeModal')).hide();
    document.getElementById('port-yuan').textContent = _fmtYuan(result.new_yuan);
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
    if (!cost || cost < 100) { _showTurboErr('Minimum ¥100.'); return; }
    document.getElementById('turbo-modal-err').style.display = 'none';
    document.getElementById('turbo-confirm-btn').disabled    = true;

    const r = await fetch('/api/account/portfolio/turbo/open', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ guild_id: _turboGuild, turbo_id: _turboOpenId, cost }),
    });
    const result = await r.json();
    document.getElementById('turbo-confirm-btn').disabled = false;

    if (!r.ok) { _showTurboErr(result.error || 'Failed to open position.'); return; }

    bootstrap.Modal.getInstance(document.getElementById('turboModal')).hide();
    document.getElementById('port-yuan').textContent = _fmtYuan(result.new_yuan);
    loadPortfolio(_portGuildId);
  }

  function _showTurboErr(msg) {
    const el = document.getElementById('turbo-modal-err');
    el.textContent   = msg;
    el.style.display = '';
  }

  // ── Turbo close ───────────────────────────────────────────────────────────

  async function _closeTurboPosition(positionId, guildId) {
    if (!confirm('Close this turbo position? Proceeds will be credited to your yuan balance.')) return;

    const r = await fetch('/api/account/portfolio/turbo/close', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ guild_id: guildId, position_id: positionId }),
    });
    const result = await r.json();
    if (!r.ok) { alert(result.error || 'Failed to close position.'); return; }

    document.getElementById('port-yuan').textContent = _fmtYuan(result.new_yuan);
    loadPortfolio(_portGuildId);
  }

  // ── All stocks (market browser) ──────────────────────────────────────────

  const _EXCHANGE_ORDER = ['NYSE', 'LSE', 'TSE', 'BSE', 'Penny'];
  const _EXCHANGE_LABELS = { NYSE: 'NYSE · New York', LSE: 'LSE · London', TSE: 'TSE · Tokyo', BSE: 'BSE · Beijing ETF', Penny: 'BSE · Penny Stocks' };

  function renderAllStocks(tickers, guildId, market) {
    const $el = document.getElementById('port-market');
    if (!tickers.length) { $el.innerHTML = '<div class="acc-empty">No market data available.</div>'; return; }

    const byGroup = {};
    for (const t of tickers) {
      const g = t.exchange_label;
      if (!byGroup[g]) byGroup[g] = [];
      byGroup[g].push(t);
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
      const label = open ? 'Closes' : 'Opens';
      return `<span class="port-mkt-time">${label} ${time} · ${date} (${rel})</span>`;
    }

    const html = _EXCHANGE_ORDER.filter(g => byGroup[g]).map(group => {
      const rows = byGroup[group];
      const ex   = rows[0].exchange;
      const open = market && market[ex] && market[ex].open;
      const badge = `<span class="${open ? 'port-mkt-open' : 'port-mkt-closed'}">${open ? 'OPEN' : 'CLOSED'}</span>`;
      return `
        <div class="port-exchange-hdr">${_EXCHANGE_LABELS[group] || group} ${badge} ${_mktTiming(ex)}</div>
        <div class="port-table-wrap"><table class="port-table">
          <thead><tr><th>Ticker</th><th>Name</th><th>Price</th><th>Owned</th><th></th></tr></thead>
          <tbody>
            ${rows.map(t => {
              const owned = t.owned_shares > 0
                ? `<span class="port-owned">${t.owned_shares % 1 === 0 ? t.owned_shares : Number(t.owned_shares).toFixed(4)} sh</span>`
                : '<span class="port-dimmed">–</span>';
              const buyDisabled = open ? '' : 'disabled title="Market closed"';
              return `<tr>
                <td><span class="port-ticker">${_esc(t.ticker)}</span></td>
                <td class="port-ticker-name">${_esc(t.name)}</td>
                <td>${_fmtPrice(t.current_price)}</td>
                <td>${owned}</td>
                <td class="port-actions">
                  <button class="port-btn port-btn-ghost" onclick="_stockChart('${_esc(t.ticker)}','${_esc(t.name)}')">Chart</button>
                  <button class="port-btn port-btn-buy" ${buyDisabled} onclick="_portBuy('${_esc(t.ticker)}','${_esc(t.name)}',${t.current_price},'${_esc(guildId)}')">Buy</button>
                </td>
              </tr>`;
            }).join('')}
          </tbody>
        </table></div>`;
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

    const labels    = data.points.map(p => {
      const d = new Date(p.ts * 1000);
      return (period === '1D' || period === '5D')
        ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    });
    const prices    = data.points.map(p => p.close);
    const entryLine = entry    != null ? data.points.map(() => entry)    : null;
    const koLine    = knockout != null ? data.points.map(() => knockout) : null;

    const datasets = [
      {
        label:           'Price',
        data:            prices,
        borderColor:     '#7D9D9C',
        backgroundColor: 'rgba(125,157,156,.10)',
        borderWidth:     1.5,
        pointRadius:     0,
        fill:            true,
        tension:         0.3,
        order:           1,
      },
    ];
    if (entryLine) datasets.push({
      label:       'Entry',
      data:        entryLine,
      borderColor: 'rgba(255,255,255,0.45)',
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
      borderColor: 'rgba(239,83,80,0.7)',
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
      _turboChart.update();
    } else {
      const ctx = document.getElementById('turbo-chart-canvas').getContext('2d');
      _turboChart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: {
          responsive:          true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              display: true,
              labels:  { color: '#aaa', font: { size: 11 }, boxWidth: 20 },
            },
            tooltip: { callbacks: { label: ctx => ctx.dataset.label + ': ' + _fmtPrice(ctx.parsed.y) } },
          },
          scales: {
            x: { ticks: { color: '#888', font: { size: 10 }, maxTicksLimit: 8 }, grid: { color: 'rgba(255,255,255,.04)' } },
            y: { ticks: { color: '#888', font: { size: 10 }, callback: v => _fmtPrice(v) }, grid: { color: 'rgba(255,255,255,.04)' } },
          },
        },
      });
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

    if (!r) { showContentError('Network error — please refresh.'); return; }
    if (r.status === 401) { window.location.href = '/social-credit/auth/discord?next=/social-credit/account'; return; }
    if (!r.ok) { showContentError('Failed to load account data — please refresh.'); return; }

    const d = await r.json();
    renderIdentity(d.discord);
    renderCounters(d.counters || {});
    renderGuilds(d.guilds || []);
    renderRequests(d.requests || []);
    renderAchievements(d.achievements || []);
    renderBadges(d.badges || [], d.badge_preference);
    initPortfolio(d.guilds || []);
  }

  init();
})();

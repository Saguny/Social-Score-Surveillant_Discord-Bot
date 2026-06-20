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

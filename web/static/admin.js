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

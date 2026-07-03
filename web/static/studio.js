(function () {
  var drift = document.getElementById('squares-drift');
  var container = document.getElementById('squares');
  var size = 190;
  var squares = [];

  function build() {
    if (isPrideSequence) return;
    container.innerHTML = '';
    squares = [];

    var isMobile = window.matchMedia('(hover: none) and (pointer: coarse)').matches;
    size = Math.max(isMobile ? 150 : 100, Math.round(Math.min(window.innerWidth, window.innerHeight) * (isMobile ? 0.25 : 0.15)));
    container.style.setProperty('--sq-size', size + 'px');

    var driftRect = drift.getBoundingClientRect();
    var cols = Math.ceil(driftRect.width / size) + 1;
    var rows = Math.ceil(driftRect.height / size) + 1;
    var total = cols * rows;

    for (var i = 0; i < total; i++) {
      var sq = document.createElement('div');
      sq.className = 'square';
      var dur = 6 + Math.random() * 12;
      var delay = Math.random() * 12;

      sq.style.setProperty('--sq-dur', dur.toFixed(2) + 's');
      sq.style.setProperty('--sq-delay', '-' + delay.toFixed(2) + 's');

      container.appendChild(sq);
      squares.push({ el: sq, cx: 0, cy: 0, scale: 1, waves: [], flashes: [] });
    }

    requestAnimationFrame(measure);
  }

  function measure() {
    for (var i = 0; i < squares.length; i++) {
      var r = squares[i].el.getBoundingClientRect();
      squares[i].cx = r.left + r.width / 2;
      squares[i].cy = r.top + r.height / 2;
    }
  }

  var mouseX = -9999;
  var mouseY = -9999;
  var overCard = false;
  var cardEl = document.querySelector('.site');
  cardEl.addEventListener('mouseenter',  function () { overCard = true; });
  cardEl.addEventListener('mouseleave',  function () { overCard = false; });
  cardEl.addEventListener('touchstart',  function () { overCard = true; },  { passive: true });
  cardEl.addEventListener('touchend',    function () { overCard = false; }, { passive: true });
  cardEl.addEventListener('touchcancel', function () { overCard = false; }, { passive: true });
  document.querySelectorAll('.avatar-wrap').forEach(function (wrap) {
    wrap.addEventListener('mousemove', function (e) {
      var rect = wrap.getBoundingClientRect();
      var dx = (e.clientX - (rect.left + rect.width  / 2)) / (rect.width  / 2);
      var dy = (e.clientY - (rect.top  + rect.height / 2)) / (rect.height / 2);
      wrap.style.transform = 'translate(' + (dx * 4).toFixed(1) + 'px, ' + (dy * 4).toFixed(1) + 'px)';
    });
    wrap.addEventListener('mouseleave', function () { wrap.style.transform = ''; });
  });

  var influence = 260;
  var maxScale = 1.4;
  var lerpSpeed = 0.1;
  var waveSpeed = 3;
  var waveDuration = 350;
  var waveMaxScale = 0.1;
  var flashDuration = 600;
  var flashPeakT = 0.2;

  /* ── Pride mode ─────────────────────────────────── */

  var prideColors = ['#FF3B3B', '#FF9F1C', '#FFE81A', '#2ECC40', '#4169FF', '#B44FFF'];
  var PRIDE_TRIGGER = 7;
  var bgClickCount = 0;
  var isPrideSequence = false;
  var lastBgClickX = 0;
  var lastBgClickY = 0;
  var paused = false;
  document.addEventListener('visibilitychange', function () { paused = document.hidden; });

  function startPrideSequence(originX, originY) {
    isPrideSequence = true;

    var now = performance.now();
    var maxDelay = 0;

    squares.forEach(function (s) {
      var dx = s.cx - originX;
      var dy = s.cy - originY;
      var dist = Math.sqrt(dx * dx + dy * dy);
      var delay = dist / waveSpeed;
      if (delay > maxDelay) maxDelay = delay;

      s.waves.push(now + delay);

      var colorIdx = Math.floor(Math.random() * prideColors.length);
      (function (sq, d, ci) {
        setTimeout(function () {
          sq.el.classList.remove('pride-out');
          sq.el.classList.add('pride-in');
          sq.el.style.animation = 'none';
          sq.el.style.backgroundColor = prideColors[ci];
        }, d);
      })(s, delay, colorIdx);
    });

    setTimeout(triggerPrideRipple, maxDelay + waveDuration + 400);
  }

  function triggerPrideRipple() {
    var cx = window.innerWidth / 2;
    var cy = window.innerHeight / 2;
    var now = performance.now();
    var maxDelay = 0;

    for (var i = 0; i < squares.length; i++) {
      var s = squares[i];
      var dx = cx - s.cx;
      var dy = cy - s.cy;
      var dist = Math.sqrt(dx * dx + dy * dy);
      var delay = dist / waveSpeed;
      if (delay > maxDelay) maxDelay = delay;

      s.waves.push(now + dist / waveSpeed);

      (function (sq, d) {
        setTimeout(function () {
          sq.el.classList.remove('pride-in');
          sq.el.classList.add('pride-out');
          sq.el.style.backgroundColor = '';
          setTimeout(function () {
            sq.el.classList.remove('pride-out');
            sq.el.style.animation = '';
          }, 320);
        }, d);
      })(s, delay);
    }

    setTimeout(function () {
      isPrideSequence = false;
      bgClickCount = 0;
    }, maxDelay + waveDuration + 620);
  }

  /* ── Render loop ────────────────────────────────── */

  function lerpLoop() {
    requestAnimationFrame(lerpLoop);
    if (paused) return;
    var now = performance.now();
    for (var i = 0; i < squares.length; i++) {
      var s = squares[i];
      var mx = (overCard || isPrideSequence) ? -9999 : mouseX;
      var my = (overCard || isPrideSequence) ? -9999 : mouseY;
      var dx = mx - s.cx;
      var dy = my - s.cy;
      var dist = Math.sqrt(dx * dx + dy * dy);
      var target = dist < influence ? 1 + (1 - dist / influence) * (maxScale - 1) : 1;
      s.scale += (target - s.scale) * lerpSpeed;

      var totalScale = s.scale;
      var brightness = 1;
      var w = 0;
      while (w < s.waves.length) {
        var t = (now - s.waves[w]) / waveDuration;
        if (t >= 1) {
          s.waves.splice(w, 1);
        } else {
          if (t >= 0) {
            var wave = Math.sin(t * Math.PI);
            totalScale += wave * waveMaxScale;
            brightness += wave * 0.2;
          }
          w++;
        }
      }

      var flashOpacity = 0;
      var f = 0;
      while (f < s.flashes.length) {
        var tf = (now - s.flashes[f]) / flashDuration;
        if (tf >= 1) { s.flashes.splice(f, 1); }
        else {
          if (tf >= 0) {
            var env = tf < flashPeakT
              ? Math.sin((tf / flashPeakT) * Math.PI * 0.5)
              : Math.cos(((tf - flashPeakT) / (1 - flashPeakT)) * Math.PI * 0.5);
            flashOpacity += env;
          }
          f++;
        }
      }
      flashOpacity = Math.min(flashOpacity, 1);

      s.el.style.transform = 'scale(' + totalScale.toFixed(3) + ')';
      s.el.style.filter = brightness > 1 ? 'brightness(' + brightness.toFixed(3) + ')' : '';
      s.el.style.zIndex = Math.round(s.scale * 100);
      if (flashOpacity > 0.001) {
        s.el.style.setProperty('--sq-flash', flashOpacity.toFixed(3));
      } else {
        s.el.style.removeProperty('--sq-flash');
      }
    }
  }

  /* ── Events ─────────────────────────────────────── */

  window.addEventListener('mousemove', function (e) {
    mouseX = e.clientX;
    mouseY = e.clientY;
  });

  window.addEventListener('mouseleave', function () {
    mouseX = -9999;
    mouseY = -9999;
  });

  window.addEventListener('click', function (e) {
    if (overCard) return;
    if (isPrideSequence) return;

    lastBgClickX = e.clientX;
    lastBgClickY = e.clientY;
    bgClickCount++;
    if (bgClickCount >= PRIDE_TRIGGER) {
      bgClickCount = 0;
      startPrideSequence(lastBgClickX, lastBgClickY);
      return;
    }

    var now = performance.now();
    for (var i = 0; i < squares.length; i++) {
      var s = squares[i];
      var dx = e.clientX - s.cx;
      var dy = e.clientY - s.cy;
      var dist = Math.sqrt(dx * dx + dy * dy);
      s.waves.push(now + dist / waveSpeed);
    }
  });

  window.addEventListener('touchstart', function (e) {
    if (isPrideSequence) return;
    var touch = e.touches[0];
    if (overCard) return;

    bgClickCount++;
    if (bgClickCount >= PRIDE_TRIGGER) {
      bgClickCount = 0;
      startPrideSequence(touch.clientX, touch.clientY);
      return;
    }

    var now = performance.now();
    for (var i = 0; i < squares.length; i++) {
      var s = squares[i];
      var dx = touch.clientX - s.cx;
      var dy = touch.clientY - s.cy;
      var dist = Math.sqrt(dx * dx + dy * dy);
      s.waves.push(now + dist / waveSpeed);
    }
  }, { passive: true });

  document.querySelector('.project').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') location.href = '/social-credit';
  });

  var logoClickCount = 0, logoClickTimer;
  document.querySelector('.logo').addEventListener('click', function () {
    logoClickCount++;
    clearTimeout(logoClickTimer);
    logoClickTimer = setTimeout(function () { logoClickCount = 0; }, 2000);
    if (logoClickCount >= 5) {
      logoClickCount = 0;
      var h1El = document.querySelector('h1');
      h1El.classList.add('glitch-burst');
      setTimeout(function () { h1El.classList.remove('glitch-burst'); }, 1000);
    }
  });

  var resizeTimer;
  window.addEventListener('resize', function () {
    if (isPrideSequence) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(build, 200);
  });

  function scheduleFlash() {
    if (!isPrideSequence && !paused && squares.length) {
      squares[Math.floor(Math.random() * squares.length)].flashes.push(performance.now());
    }
    setTimeout(scheduleFlash, 300 + Math.random() * 700);
  }

  build();
  lerpLoop();
  scheduleFlash();
  setInterval(measure, 500);

  fetch('/api/stats')
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d) return;
      var guilds = d.total_guilds;
      var users = d.total_users;
      if (typeof guilds === 'number') document.getElementById('sc-guilds').textContent = guilds.toLocaleString() + ' servers';
      if (typeof users === 'number') document.getElementById('sc-users').textContent = users.toLocaleString() + ' citizens';
    })
    .catch(function () {});
})();

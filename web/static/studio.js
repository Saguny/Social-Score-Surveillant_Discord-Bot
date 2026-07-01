(function () {
  var drift = document.getElementById('squares-drift');
  var container = document.getElementById('squares');
  var size = 190;
  var squares = [];

  function build() {
    container.innerHTML = '';
    squares = [];

    size = Math.max(100, Math.round(Math.min(window.innerWidth, window.innerHeight) * 0.15));
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
      squares.push({ el: sq, cx: 0, cy: 0, scale: 1, waves: [] });
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
  var cardEl = document.querySelector('.card');
  cardEl.addEventListener('mouseenter', function () { overCard = true; });
  cardEl.addEventListener('mouseleave', function () { overCard = false; });
  var influence = 260;
  var maxScale = 1.4;
  var lerpSpeed = 0.1;
  var waveSpeed = 3;
  var waveDuration = 350;
  var waveMaxScale = 0.1;

  function lerpLoop() {
    requestAnimationFrame(lerpLoop);
    var now = performance.now();
    for (var i = 0; i < squares.length; i++) {
      var s = squares[i];
      var mx = overCard ? -9999 : mouseX;
      var my = overCard ? -9999 : mouseY;
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

      s.el.style.transform = 'scale(' + totalScale.toFixed(3) + ')';
      s.el.style.filter = brightness > 1 ? 'brightness(' + brightness.toFixed(3) + ')' : '';
      s.el.style.zIndex = Math.round(s.scale * 100);
    }
  }

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
    var now = performance.now();
    for (var i = 0; i < squares.length; i++) {
      var s = squares[i];
      var dx = e.clientX - s.cx;
      var dy = e.clientY - s.cy;
      var dist = Math.sqrt(dx * dx + dy * dy);
      s.waves.push(now + dist / waveSpeed);
    }
  });

  var hueAccum = 0;
  var scrollTicking = false;
  function applyHue() {
    scrollTicking = false;
    drift.style.filter = 'hue-rotate(' + hueAccum.toFixed(1) + 'deg)';
  }
  window.addEventListener('wheel', function (e) {
    hueAccum = (hueAccum + e.deltaY * 0.06) % 360;
    if (!scrollTicking) {
      scrollTicking = true;
      requestAnimationFrame(applyHue);
    }
  }, { passive: true });

  var resizeTimer;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(build, 200);
  });

  build();
  lerpLoop();
  setInterval(measure, 500);
})();

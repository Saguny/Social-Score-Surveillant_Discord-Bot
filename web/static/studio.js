(function () {
  var INTRO_END = 5.55;
  var INK = '#121212', PAPER = '#f4f4f2', ACID = '#b4ff1f', BLUE = '#2b0bff', MAG = '#ff2bd6', DIM = '#6a6a66';
  var STEP = 15;
  var GLYPHS = 'ABCDEFGHJKLNOPRSVXYZ0123456789';
  var DATA = { servers: null, citizens: null };
  var now = 0, dataAt = null;
  var MAX_DPR = 2, INTRO_PX = 1.2e6, PAGE_FROM = 4.9;
  function cdpr() { return Math.min(window.devicePixelRatio || 1, MAX_DPR); }
  function unit() { return Math.min(ih / 1080, iw / 720); }


  function clamp(v, a, b) { return Math.min(b === undefined ? 1 : b, Math.max(a === undefined ? 0 : a, v)); }
  function seg(t, a, b) { return clamp((t - a) / (b - a)); }
  function lerp(a, b, x) { return a + (b - a) * x; }
  function easeOut(x) { return 1 - Math.pow(1 - x, 3); }
  function easeInOut(x) { return x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; }
  function hash(a, b) {
    var h = Math.imul((a | 0) ^ 0x9e3779b9, 374761393) ^ Math.imul(((b | 0) + 0x632be5ab) | 0, 668265263);
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    h ^= h >>> 16;
    return (h >>> 0) / 4294967296;
  }

  function code(seed, len) {
    var s = '';
    for (var i = 0; i < len; i++) s += GLYPHS[Math.floor(hash(seed, i) * GLYPHS.length)];
    return s;
  }


  document.querySelectorAll('.frame').forEach(function (f) {
    ['tl', 'tr', 'bl', 'br'].forEach(function (k) {
      var x = document.createElement('i');
      x.className = 'x ' + k;
      f.appendChild(x);
    });
  });

  fetch('/api/stats').then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
    if (!d) return;
    if (typeof d.total_guilds === 'number') DATA.servers = d.total_guilds;
    if (typeof d.total_users === 'number') DATA.citizens = d.total_users;
    dataAt = now;
  }).catch(function () {});

  /* ── Intro ─────────────────────────────────────── */

  var ic = document.getElementById('intro');
  var ix = ic.getContext('2d');
  var iw = 0, ih = 0, idpr = 1, introGone = false, introFrame = -1;
  var snap = document.createElement('canvas'), snapX = snap.getContext('2d');
  var exit = null, exitFrame = -1, EXIT_IN = .4, EXIT_OUT = .33;
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var LOGO = [], LOGO_W = 60, LOGO_H = 6;


  function genObject(kind) {
    var c = document.createElement('canvas');
    c.width = c.height = 256;
    var g = c.getContext('2d');
    g.fillStyle = '#000'; g.fillRect(0, 0, 256, 256);
    if (kind === 'orb') {
      g.lineWidth = 16; g.strokeStyle = '#4a4a4a';
      g.beginPath(); g.ellipse(128, 134, 116, 32, -.35, Math.PI, Math.PI * 2); g.stroke();
      var sg = g.createRadialGradient(98, 96, 4, 128, 128, 74);
      sg.addColorStop(0, '#ffffff'); sg.addColorStop(.25, '#c4c4c4'); sg.addColorStop(.65, '#4c4c4c'); sg.addColorStop(1, '#0e0e0e');
      g.fillStyle = sg; g.beginPath(); g.arc(128, 128, 72, 0, Math.PI * 2); g.fill();
      g.strokeStyle = 'rgba(0,0,0,.35)'; g.lineWidth = 2;
      for (var b = 1; b < 5; b++) { g.beginPath(); g.ellipse(128, 128, 72, 72 * b / 5, 0, 0, Math.PI * 2); g.stroke(); }
      var rg = g.createLinearGradient(12, 0, 244, 0);
      rg.addColorStop(0, '#3a3a3a'); rg.addColorStop(.45, '#ffffff'); rg.addColorStop(.7, '#9a9a9a'); rg.addColorStop(1, '#2a2a2a');
      g.strokeStyle = rg; g.lineWidth = 16;
      g.beginPath(); g.ellipse(128, 134, 116, 32, -.35, 0, Math.PI); g.stroke();
    } else {
      var P = { t: [128, 18], b: [128, 238], l: [44, 122], r: [212, 130], f: [112, 156], k: [150, 100] };
      [['t', 'l', 'k', '#2e2e2e'], ['t', 'k', 'r', '#5a5a5a'], ['b', 'k', 'r', '#262626'], ['b', 'l', 'k', '#1c1c1c'],
       ['t', 'l', 'f', '#e4e4e4'], ['t', 'f', 'r', '#a6a6a6'], ['b', 'l', 'f', '#7c7c7c'], ['b', 'f', 'r', '#454545']].forEach(function (F) {
        g.fillStyle = F[3];
        g.beginPath(); g.moveTo(P[F[0]][0], P[F[0]][1]); g.lineTo(P[F[1]][0], P[F[1]][1]); g.lineTo(P[F[2]][0], P[F[2]][1]); g.closePath(); g.fill();
        g.strokeStyle = 'rgba(255,255,255,.35)'; g.lineWidth = 1.5; g.stroke();
      });
    }
    return c;
  }


  function bake(src) {
    var c = document.createElement('canvas');
    c.width = src.width; c.height = src.height;
    var g = c.getContext('2d');
    g.filter = 'grayscale(1) contrast(1.4)';
    g.drawImage(src, 0, 0);
    return c;
  }

  var SUBJECTS = [{ img: bake(genObject('orb')) }, { img: bake(genObject('shard')) }];


  function fitIntro() {
    iw = window.innerWidth; ih = window.innerHeight;
    idpr = Math.min(cdpr(), Math.sqrt(INTRO_PX / (iw * ih)));
    ic.width = Math.round(iw * idpr); ic.height = Math.round(ih * idpr);
    introFrame = -1;
  }

  function itext(s, x, y, size, color, font, align) {
    ix.font = size + 'px ' + (font || '"Space Mono", monospace');
    ix.fillStyle = color;
    ix.textAlign = align || 'left';
    ix.textBaseline = 'alphabetic';
    ix.fillText(s, x, y);
  }

  function buildLogo() {
    var o = document.createElement('canvas');
    o.width = 400; o.height = 40;
    var g = o.getContext('2d');
    g.font = '16px Silkscreen, monospace';
    g.textBaseline = 'top';
    g.fillStyle = '#fff';
    g.fillText('OFF-BY-ONE', 0, 0);
    var d = g.getImageData(0, 0, o.width, o.height).data;
    var maxX = 0, maxY = 0, minY = 99;
    LOGO = [];
    for (var j = 0; j < 20; j++) for (var i = 0; i < 200; i++) {
      if (d[((j * 2 + 1) * o.width + (i * 2 + 1)) * 4 + 3] > 110) {
        LOGO.push({ x: i, y: j });
        maxX = Math.max(maxX, i); maxY = Math.max(maxY, j); minY = Math.min(minY, j);
      }
    }
    LOGO.forEach(function (c) { c.y -= minY; });
    LOGO_W = maxX + 1; LOGO_H = maxY - minY + 1;
  }

  function chromeGrad(x0, y0, x1, y1) {
    var g = ix.createLinearGradient(x0, y0, x1, y1);
    g.addColorStop(0, '#2b2b2e'); g.addColorStop(.35, '#f6f6f6'); g.addColorStop(.55, '#8d8d92');
    g.addColorStop(.75, '#ffffff'); g.addColorStop(1, '#1e1e20');
    return g;
  }

  function chromeShapeBase(kind, x, y, r, rot) {
    if (kind === 0) {
      ix.beginPath();
      for (var k = 0; k < 8; k++) {
        var a = rot + k * Math.PI / 4 - Math.PI / 2, rr = k % 2 ? r * .26 : r;
        ix.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr);
      }
      ix.closePath();
      ix.fillStyle = chromeGrad(x - r, y - r, x + r, y + r);
      ix.fill();
    } else if (kind === 1) {
      var g = ix.createRadialGradient(x - r * .35, y - r * .35, r * .08, x, y, r);
      g.addColorStop(0, '#ffffff'); g.addColorStop(.4, '#b8b8bc'); g.addColorStop(.85, '#3a3a3e'); g.addColorStop(1, '#111');
      ix.fillStyle = g;
      ix.beginPath(); ix.arc(x, y, r * .7, 0, Math.PI * 2); ix.fill();
    } else if (kind === 2) {
      ix.lineWidth = r * .34;
      ix.lineCap = 'butt';
      ix.strokeStyle = chromeGrad(x - r, y, x + r, y);
      ix.beginPath(); ix.arc(x, y, r, rot, rot + Math.PI * 1.1); ix.stroke();
    } else {
      ix.lineWidth = r * .3;
      ix.lineCap = 'square';
      ix.strokeStyle = chromeGrad(x - r, y - r, x + r, y + r);
      ix.beginPath();
      ix.moveTo(x + r * .8, y + r * .8); ix.lineTo(x - r * .5, y - r * .5);
      ix.moveTo(x - r * .5, y + r * .2); ix.lineTo(x - r * .5, y - r * .5); ix.lineTo(x + r * .2, y - r * .5);
      ix.stroke();
    }
  }

  function chromeShape(kind, x, y, r, rot) {
    if (kind < 4) return chromeShapeBase(kind, x, y, r, rot);
    if (r <= 0) return;
    if (kind === 4) {
      ix.lineWidth = r * .26;
      ix.strokeStyle = chromeGrad(x - r, y - r * .4, x + r, y + r * .4);
      ix.beginPath(); ix.ellipse(x, y, r, r * (.18 + .3 * Math.abs(Math.sin(rot))), rot * .4, 0, Math.PI * 2); ix.stroke();
    } else if (kind === 5) {
      ix.save(); ix.translate(x, y); ix.rotate(rot);
      var cg = ix.createLinearGradient(0, -r * .3, 0, r * .3);
      cg.addColorStop(0, '#2b2b2e'); cg.addColorStop(.3, '#ffffff'); cg.addColorStop(.6, '#8d8d92'); cg.addColorStop(1, '#1e1e20');
      ix.fillStyle = cg; ix.beginPath(); ix.roundRect(-r, -r * .28, r * 2, r * .56, r * .28); ix.fill();
      ix.restore();
    } else if (kind === 6) {
      ix.save(); ix.translate(x, y); ix.rotate(rot);
      ix.fillStyle = chromeGrad(-r, -r, r, r);
      ix.fillRect(-r * .2, -r * .8, r * .4, r * 1.6); ix.fillRect(-r * .8, -r * .2, r * 1.6, r * .4);
      ix.restore();
    } else {
      var v = [];
      for (var k = 0; k < 6; k++) v.push([x + Math.cos(rot + k * Math.PI / 3) * r * .8, y + Math.sin(rot + k * Math.PI / 3) * r * .8]);
      [[0, 1, 2, '#f4f4f4'], [2, 3, 4, '#8d8d92'], [4, 5, 0, '#3a3a3e']].forEach(function (F) {
        var g = ix.createLinearGradient(v[F[0]][0], v[F[0]][1], v[F[2]][0], v[F[2]][1]);
        g.addColorStop(0, F[3]); g.addColorStop(1, '#1e1e20');
        ix.fillStyle = g;
        ix.beginPath(); ix.moveTo(x, y); ix.lineTo(v[F[0]][0], v[F[0]][1]); ix.lineTo(v[F[1]][0], v[F[1]][1]); ix.lineTo(v[F[2]][0], v[F[2]][1]); ix.closePath(); ix.fill();
      });
    }
  }

  function wrapIn(v, m, p) { var L = m + 2 * p; return ((v + p) % L + L) % L - p; }

  function circuit(seed, color, alpha) {
    var s = unit();
    ix.globalAlpha = alpha;
    ix.strokeStyle = color;
    ix.lineWidth = 1.2;
    for (var k = 0; k < 14; k++) {
      var x = hash(k, seed) * iw, y = hash(k, seed + 1) * ih, w = (60 + hash(k, seed + 2) * 360) * s;
      ix.beginPath();
      ix.moveTo(x, y); ix.lineTo(x + w, y); ix.lineTo(x + w, y + w * .4 * (hash(k, seed + 3) > .5 ? 1 : -1));
      ix.stroke();
      if (hash(k, seed + 4) < .35) { ix.beginPath(); ix.arc(x, y, w * .25, 0, Math.PI * 2); ix.stroke(); }
      if (hash(k, seed + 5) < .3) ix.strokeRect(x + w * .5, y - 30 * s, 48 * s, 48 * s);
    }
    ix.globalAlpha = 1;
  }

  function smear(n, seed) {
    if (snap.width !== ic.width || snap.height !== ic.height) { snap.width = ic.width; snap.height = ic.height; }
    snapX.clearRect(0, 0, snap.width, snap.height);
    snapX.drawImage(ic, 0, 0);
    ix.save();
    ix.setTransform(1, 0, 0, 1, 0, 0);
    for (var k = 0; k < n; k++) {
      var y = Math.floor(hash(seed, k) * ic.height), h = Math.floor((4 + hash(seed, k + 30) * 60) * idpr);
      var x = Math.floor(hash(seed, k + 60) * ic.width * .8);
      ix.drawImage(snap, x, y, Math.max(1, Math.round(2 * idpr)), h, x, y, ic.width - x, h);
    }
    for (var b = 0; b < n; b++) {
      var bw = Math.floor((40 + hash(seed, b + 90) * 160) * idpr), bh = Math.floor((20 + hash(seed, b + 120) * 70) * idpr);
      var sx0 = Math.floor(hash(seed, b + 150) * (ic.width - bw)), sy0 = Math.floor(hash(seed, b + 180) * (ic.height - bh));
      ix.drawImage(snap, sx0, sy0, bw, bh, sx0 + Math.round((hash(seed, b + 210) - .5) * 200 * idpr), sy0, bw, bh);
    }
    ix.restore();
  }

  function avatarBox(s, x, y, size) {
    if (s.img) ix.drawImage(s.img, x, y, size, size);
  }

  function qr(x, y, size, seed, color) {
    var n = 9, c = size / n;
    ix.fillStyle = color;
    for (var i = 0; i < n; i++) for (var j = 0; j < n; j++) {
      var corner = (i < 3 && j < 3) || (i > 5 && j < 3) || (i < 3 && j > 5);
      if (corner ? !(i % 2 === 1 && j % 2 === 1 && (i === 1 || i === 7) && (j === 1 || j === 7)) && (i % 3 !== 1 || j % 3 !== 1 || false) : hash(i + seed, j) < .5) ix.fillRect(x + i * c, y + j * c, c + .3, c + .3);
    }
  }

  function brackets(color, inset, len, w) {
    ix.strokeStyle = color; ix.lineWidth = w;
    var L = inset, R = iw - inset, T = inset, B = ih - inset;
    ix.beginPath();
    ix.moveTo(L, T + len); ix.lineTo(L, T + len * .3); ix.lineTo(L + len * .3, T); ix.lineTo(L + len, T);
    ix.moveTo(R - len, T); ix.lineTo(R - len * .3, T); ix.lineTo(R, T + len * .3); ix.lineTo(R, T + len);
    ix.moveTo(L, B - len); ix.lineTo(L, B - len * .3); ix.lineTo(L + len * .3, B); ix.lineTo(L + len, B);
    ix.moveTo(R - len, B); ix.lineTo(R - len * .3, B); ix.lineTo(R, B - len * .3); ix.lineTo(R, B - len);
    ix.stroke();
  }

  function codeLine(x, y, size, opText, opBox, opBoxColor, opTextColor) {
    var parts = ['for (let i = 0; i ', opText, ' crew.length; i++)'];
    ix.font = '700 ' + size + 'px "Space Mono", monospace';
    var w0 = ix.measureText(parts[0]).width, w1 = ix.measureText(opText).width;
    itext(parts[0], x, y, '700 ' + size, INK);
    if (opBox) { ix.fillStyle = opBoxColor; ix.fillRect(x + w0 - 6, y - size * .85, w1 + 12, size * 1.1); }
    itext(opText, x + w0, y, '700 ' + size, opTextColor || INK);
    itext(parts[2], x + w0 + w1, y, '700 ' + size, INK);
  }

  function tqOf(t) { return Math.floor(t * STEP + 1e-6) / STEP; }
  function gauss(a, b) { return (hash(a, b) + hash(a, b + 1) + hash(a, b + 2)) / 1.5 - 1; }

  function lineShape(kind, x, y, r, color) {
    ix.strokeStyle = color; ix.fillStyle = color; ix.lineWidth = 1.5;
    if (kind === 0) ix.strokeRect(x - r, y - r, r * 2, r * 2);
    else if (kind === 1) { ix.beginPath(); ix.arc(x, y, r, 0, Math.PI * 2); ix.stroke(); }
    else if (kind === 2) { ix.beginPath(); ix.arc(x, y, r * .2, 0, Math.PI * 2); ix.fill(); }
    else if (kind === 3) ix.fillRect(x - r * .22, y - r * .22, r * .44, r * .44);
    else { ix.beginPath(); ix.moveTo(x - r * 1.6, y); ix.lineTo(x, y); ix.lineTo(x, y + r); ix.stroke(); }
  }

  function build(tq, o) {
    var s = unit();
    for (var k = 0; k < o.n; k++) {
      var tk = o.t0 + (o.t1 - o.t0) * Math.pow(k / o.n, o.acc || .55);
      if (tq < tk) break;
      var grow = o.spread ? .2 + .8 * Math.pow(k / o.n, .6) : 1;
      var x = o.x + gauss(k, o.seed) * o.sx * grow, y = o.y + gauss(k, o.seed + 5) * o.sy * grow;
      var age = tq - tk, pop = age < .5 / STEP ? .55 : 1;
      if (o.lines && hash(k, o.seed + 9) < .3) {
        lineShape(Math.floor(hash(k, o.seed + 10) * 5), x, y, (10 + hash(k, o.seed + 11) * 60) * s * (o.sc || 1), o.lines);
        continue;
      }
      var big = hash(k, o.seed + 12);
      var r = (big < .2 ? 120 + big * 600 : 22 + big * 90) * s * (o.sc || 1) * pop;
      chromeShape(Math.floor(hash(k, o.seed + 13) * 8), x, y, r, hash(k, o.seed + 14) * 6 + Math.floor(age * STEP) * .06 * (hash(k, o.seed + 15) - .5));
    }
  }

  function trail(tq, t0, dur, draw, path, r) {
    if (tq < t0) return;
    var steps = Math.floor((Math.min(tq, t0 + dur) - t0) * STEP + 1e-6);
    for (var i = 0; i <= steps; i++) {
      var p = path(i / (dur * STEP));
      draw(p[0], p[1], r, p[2]);
    }
  }

  function limeArc(x, y, r, rot) {
    var g = ix.createLinearGradient(x - r, y - r, x + r, y + r);
    g.addColorStop(0, '#5a7a10'); g.addColorStop(.35, ACID); g.addColorStop(.7, '#ffffff'); g.addColorStop(1, '#8fbf20');
    ix.lineWidth = r * .34; ix.lineCap = 'butt'; ix.strokeStyle = g;
    ix.beginPath(); ix.arc(x, y, r, rot, rot + Math.PI * .85); ix.stroke();
  }

  function chromeCheck(x, y, r) {
    ix.lineWidth = r * .3; ix.lineCap = 'butt'; ix.lineJoin = 'miter';
    ix.strokeStyle = chromeGrad(x - r, y - r, x + r, y + r);
    ix.beginPath(); ix.moveTo(x - r * .7, y - r * .05); ix.lineTo(x - r * .15, y + r * .5); ix.lineTo(x + r * .75, y - r * .65); ix.stroke();
  }

  function tubes(cx, cy, R, n, lenMax, wMax, seed, rot) {
    ix.lineCap = 'round';
    for (var k = 0; k < n; k++) {
      var ang = hash(k, seed) * Math.PI * 2 + rot, off = R * hash(k, seed + 3);
      var x1 = cx + Math.cos(ang) * off, y1 = cy + Math.sin(ang) * off * .8;
      var a2 = ang + hash(k, seed + 4) * 2 + rot * .5, len = lenMax * (.3 + hash(k, seed + 2) * .7);
      var x2 = x1 + Math.cos(a2) * len, y2 = y1 + Math.sin(a2) * len;
      var g = ix.createLinearGradient(x1, y1, x2, y2);
      g.addColorStop(0, '#f8f8f8'); g.addColorStop(.4, hash(k, seed + 6) < .45 ? MAG : '#8d8d92'); g.addColorStop(.7, '#2a2a2e'); g.addColorStop(1, '#ffffff');
      ix.strokeStyle = g;
      ix.lineWidth = wMax * (.35 + hash(k, seed + 7) * .65);
      ix.beginPath(); ix.moveTo(x1, y1); ix.lineTo(x2, y2); ix.stroke();
    }
  }

  function cjk(txt, x, y, size, color) {
    itext(txt, x, y, size, color, '"Noto Sans SC", "Microsoft YaHei", sans-serif');
    ix.font = size + 'px "Noto Sans SC", "Microsoft YaHei", sans-serif';
    return ix.measureText(txt).width;
  }

  function drawIntroB(t) {
    var s = unit(), cx = iw / 2, cy = ih / 2, tq = tqOf(t), fstep = Math.floor(t * STEP);

    if (t < .4) {
      ix.fillStyle = PAPER; ix.fillRect(0, 0, iw, ih);
      var st = Math.floor(t * STEP);
      if (st >= 1) chromeShape(3, cx - 150 * s, cy - 18 * s, 34 * s, 0);
      if (st >= 1) itext('OB1', cx - 70 * s, cy + 14 * s, Math.round(64 * s), INK, 'Silkscreen, monospace', 'center');
      if (st >= 2) itext('off-by-one', cx + 70 * s, cy + 10 * s, Math.round(26 * s), INK, null, 'center');
      if (st >= 3) {
        itext('> const crew = [ ... ]', cx - 120 * s, cy + 60 * s, Math.round(12 * s), '#8b8b88');
        itext('> console.log', cx - 120 * s, cy + 78 * s, Math.round(12 * s), '#8b8b88');
      }
      if (st >= 4) {
        qr(cx + 150 * s, cy + 46 * s, 34 * s, 3, INK);
        itext('void', cx - 120 * s, cy - 60 * s, Math.round(11 * s), '#8b8b88');
        itext('help', cx + 160 * s, cy - 60 * s, Math.round(11 * s), '#8b8b88');
      }
      return;
    }

    if (t < 1.5) {
      ix.fillStyle = ACID; ix.fillRect(0, 0, iw, ih);
      circuit(5, INK, .35);
      ix.fillStyle = INK;
      ix.beginPath(); ix.arc(40 * s, 40 * s, 7 * s, 0, Math.PI * 2); ix.fill();
      ix.strokeStyle = INK; ix.lineWidth = 2; ix.beginPath(); ix.arc(60 * s, 40 * s, 7 * s, 0, Math.PI * 2); ix.stroke();
      itext('> BOOT CREW', iw - 60 * s, 120 * s, '500 ' + Math.round(80 * s), INK, '"Space Grotesk", sans-serif', 'right');
      itext('const r1', 50 * s, ih - 50 * s, '500 ' + Math.round(44 * s), INK, '"Space Grotesk", sans-serif');
      codeLine(50 * s, ih - 120 * s, Math.round(22 * s), '<=', tq >= .9, INK, tq >= .9 ? '#ff2236' : INK);
      chromeShape(2, iw * .26, ih * .38, 120 * s, 2.3);
      chromeShape(0, iw * .66, ih * .27, 56 * s, .35);
      lineShape(0, iw * .6, ih * .66, 64 * s, INK);
      lineShape(3, iw * .2, ih * .7, 40 * s, INK);

      var size = 140 * s, cxs = [cx - 170 * s, cx, cx + 170 * s], sy = cy - size / 2 + 20 * s;
      var idx = tq >= .85 ? 2 : tq >= .7 ? 1 : tq >= .55 ? 0 : -1;
      for (var k = 0; k < 2; k++) {
        var x0 = cxs[k] - size / 2;
        ix.fillStyle = PAPER; ix.fillRect(x0, sy, size, size);
        avatarBox(SUBJECTS[k], x0 + 8 * s, sy + 8 * s, size - 16 * s);
        ix.strokeStyle = INK; ix.lineWidth = idx > k ? 6 * s : 3 * s; ix.strokeRect(x0, sy, size, size);
        itext('crew[' + k + ']', cxs[k], sy + size + 30 * s, Math.round(18 * s), INK, null, 'center');
        if (idx > k) {
          ix.fillStyle = INK; ix.fillRect(x0 + size - 54 * s, sy - 14 * s, 54 * s, 26 * s);
          itext('OK', x0 + size - 27 * s, sy + 5 * s, '700 ' + Math.round(15 * s), ACID, null, 'center');
        }
      }
      if (idx === 2) {
        var x2 = cxs[2] - size / 2;
        if (tq < 1.0 && fstep % 2 === 0) { ix.fillStyle = '#ff2236'; ix.fillRect(x2, sy, size, size); }
        ix.setLineDash([10 * s, 8 * s]); ix.strokeStyle = '#ff2236'; ix.lineWidth = 4 * s;
        ix.strokeRect(x2, sy, size, size); ix.setLineDash([]);
        itext('undefined', cxs[2], sy + size / 2 + 7 * s, '700 ' + Math.round(20 * s), INK, null, 'center');
        itext('crew[2]', cxs[2], sy + size + 30 * s, Math.round(18 * s), '#ff2236', null, 'center');
      }
      if (idx >= 0) {
        var px = cxs[idx];
        ix.fillStyle = INK;
        ix.beginPath(); ix.moveTo(px - 14 * s, sy - 34 * s); ix.lineTo(px + 14 * s, sy - 34 * s); ix.lineTo(px, sy - 14 * s); ix.closePath(); ix.fill();
        itext('i = ' + idx, px, sy - 46 * s, '700 ' + Math.round(22 * s), INK, null, 'center');
      }
      build(tq, { t0: .93, t1: 1.46, n: 78, seed: 21, x: cxs[2], y: sy + size / 2, sx: iw * .34, sy: ih * .36, spread: true, lines: INK });
      return;
    }

    if (t < 2.75) {
      var dark = tq >= 2.2;
      ix.fillStyle = dark ? '#050507' : BLUE; ix.fillRect(0, 0, iw, ih);
      circuit(9, '#ffffff', dark ? .22 : .45);
      lineShape(1, iw * .28, ih * .38, 70 * s, 'rgba(255,255,255,.75)');
      lineShape(0, iw * .36, ih * .2, 40 * s, 'rgba(255,255,255,.75)');
      itext('Configuration applied', 50 * s, 60 * s, '500 ' + Math.round(22 * s), '#ffffff', '"Space Grotesk", sans-serif');
      for (var di = 0; di < 4; di++) for (var dj = 0; dj < 3; dj++) { ix.fillStyle = '#ffffff'; ix.fillRect(iw - 160 * s + di * 30 * s, 50 * s + dj * 22 * s, 3 * s, 3 * s); }
      itext('> run', 50 * s, ih * .45, Math.round(18 * s), '#ffffff');
      cjk('补丁', iw * .64, ih * .45, Math.round(18 * s), '#ffffff');
      itext('> fix', iw * .74, ih * .45, Math.round(18 * s), '#ffffff');
      itext('> check status', 140 * s, ih - 116 * s, Math.round(13 * s), '#ffffff');
      var cw = cjk('补丁', 50 * s, ih - 60 * s, Math.round(56 * s), '#ffffff');
      itext('a p p l i e d', 50 * s + cw + 24 * s, ih - 60 * s, Math.round(56 * s), '#ffffff', '"Space Grotesk", sans-serif');
      ix.fillStyle = '#ffffff'; ix.fillRect(50 * s, ih - 40 * s, 640 * s, 2);

      var big = Math.round(84 * s), sel = tq >= 1.72, del = tq >= 1.84, fixed = tq >= 1.92;
      var op = del ? '<' : '<=', pre = 'i ', post = ' crew.length';
      ix.font = '700 ' + big + 'px "Space Mono", monospace';
      var wPre = ix.measureText(pre).width, wOp = ix.measureText(op).width, wPost = ix.measureText(post).width;
      var x0c = cx - (wPre + wOp + wPost) / 2, y0c = cy - 10 * s;
      if (sel && !fixed) { ix.fillStyle = '#ff2236'; ix.fillRect(x0c + wPre - 8, y0c - big * .85, wOp + 16, big * 1.1); }
      if (fixed) { ix.fillStyle = ACID; ix.fillRect(x0c + wPre - 8, y0c - big * .85, wOp + 16, big * 1.1); }
      itext(pre, x0c, y0c, '700 ' + big, '#ffffff');
      itext(op, x0c + wPre, y0c, '700 ' + big, fixed ? INK : '#ffffff');
      itext(post, x0c + wPre + wOp, y0c, '700 ' + big, '#ffffff');
      if (fixed) itext('// <= → <', x0c, y0c + 56 * s, Math.round(22 * s), ACID);

      if (tq >= 1.94) chromeCheck(iw * .72, ih * .7, 110 * s);
      trail(tq, 1.98, .6, limeArc, function (u) { return [lerp(iw * .9, iw * .14, u), ih * .3 + Math.sin(u * 3.2) * ih * .06, -2.5 + u * .7]; }, 150 * s);
      trail(tq, 2.1, .55, function (x, y, r, rot) { chromeShape(2, x, y, r, rot); }, function (u) { return [lerp(iw * .82, iw * .08, u), ih * .6 - Math.sin(u * 2.6) * ih * .05, -2.9 + u]; }, 120 * s);
      build(tq, { t0: 2.2, t1: 2.72, n: 60, seed: 44, x: cx, y: ih * .76, sx: iw * .55, sy: ih * .2, lines: '#ffffff' });
      return;
    }

    if (t < 3.9) {
      ix.fillStyle = BLUE; ix.fillRect(0, 0, iw, ih);
      brackets('#ffffff', 16 * s, 70 * s, 1.5);
      itext('EXIT', 30 * s, 80 * s, '500 ' + Math.round(66 * s), '#ffffff', '"Space Grotesk", sans-serif');
      itext('const r1:', 230 * s, 46 * s, Math.round(16 * s), '#ffffff');
      ix.strokeStyle = '#ffffff'; ix.lineWidth = 1.5; ix.strokeRect(330 * s, 33 * s, 220 * s, 14 * s);
      itext('GR 0x1F2A-27', 600 * s, 46 * s, Math.round(12 * s), '#ffffff');
      ix.save(); ix.translate(iw - 34 * s, 130 * s); ix.rotate(Math.PI / 2);
      itext('status', 0, 0, Math.round(22 * s), '#ffffff'); ix.restore();
      qr(iw - 80 * s, ih - 80 * s, 46 * s, 9, '#ffffff');
      itext('00.000, -01.000', iw - 100 * s, ih - 30 * s, Math.round(13 * s), '#ffffff', null, 'right');
      itext('■□□', cx, ih - 30 * s, Math.round(16 * s), '#ffffff', null, 'center');
      chromeShape(2, iw * .66, ih * .55, 110 * s, 1.0);

      var LINES = ['> boot(crew[0])', 'OK', '> boot(crew[1])', 'OK', '> exit 0', 'None', 'END', 'CREW 2/2', 'const', 'i < crew.length'];
      for (var g = 0; g < 44; g++) {
        var tg = 2.82 + 1.0 * Math.pow(g / 44, .55);
        if (tq < tg) break;
        ix.fillStyle = hash(g, 1) < .5 ? '#9a9aa8' : hash(g, 1) < .75 ? ACID : '#ffffff';
        ix.fillRect(iw * (.1 + hash(g, 2) * .6), ih * (.25 + hash(g, 3) * .6), (60 + hash(g, 4) * 420) * s, (6 + hash(g, 5) * 26) * s);
      }
      for (var k2 = 0; k2 < 44; k2++) {
        var tk2 = 2.8 + 1.02 * Math.pow(k2 / 44, .55);
        if (tq < tk2) break;
        var fs = Math.round((18 + hash(k2, 13) * 66) * s), txt = LINES[k2 % LINES.length];
        var tx = iw * (.14 + hash(k2, 14) * .56), ty = ih * (.22 + hash(k2, 15) * .62);
        if (hash(k2, 17) < .3) { ix.fillStyle = '#b8b8c4'; ix.fillRect(tx - 4, ty - fs * .85, fs * txt.length * .55, fs * 1.05); }
        itext(txt, tx, ty, '500 ' + fs, hash(k2, 16) < .75 ? '#ffffff' : ACID, '"Space Grotesk", sans-serif');
      }
      build(tq, { t0: 2.92, t1: 3.86, n: 46, seed: 63, x: cx + 60 * s, y: ih * .62, sx: iw * .3, sy: ih * .2, sc: .8 });
      if (tq >= 3.3) smear(Math.round(lerp(4, 18, seg(tq, 3.3, 3.86))), fstep);
      return;
    }

    var dis = seg(t, 5.1, 5.55);
    ix.save();
    if (dis > 0) {
      ix.beginPath();
      var Bk = 64;
      for (var bi = 0; bi * Bk < iw; bi++) for (var bj = 0; bj * Bk < ih; bj++) if (hash(bi * 7 + 1, bj * 13 + 2) >= dis) ix.rect(bi * Bk, bj * Bk, Bk, Bk);
      ix.clip();
    }
    ix.fillStyle = '#ffffff'; ix.fillRect(0, 0, iw, ih);
    brackets(INK, 30 * s, 90 * s, 1.5);
    if (tq < 4.34) {
      var b = easeOut(seg(tq, 3.9, 4.25));
      tubes(cx, cy, Math.max(iw, ih) * .55 * b, 120, 700 * s * (.2 + b), 52 * s, 501, tq * .5);
    } else {
      var gr = 1 + seg(tq, 4.34, 5.2) * .45;
      tubes(cx, cy - 110 * s, 46 * s * gr, 70, 70 * s * gr, 16 * s * gr, 601, tq * .9);
      if (tq >= 4.5) {
        var pop = seg(tq, 4.5, 4.7);
        var cell = Math.max(3, Math.floor(Math.min(iw * .44 / LOGO_W, ih * .09 / LOGO_H)));
        var lw = LOGO_W * cell, lh = LOGO_H * cell, lx = Math.round(cx - lw / 2), ly = Math.round(cy + 10 * s);
        ix.fillStyle = INK;
        for (var q = 0; q < LOGO.length; q++) if (hash(q, 9) <= pop) ix.fillRect(lx + LOGO[q].x * cell, ly + LOGO[q].y * cell, cell - 1, cell - 1);
        ix.fillStyle = MAG; ix.fillRect(lx, ly + lh + 16 * s, lw * pop, 5 * s);
        var sub = 'named after our favorite bug.';
        itext(sub.slice(0, Math.max(0, Math.floor((t - 4.62) * 60))), cx, ly + lh + 56 * s, Math.round(22 * s), '#6d6d75', null, 'center');
      }
    }
    ix.restore();
    if (dis > 0 && dis < 1) smear(8, fstep);
  }

  function drawIntro(t) {
    if (t >= INTRO_END) {
      if (!introGone) {
        introGone = true;
        ic.style.display = 'none';
        document.documentElement.classList.remove('intro');
      }
      return;
    }
    if (window.innerWidth !== iw || window.innerHeight !== ih) fitIntro();
    var f = Math.floor(t * STEP + 1e-6);
    if (f === introFrame) return;
    introFrame = f;
    ix.setTransform(idpr, 0, 0, idpr, 0, 0);
    ix.globalAlpha = 1; ix.globalCompositeOperation = 'source-over'; ix.filter = 'none';
    ix.clearRect(0, 0, iw, ih);
    drawIntroB(f / STEP);
  }

  function drawExit(t) {
    var e = t - exit.at;
    if (e >= EXIT_IN && !exit.done) {
      exit.done = true;
      if (exit.blank) window.open(exit.href, '_blank', 'noopener,noreferrer');
      else location.href = exit.href;
    }
    if (e >= EXIT_IN + (exit.blank ? EXIT_OUT : 5)) {
      exit = null;
      ic.style.display = 'none';
      return;
    }
    if (window.innerWidth !== iw || window.innerHeight !== ih) { fitIntro(); exitFrame = -1; }
    var f = Math.floor(t * STEP + 1e-6);
    if (f === exitFrame) return;
    exitFrame = f;
    var cover = e < EXIT_IN ? seg(e, 0, EXIT_IN) : exit.blank ? 1 - seg(e, EXIT_IN, EXIT_IN + EXIT_OUT) : 1;
    var bk = Math.max(28, Math.round(Math.min(iw, ih) / 14));
    ix.setTransform(idpr, 0, 0, idpr, 0, 0);
    ix.clearRect(0, 0, iw, ih);
    for (var bi = 0; bi * bk < iw; bi++) for (var bj = 0; bj * bk < ih; bj++) {
      var th = hash(bi * 7 + 1, bj * 13 + 2) * .85;
      if (th >= cover) continue;
      ix.fillStyle = cover < 1 && cover - th < .15 ? (hash(bi, bj + 31) < .5 ? ACID : BLUE) : INK;
      ix.fillRect(bi * bk, bj * bk, bk, bk);
    }
  }

  function leave(href, blank) {
    if (exit) return;
    if (reduceMotion || now < INTRO_END) {
      if (blank) window.open(href, '_blank', 'noopener,noreferrer');
      else location.href = href;
      return;
    }
    fitIntro();
    exitFrame = -1;
    exit = { at: now, href: href, blank: blank, done: false };
    ic.style.display = 'block';
  }


  /* ── Page boot ─────────────────────────────────── */

  var BOOT_FROM = INTRO_END - .6;
  var boots = Array.prototype.map.call(document.querySelectorAll('.boot'), function (el) {
    return { el: el, delay: parseFloat(el.dataset.delay) || 0, seen: null, state: 0 };
  });
  function bootOf(el) {
    var b = el.closest('.boot');
    for (var i = 0; i < boots.length; i++) if (boots[i].el === b) return boots[i];
    return null;
  }
  function bootStart(b) { return b && b.seen !== null ? b.seen + b.delay : null; }

  function bootTick(t, vh) {
    var i, b;
    if (t >= BOOT_FROM) for (i = 0; i < boots.length; i++) {
      b = boots[i];
      if (b.seen === null && b.el.getBoundingClientRect().top < vh * .92) b.seen = Math.max(t, BOOT_FROM);
    }
    for (i = 0; i < boots.length; i++) {
      b = boots[i];
      if (b.seen === null || b.state === 2) continue;
      var p = easeOut(seg(t, b.seen + b.delay, b.seen + b.delay + .55));
      if (p >= 1) {
        if (b.state !== 2) {
          b.state = 2;
          b.el.classList.remove('booting');
          b.el.classList.add('done');
          b.el.style.removeProperty('--p');
        }
        continue;
      }
      b.state = 1;
      b.el.classList.add('booting');
      b.el.style.setProperty('--p', p.toFixed(4));
    }
  }

  var scrambles = Array.prototype.map.call(document.querySelectorAll('[data-scramble]'), function (el) {
    return { el: el, final: el.textContent, boot: bootOf(el), last: null };
  });
  function scrambleTick(t) {
    var fstep = Math.floor(t * 24);
    scrambles.forEach(function (s, si) {
      var st = bootStart(s.boot);
      var out;
      if (st === null) out = s.final;
      else {
        var a = st + .1, dur = Math.min(.9, .25 + s.final.length * .012);
        var q = seg(t, a, a + dur);
        if (q >= 1) out = s.final;
        else {
          var k = Math.floor(q * s.final.length);
          out = '';
          for (var i = 0; i < s.final.length; i++) {
            var ch = s.final[i];
            out += (i < k || ch === ' ') ? ch : GLYPHS[Math.floor(hash(i + si * 131, fstep) * GLYPHS.length)];
          }
        }
      }
      if (out !== s.last) { s.el.textContent = out; s.last = out; }
    });
  }


  var counters = Array.prototype.map.call(document.querySelectorAll('[data-count]'), function (el) {
    return { el: el, key: el.dataset.count, boot: bootOf(el), last: null };
  });
  function countTick(t) {
    counters.forEach(function (c) {
      var st = bootStart(c.boot), v = DATA[c.key], s;
      if (v === null || st === null) s = '—';
      else {
        var a = Math.max(st + .2, dataAt === null ? 0 : dataAt);
        s = Math.round(v * easeOut(seg(t, a, a + 1.4))).toLocaleString('en-US');
      }
      if (s !== c.last) { c.el.textContent = s; c.last = s; }
    });
  }


  /* ── Ambient ───────────────────────────────────── */

  var clock = document.getElementById('clock');
  var gens = document.querySelectorAll('[data-gen]');
  var cursor = document.querySelector('.cursor');
  var dot = document.querySelector('.dot');
  var ticker = document.querySelector('.ticker');
  var track = document.querySelector('.ticker-track');
  var glyphBox = document.querySelector('.glyphs');
  var glyphCells = [], trackUnit = 0;
  for (var g = 0; g < 18; g++) {
    var sp = document.createElement('span');
    glyphBox.appendChild(sp);
    glyphCells.push(sp);
  }

  function pad(n) { return String(n).padStart(2, '0'); }
  function ambientTick(t) {
    var d = new Date();
    var cs = 'UTC ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds());
    if (clock.textContent !== cs) clock.textContent = cs;
    var step = Math.floor(t * 4);
    gens.forEach(function (el) {
      var k = el.dataset.gen, v;
      if (k === 'coords') v = (51.2227 + hash(step, 1) * .01).toFixed(4) + ' N - ' + (6.7685 + hash(step, 2) * .01).toFixed(4) + ' E';
      else if (k === 'hex') v = '0x' + code(step, 4) + ' · CH ' + pad(Math.floor(hash(step, 3) * 99));
      else if (k === 'rcv') v = (.9 + hash(step, 5) * .09).toFixed(2) + ' RCV';
      if (el.textContent !== v) el.textContent = v;
    });
    cursor.style.opacity = Math.floor(t * 2.2) % 2 ? '0' : '1';
    dot.style.opacity = Math.floor(t * 1.5) % 2 ? '.35' : '1';
    if (trackUnit) track.style.transform = 'translateX(' + (-((t * 70) % trackUnit)).toFixed(1) + 'px)';
    ticker.style.setProperty('--sweep', ((t * .3) % 1).toFixed(4));
    for (var i = 0; i < glyphCells.length; i++) {
      var ch = hash(i, 99) < .16 ? '' : GLYPHS[Math.floor(hash(i, Math.floor(t * 5 + hash(i, 9) * 5)) * GLYPHS.length)];
      if (glyphCells[i].textContent !== ch) glyphCells[i].textContent = ch;
    }
  }


  function prep(c, r, key) {
    if (!r || r.width === 0 || r.bottom < 0 || r.top > window.innerHeight) return null;
    var dpr = cdpr();
    var w = Math.round(r.width * dpr), h = Math.round(r.height * dpr);
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; c._key = null; }
    if (c._key === key) return null;
    c._key = key;
    var x = c.getContext('2d');
    x.setTransform(dpr, 0, 0, dpr, 0, 0);
    x.clearRect(0, 0, r.width, r.height);
    return { x: x, w: r.width, h: r.height };
  }

  function withCtx(x, w, sh, fn) {
    var sv = [ix, iw, ih, idpr];
    ix = x; iw = w; ih = sh; idpr = cdpr();
    try { fn(); } finally { ix = sv[0]; iw = sv[1]; ih = sv[2]; idpr = sv[3]; }
  }

  function heroOverflow(x, w, h, t) {
    var tq = tqOf(t), cyc = tq % 4.4;
    x.fillStyle = '#2b0bff'; x.fillRect(0, 0, w, h);
    withCtx(x, w, h, function () { circuit(5, '#ffffff', .25); });
    withCtx(x, w, 1080 * .55 * Math.min(1, w / 640), function () {
      var size = Math.min(h * .36, w * .2), gap = size * 1.25, cx = w / 2, sy = h * .5 - size * .45;
      var cxs = [cx - gap, cx, cx + gap], idx = cyc >= 1.0 ? 2 : cyc >= .7 ? 1 : cyc >= .4 ? 0 : -1;
      chromeShape(2, w * .14, h * .26, size * .5, 2.3);
      chromeShape(0, w * .86, h * .2, size * .26, .35);
      lineShape(0, w * .82, h * .74, size * .3, 'rgba(255,255,255,.7)');
      for (var k = 0; k < 3; k++) {
        var xx = cxs[k] - size / 2;
        if (k < 2) {
          ix.fillStyle = '#b4ff1f'; ix.fillRect(xx, sy, size, size);
          avatarBox(SUBJECTS[k], xx + 6, sy + 6, size - 12);
          ix.strokeStyle = '#121212'; ix.lineWidth = idx > k ? 5 : 3; ix.strokeRect(xx, sy, size, size);
          if (idx > k) { ix.fillStyle = '#121212'; ix.fillRect(xx + size - 34, sy - 10, 34, 20); itext('OK', xx + size - 17, sy + 5, '700 12', '#b4ff1f', null, 'center'); }
        } else if (idx === 2) {
          if (cyc < 1.15 && Math.floor(tq * STEP) % 2 === 0) { ix.fillStyle = '#ff2236'; ix.fillRect(xx, sy, size, size); }
          ix.setLineDash([8, 6]); ix.strokeStyle = '#ff4a6a'; ix.lineWidth = 3; ix.strokeRect(xx, sy, size, size); ix.setLineDash([]);
          itext('undefined', cxs[k], sy + size / 2 + 5, '700 14', '#ffffff', null, 'center');
        }
        itext('crew[' + k + ']', cxs[k], sy + size + 22, '700 12', k === 2 && idx === 2 ? '#ff4a6a' : '#ffffff', null, 'center');
      }
      if (idx >= 0) {
        var px = cxs[idx];
        ix.fillStyle = '#ffffff';
        ix.beginPath(); ix.moveTo(px - 10, sy - 30); ix.lineTo(px + 10, sy - 30); ix.lineTo(px, sy - 16); ix.closePath(); ix.fill();
        itext('i = ' + idx, px, sy - 38, '700 14', '#ffffff', null, 'center');
      }
      build(cyc, { t0: 1.1, t1: 3.6, n: 34, seed: 21 + Math.floor(tq / 4.4) * 7, x: cxs[2], y: sy + size / 2, sx: w * .3, sy: h * .34, spread: true, lines: '#ffffff', sc: .9, acc: .7 });
      itext(idx === 2 ? 'TypeError: crew[2] is undefined' : 'for (let i = 0; i <= crew.length; i++)', 16, h - 16, '700 13', idx === 2 ? '#ff4a6a' : '#b4ff1f');
    });
  }


  var fxShapes = document.querySelector('.fx-shapes');
  function fxShapesTick(t, r, sy) {
    if (!fxShapes) return;
    var c = prep(fxShapes, r, Math.floor(t * 30) + ':' + sy);
    if (!c) return;
    withCtx(c.x, c.w, 1080, function () {
      for (var k = 0; k < 18; k++) {
        var par = .25 + hash(k, 3) * .6;
        var x = wrapIn(hash(k, 1) * c.w + (hash(k, 6) - .5) * 240 * t, c.w, 120);
        var y = wrapIn(hash(k, 2) * c.h * 1.6 - sy * par + (hash(k, 7) - .5) * 160 * t, c.h, 120);
        chromeShape(Math.floor(hash(k, 8) * 8), x, y, 24 + hash(k, 9) * 56, t * (hash(k, 4) - .5) * 8 + k);
      }
    });
  }


  var radar = document.querySelector('.radar');
  function heroTick(t, r) {
    var c = prep(radar, r, tqOf(t));
    if (c) heroOverflow(c.x, c.w, c.h, t);
  }

  var waves = document.querySelectorAll('.wave');

  function waveTick(t, rs) {
    waves.forEach(function (cv, wi) {
      var c = prep(cv, rs[wi], Math.floor(t * 30));
      if (!c) return;
      var x = c.x, w = c.w, h = c.h, mid = h / 2;
      x.strokeStyle = INK; x.lineWidth = 1.5;
      x.beginPath();
      for (var px = 0; px <= w; px += 3) {
        var amp = h * (.12 + .18 * (.5 + .5 * Math.sin(t * 1.7 + px * .02 + wi)));
        var y = mid + Math.sin(px * .21 + t * 18 + wi * 2) * amp * .6 + (hash(px + wi * 999, Math.floor(t * 20)) - .5) * amp;
        if (px === 0) x.moveTo(px, y); else x.lineTo(px, y);
      }
      x.stroke();
    });
  }

  function drawBarcodes() {
    document.querySelectorAll('.barcode').forEach(function (cv) {
      var r = cv.getBoundingClientRect();
      var dpr = window.devicePixelRatio || 1;
      cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
      var x = cv.getContext('2d');
      x.setTransform(dpr, 0, 0, dpr, 0, 0);
      x.fillStyle = INK;
      var seed = parseInt(cv.dataset.seed, 10), px = 0, i = 0;
      while (px < r.width - 120) {
        var bw = 1 + Math.floor(hash(seed, i) * 4);
        x.fillRect(px, 0, bw, r.height - 12);
        px += bw + 1 + Math.floor(hash(seed, i + 500) * 4);
        i++;
      }
      x.font = '10px "Space Mono", monospace';
      x.fillStyle = DIM;
      x.textAlign = 'right';
      x.fillText('ID ' + code(seed, 8), r.width, r.height - 14);
    });
  }


  function drawIdenticons() {
    document.querySelectorAll('canvas.avatar').forEach(function (cv, n) {
      var seed = n % 2 ? 41 : 17, S = 8;
      cv.width = S; cv.height = S;
      var x = cv.getContext('2d');
      x.fillStyle = INK;
      x.fillRect(0, 0, S, S);
      for (var j = 0; j < S; j++) for (var i = 0; i < S / 2; i++) {
        if (hash(seed + i, j * 7) >= .5) continue;
        x.fillStyle = hash(seed, i * 13 + j) < .2 ? '#ffffff' : ACID;
        x.fillRect(i, j, 1, 1); x.fillRect(S - 1 - i, j, 1, 1);
      }
    });
  }

  document.querySelectorAll('.project[data-href]').forEach(function (card) {
    card.addEventListener('click', function (e) {
      if (e.target.closest('a')) return;
      leave(card.dataset.href, false);
    });
    card.addEventListener('keydown', function (e) {
      if (e.target === card && e.key === 'Enter') leave(card.dataset.href, false);
    });
  });

  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || a.hasAttribute('download')) return;
    var url = new URL(a.href, location.href);
    if (!/^https?:$/.test(url.protocol)) return;
    if (url.origin === location.origin && url.pathname === location.pathname && url.search === location.search) return;
    e.preventDefault();
    leave(url.href, a.target === '_blank');
  });

  window.addEventListener('pageshow', function (e) {
    if (e.persisted && exit) { exit = null; ic.style.display = 'none'; }
  });

  /* ── Clock ─────────────────────────────────────── */

  function rectOf(el) { return el ? el.getBoundingClientRect() : null; }

  function tick(t) {
    now = t;
    drawIntro(t);
    if (exit) drawExit(t);
    if (t < PAGE_FROM) return;
    var vh = window.innerHeight, sy = window.scrollY;
    var rRadar = rectOf(radar), rFx = rectOf(fxShapes), rWaves = Array.prototype.map.call(waves, rectOf);
    bootTick(t, vh);
    scrambleTick(t);
    countTick(t);
    ambientTick(t);
    heroTick(t, rRadar);
    fxShapesTick(t, rFx, sy);
    waveTick(t, rWaves);
  }

  var start = 0, skip = 0, seen = false;
  try { seen = sessionStorage.getItem('ob1-intro') === '1'; sessionStorage.setItem('ob1-intro', '1'); } catch (e) {}
  if (seen || reduceMotion) skip = INTRO_END;
  function skipIntro() {
    var t = (performance.now() - start) / 1000 + skip;
    if (t < INTRO_END) skip += INTRO_END - t;
  }

  function measureTrack() { trackUnit = track.firstElementChild.offsetWidth; }

  fitIntro();
  window.addEventListener('resize', function () { fitIntro(); drawBarcodes(); measureTrack(); });

  var fonts = document.fonts ? Promise.all([
    document.fonts.load('16px "Space Mono"'), document.fonts.load('700 16px "Space Mono"'),
    document.fonts.load('16px Silkscreen'), document.fonts.load('700 16px "Space Grotesk"')
  ]).catch(function () {}) : Promise.resolve();
  var settle = function (p, ms) { return Promise.race([p, new Promise(function (r) { setTimeout(r, ms); })]); };

  settle(fonts, 2500).then(function () {
    buildLogo();
    drawBarcodes();
    measureTrack();
    drawIdenticons();
    window.addEventListener('keydown', skipIntro);
    ic.addEventListener('click', skipIntro);
    start = performance.now();
    (function loop() {
      tick((performance.now() - start) / 1000 + skip);
      requestAnimationFrame(loop);
    })();
  });
})();

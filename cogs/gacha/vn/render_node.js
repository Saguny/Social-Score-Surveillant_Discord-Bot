'use strict';
/**
 * VN scene renderer — node-canvas port of scripts/vn_editor/static/preview.js drawScene().
 * Protocol: reads newline-delimited JSON from stdin, writes length-prefixed PNG to stdout.
 *   stdin:  <JSON>\n
 *   stdout: [4-byte big-endian uint32 length][PNG bytes]  — length=0 signals an error
 */

const { createCanvas, loadImage, GlobalFonts } = require('@napi-rs/canvas');
const path = require('path');
const fs   = require('fs');

// Per-worker image cache — same URL only fetched once per worker lifetime
const _imgCache    = new Map(); // url → { img, ts }
const _IMG_TTL     = 10 * 60 * 1000; // 10 minutes
const _IMG_MAX     = 150;             // max cached images per worker

async function _loadImg(url) {
  if (!url) return null;
  const now    = Date.now();
  const cached = _imgCache.get(url);
  if (cached && now - cached.ts < _IMG_TTL) return cached.img;
  try {
    const img = await loadImage(url);
    _imgCache.set(url, { img, ts: now });
    if (_imgCache.size > _IMG_MAX) _imgCache.delete(_imgCache.keys().next().value);
    return img;
  } catch (_) { return null; }
}

// Register fonts from the bot's fonts/ directory if present
const FONTS_DIR = path.join(__dirname, '..', '..', '..', 'fonts');
for (const [file, family] of [
  ['NotoSansSC-Regular.otf', 'Noto Sans SC'],
  ['NotoSans-Regular.ttf',   'Noto Sans'],
  ['NotoSans-Bold.ttf',      'Noto Sans'],
]) {
  const fp = path.join(FONTS_DIR, file);
  if (fs.existsSync(fp)) {
    try { GlobalFonts.registerFromPath(fp, family); } catch (_) {}
  }
}

const W = 960, H = 540;          // output resolution (1.5× the editor's 640×360)
const SC = W / 640;              // scale factor — all preview.js pixel values multiply by this

const POSITIONS = {
  L: W * 0.12, CL: W * 0.30, C: W * 0.50, CR: W * 0.70, R: W * 0.88,
};

// ── Exact copies of preview.js helpers ──────────────────────────────────────

function _roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function _wrapText(ctx, text, x, y, maxW, lineH, maxLines, stroke) {
  const draw = t => stroke ? ctx.strokeText(t, x, y) : ctx.fillText(t, x, y);
  const words = String(text || '').split(' ');
  let line = '', lines = 0;
  for (const word of words) {
    const test = line + (line ? ' ' : '') + word;
    if (ctx.measureText(test).width > maxW && line) {
      if (lines >= maxLines - 1) {
        stroke ? ctx.strokeText(line + ' …', x, y) : ctx.fillText(line + ' …', x, y);
        return;
      }
      draw(line);
      y += lineH; lines++;
      line = word;
    } else { line = test; }
  }
  if (line) draw(line);
}

// ── Main renderer ────────────────────────────────────────────────────────────

async function renderScene(req) {
  const {
    bg_url, ui_url, chars,       // chars: [{url, position}]
    speaker, dialogue_text,
    text_color, ui_scale, bg_blur,
    scene_type, ending_type, choices,
    cfg,
  } = req;

  const sc = SC;
  const BOX_H = Math.round(H * 0.36);

  // cfg mirrors vn_config table columns (all optional, same defaults as preview.js)
  const sdx        = (cfg.speaker_dx       || 0) * sc;
  const sdy        = (cfg.speaker_dy       || 0) * sc;
  const tdx        = (cfg.text_dx          || 0) * sc;
  const tdy        = (cfg.text_dy          || 0) * sc;
  const charPadTop = (cfg.char_pad_top     || 0) * sc;
  const charScale  = cfg.char_scale  ?? 1.0;
  const speakerFs  = Math.round((cfg.speaker_font_size || 13) * sc);
  const textFs     = Math.round((cfg.text_font_size    || 13) * sc);
  const textAreaWCfg = (cfg.text_area_w || 0) * sc;
  const showBox    = cfg.speaker_box !== false;
  const tc         = text_color || 'black';
  const boxColor   = cfg.speaker_box_color || (tc === 'pink-outline' ? '#e91e8c' : '#c0392b');
  const scale      = ui_scale ?? cfg.ui_scale ?? 1.0;

  // Load all images in parallel via per-worker cache
  const [bgImg, uiImg, ...charImgs] = await Promise.all([
    _loadImg(bg_url),
    _loadImg(ui_url),
    ...(chars || []).map(c => _loadImg(c.url)),
  ]);

  const canvas = createCanvas(W, H);
  const ctx    = canvas.getContext('2d');

  // ── Background ──
  if (bgImg) {
    if (bg_blur > 0) ctx.filter = `blur(${bg_blur * sc}px)`;
    ctx.drawImage(bgImg, 0, 0, W, H);
    if (bg_blur > 0) ctx.filter = 'none';
  } else {
    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, W, H);
  }

  // ── Character sprites ──
  const fullAreaH = H - BOX_H;
  const sprBottom = H - BOX_H;
  (chars || []).forEach((c, i) => {
    const img = charImgs[i];
    if (!img) return;
    const px   = POSITIONS[c.position] ?? W * 0.5;
    const sprH = fullAreaH * charScale;
    const sprW = (img.width / img.height) * sprH;
    ctx.drawImage(img, px - sprW / 2, sprBottom - sprH + charPadTop, sprW, sprH);
  });

  // ── Dialogue box ──
  let boxY = H - BOX_H;
  if (uiImg) {
    const uiDrawW = W * scale;
    const uiDrawH = (uiImg.height / uiImg.width) * uiDrawW;
    const uiDrawX = (W - uiDrawW) / 2;
    const uiDrawY = H - uiDrawH;
    boxY = uiDrawY;
    ctx.drawImage(uiImg, uiDrawX, uiDrawY, uiDrawW, uiDrawH);
  } else {
    ctx.fillStyle = 'rgba(10,10,10,0.88)';
    ctx.fillRect(0, boxY, W, BOX_H);
    ctx.fillStyle = '#c0392b';
    ctx.fillRect(0, boxY, W, 3);
  }

  // ── Speaker namebox ──
  const spk = (speaker || 'narrator').trim();
  if (spk.toLowerCase() !== 'narrator') {
    ctx.font = `bold ${speakerFs}px "Noto Sans SC", "Noto Sans", sans-serif`;
    const nameUp = spk.toUpperCase();
    const nameW  = ctx.measureText(nameUp).width + 24 * sc;
    if (showBox) {
      ctx.fillStyle = boxColor;
      _roundRect(ctx, 16 * sc + sdx, boxY - speakerFs - 8 * sc + sdy, nameW, speakerFs + 8 * sc, 4);
      ctx.fill();
      ctx.fillStyle = '#fff';
    } else {
      ctx.fillStyle = tc === 'black' ? '#111' : '#fff';
    }
    ctx.textAlign = 'left';
    ctx.fillText(nameUp, 28 * sc + sdx, boxY - 5 * sc + sdy);
  }

  // ── Dialogue text ──
  const textX    = 24 * sc + tdx;
  const textY    = boxY + textFs + 8 * sc + tdy;
  const maxW     = textAreaWCfg || (W - textX - 24 * sc);
  const lineH    = textFs + 5;
  ctx.font       = `${textFs}px "Noto Sans SC", "Noto Sans", sans-serif`;
  ctx.textAlign  = 'left';
  if (tc === 'pink-outline') {
    ctx.strokeStyle = '#e91e8c';
    ctx.lineWidth   = 3;
    ctx.lineJoin    = 'round';
    _wrapText(ctx, dialogue_text, textX, textY, maxW, lineH, 8, true);
    ctx.lineWidth = 1;
  }
  ctx.fillStyle = tc === 'black' ? '#111' : '#fff';
  _wrapText(ctx, dialogue_text, textX, textY, maxW, lineH, 8, false);

  // ── Choice / ending badge (matches preview.js) ──
  if (scene_type === 'choice' && choices?.length) {
    ctx.fillStyle = '#8e44ad99';
    ctx.fillRect(0, H - 28, W, 28);
    ctx.fillStyle = '#c8a8f0';
    ctx.font = `${textFs - 1}px "Noto Sans SC", "Noto Sans", sans-serif`;
    ctx.textAlign = 'center';
    ctx.fillText(`▲ ${choices.length} choices`, W / 2, H - 10);
  }
  if (scene_type === 'ending') {
    const colors = { good: '#27ae60', neutral: '#f39c12', bad: '#c0392b' };
    const endingFs = Math.round(48 * sc);
    ctx.font = `bold ${endingFs}px "Noto Sans SC", "Noto Sans", sans-serif`;
    ctx.textAlign = 'center';
    const label = `${(ending_type || 'ending').toUpperCase()} END`;
    // shadow
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.fillText(label, W / 2 + 3, H / 2 + 3);
    // main text
    ctx.fillStyle = colors[ending_type] || '#ffffff';
    ctx.fillText(label, W / 2, H / 2);
  }

  return canvas.toBuffer('image/png');
}

// ── stdin/stdout protocol ────────────────────────────────────────────────────

let _buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  _buf += chunk;
  const lines = _buf.split('\n');
  _buf = lines.pop();           // keep partial last line
  for (const line of lines) {
    if (!line.trim()) continue;
    (async () => {
      let png;
      try {
        png = await renderScene(JSON.parse(line));
      } catch (e) {
        process.stderr.write(`render error: ${e.stack || e}\n`);
        const zero = Buffer.alloc(4);
        process.stdout.write(zero);
        return;
      }
      const hdr = Buffer.alloc(4);
      hdr.writeUInt32BE(png.length);
      process.stdout.write(hdr);
      process.stdout.write(png);
    })();
  }
});
process.stdin.resume();

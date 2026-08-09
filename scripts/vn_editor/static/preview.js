const Preview = (() => {
  const W = 640, H = 360;
  const FONT = '13px system-ui, sans-serif';
  let _canvas = null, _ctx = null;
  const _cache = {};

  function mount(canvasId) {
    _canvas = document.getElementById(canvasId);
    if (!_canvas) return;
    _canvas.width  = W;
    _canvas.height = H;
    _ctx = _canvas.getContext('2d');
    clear();
  }

  function clear() {
    if (!_ctx) return;
    _ctx.fillStyle = '#111';
    _ctx.fillRect(0, 0, W, H);
    _ctx.fillStyle = '#444';
    _ctx.font = '12px system-ui, sans-serif';
    _ctx.textAlign = 'center';
    _ctx.fillText('No scene selected', W / 2, H / 2);
  }

  function _loadImg(url) {
    if (!url) return Promise.resolve(null);
    if (_cache[url]) return Promise.resolve(_cache[url]);
    return new Promise(resolve => {
      const img = new Image();
      img.onload  = () => { _cache[url] = img; resolve(img); };
      img.onerror = () => resolve(null);
      img.src = url;
    });
  }

  async function drawScene(scene, ctx, w, h, cfgOverride) {
    ctx = ctx || _ctx;
    w   = w   || W;
    h   = h   || H;
    if (!ctx || !scene) { clear(); return; }

    const BOX_H = Math.round(h * 0.36);

    // ── Layout config — resolved first so everything below can use it ──
    const cfg = cfgOverride || (typeof APP !== 'undefined' && APP.state?.config) || {};
    const sc  = w / 640;
    const sdx = (cfg.speaker_dx   || 0) * sc,  sdy = (cfg.speaker_dy   || 0) * sc;
    const tdx = (cfg.text_dx      || 0) * sc,  tdy = (cfg.text_dy      || 0) * sc;
    const charPadTop = (cfg.char_pad_top || 0) * sc;

    // resolve asset URLs
    const bgInfo = scene.bg_key
      ? APP.state.backgrounds.find(b => b.r2_key === scene.bg_key) : null;
    const uiInfo = scene.ui_asset_id
      ? APP.state.uiAssets.find(u => u.id === scene.ui_asset_id) : null;
    const charInfos = (scene.chars || []).map(c => {
      const charId = c.character_id
        ?? (c.type === 'party' ? APP.state.currentStory?.test_party?.[c.slot] : null);
      const ch = charId ? APP.state.characters.find(x => x.character_id === charId) : null;
      return { char: c, url: ch?.image_urls?.[0] ?? null };
    });

    // load all images in parallel
    const [bgImg, uiImg, ...charImgs] = await Promise.all([
      _loadImg(bgInfo?.public_url),
      _loadImg(uiInfo?.public_url),
      ...charInfos.map(c => _loadImg(c.url)),
    ]);

    // ── Background ──
    const bgBlur = scene.bg_blur ?? 0;
    if (bgImg) {
      if (bgBlur > 0) ctx.filter = `blur(${bgBlur * sc}px)`;
      ctx.drawImage(bgImg, 0, 0, w, h);
      if (bgBlur > 0) ctx.filter = 'none';
    } else {
      ctx.fillStyle = '#1a1a2e';
      ctx.fillRect(0, 0, w, h);
      if (scene.bg_key) {
        ctx.fillStyle = '#333';
        ctx.font = `11px system-ui, sans-serif`;
        ctx.textAlign = 'center';
        ctx.fillText(`[bg: ${scene.bg_key}]`, w / 2, (h - BOX_H) / 2);
      }
    }

    // ── Character sprites ──
    const POSITIONS = { L: w*0.12, CL: w*0.30, C: w*0.50, CR: w*0.70, R: w*0.88 };
    const charScale  = cfg.char_scale ?? 1.0;
    const fullAreaH  = h - BOX_H;           // size reference — never shrinks with padding
    const sprBottom  = h - BOX_H;           // sprites always bottom-anchor to dialogue box top
    charInfos.forEach(({ char }, i) => {
      const img = charImgs[i];
      const px  = POSITIONS[char.position] ?? w / 2;
      if (img) {
        const sprH = fullAreaH * charScale;
        const sprW = (img.width / img.height) * sprH;
        ctx.drawImage(img, px - sprW / 2, sprBottom - sprH + charPadTop, sprW, sprH);
      } else {
        _drawCharPlaceholder(ctx, px, sprBottom - 20,
          char.type === 'party' ? `Party[${char.slot}]` : char.character_id || '?', w, h, charPadTop);
      }
    });

    // ── Dialogue box ──
    const scale = scene.ui_scale ?? cfg.ui_scale ?? 1.0;
    let boxY = h - BOX_H;
    if (uiImg) {
      const uiDrawW = w * scale;
      const uiDrawH = (uiImg.height / uiImg.width) * uiDrawW;
      const uiDrawX = (w - uiDrawW) / 2;
      const uiDrawY = h - uiDrawH;
      boxY = uiDrawY;  // align text to actual UI image top edge
      ctx.drawImage(uiImg, uiDrawX, uiDrawY, uiDrawW, uiDrawH);
    } else {
      ctx.fillStyle = 'rgba(10,10,10,0.88)';
      ctx.fillRect(0, boxY, w, BOX_H);
      ctx.fillStyle = '#c0392b';
      ctx.fillRect(0, boxY, w, 3);
    }

    // ── Speaker namebox ──
    const speakerRaw = scene.speaker || 'narrator';
    const speakerPartyCount = (speakerRaw.match(/\{party:\d+\}/g) || []).length;
    const speaker = speakerRaw.replace(/\{party:(\d+)\}/g, (_, n) => {
      const slot = parseInt(n);
      const charEntry = (scene.chars || []).find(c => c.type === 'party' && c.slot === slot);
      const charId = charEntry?.character_id
        ?? ((typeof APP !== 'undefined') && APP.state.currentStory?.test_party?.[slot]);
      if (!charId) return `Party Member ${slot + 1}`;
      const ch = (typeof APP !== 'undefined') && APP.state.characters.find(x => x.character_id === charId);
      if (!ch) return `Party Member ${slot + 1}`;
      if (speakerPartyCount > 1) {
        const parts = ch.name.trim().split(/\s+/);
        return parts.length > 1 ? parts[parts.length - 1] : ch.name;
      }
      return ch.name;
    });
    const tc        = scene.text_color || 'black';
    const speakerFs = Math.round((cfg.speaker_font_size || 13) * sc);
    const textFs    = Math.round((cfg.text_font_size    || 13) * sc);
    if (speaker !== 'narrator') {
      ctx.font = `bold ${speakerFs}px system-ui, sans-serif`;
      const nameW   = ctx.measureText(speaker.toUpperCase()).width + 24 * sc;
      const showBox = cfg.speaker_box !== false;
      const boxColor = cfg.speaker_box_color || (tc === 'pink-outline' ? '#e91e8c' : '#c0392b');
      if (showBox) {
        ctx.fillStyle = boxColor;
        _roundRect(ctx, 16 * sc + sdx, boxY - speakerFs - 8 * sc + sdy, nameW, speakerFs + 8 * sc, 4);
        ctx.fill();
        ctx.fillStyle = '#fff';
      } else {
        ctx.fillStyle = tc === 'black' ? '#111' : '#fff';
      }
      ctx.textAlign = 'left';
      ctx.fillText(speaker.toUpperCase(), 28 * sc + sdx, boxY - 5 * sc + sdy);
    }

    // ── Dialogue text ──
    const textX     = 24 * sc + tdx;
    const textY     = boxY + textFs + 8 * sc + tdy;
    const textAreaW = cfg.text_area_w ? cfg.text_area_w * sc : (w - textX - 24 * sc);
    ctx.font = `${textFs}px system-ui, sans-serif`;
    ctx.textAlign = 'left';
    if (tc === 'pink-outline') {
      ctx.strokeStyle = '#e91e8c';
      ctx.lineWidth = 3;
      ctx.lineJoin = 'round';
      _wrapText(ctx, resolveParty(scene.dialogue_text), textX, textY, textAreaW, textFs + 5, 8, true);
      ctx.lineWidth = 1;
    }
    const resolveParty = t => (t || '').replace(/\{party:(\d+)\}/g, (_, n) => {
      const slot = parseInt(n);
      const charEntry = (scene.chars || []).find(c => c.type === 'party' && c.slot === slot);
      const charId = charEntry?.character_id
        ?? ((typeof APP !== 'undefined') && APP.state.currentStory?.test_party?.[slot]);
      if (!charId) return `Party Member ${slot + 1}`;
      const ch = (typeof APP !== 'undefined') && APP.state.characters.find(x => x.character_id === charId);
      return ch ? ch.name : `Party Member ${slot + 1}`;
    });
    ctx.fillStyle = tc === 'black' ? '#111' : '#fff';
    _wrapText(ctx, resolveParty(scene.dialogue_text), textX, textY, textAreaW, textFs + 5, 8, false);

    // ── Choice indicator / ending badge ──
    if (scene.scene_type === 'choice' && scene.choices?.length) {
      ctx.fillStyle = '#8e44ad99';
      ctx.fillRect(0, h - 28, w, 28);
      ctx.fillStyle = '#c8a8f0';
      ctx.font = `${textFs - 1}px system-ui, sans-serif`;
      ctx.textAlign = 'center';
      ctx.fillText(`▲ ${scene.choices.length} choices`, w / 2, h - 10);
    }
    if (scene.scene_type === 'ending') {
      const colors = { good: '#27ae60', neutral: '#f39c12', bad: '#c0392b' };
      ctx.fillStyle = colors[scene.ending_type] || '#555';
      ctx.font = `bold ${textFs - 1}px system-ui, sans-serif`;
      ctx.textAlign = 'right';
      ctx.fillText(`[${(scene.ending_type || 'ending').toUpperCase()} ENDING]`, w - 16, boxY + textFs + 4);
    }
  }

  function _drawCharPlaceholder(ctx, cx, bottom, label, w, h, padTop) {
    padTop = padTop || 0;
    const charW = Math.round(w * 0.09), charH = Math.round((h * 0.28) - padTop * 0.5);
    ctx.strokeStyle = '#555';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.strokeRect(cx - charW / 2, bottom - charH, charW, charH);
    ctx.setLineDash([]);
    ctx.fillStyle = '#666';
    ctx.font = '9px system-ui, sans-serif';
    ctx.textAlign = 'center';
    const short = label.length > 10 ? label.slice(0, 9) + '…' : label;
    ctx.fillText(short, cx, bottom - charH / 2 + 4);
  }

  function _wrapText(ctx, text, x, y, maxW, lineH, maxLines, stroke) {
    const draw = t => stroke ? ctx.strokeText(t, x, y) : ctx.fillText(t, x, y);
    const words = text.split(' ');
    let line = '', lines = 0;
    for (const word of words) {
      const test = line + (line ? ' ' : '') + word;
      if (ctx.measureText(test).width > maxW && line) {
        if (lines >= maxLines - 1) { stroke ? ctx.strokeText(line + ' …', x, y) : ctx.fillText(line + ' …', x, y); return; }
        draw(line);
        y += lineH; lines++;
        line = word;
      } else { line = test; }
    }
    if (line) draw(line);
  }

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

  return { mount, drawScene, clear, _loadImg, _wrapText, _roundRect };
})();

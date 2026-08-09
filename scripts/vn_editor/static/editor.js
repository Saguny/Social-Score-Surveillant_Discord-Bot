const SceneEditor = (() => {
  const POSITIONS = ['L', 'CL', 'C', 'CR', 'R'];
  let _scene = null, _dirty = false;

  function _uiLabel(id) {
    if (!id) return '';
    const a = APP.state.uiAssets.find(u => u.id === id);
    return a ? a.name : `ui#${id}`;
  }

  function render(scene) {
    _scene = scene ? JSON.parse(JSON.stringify(scene)) : null;
    _dirty = false;
    const panel = document.getElementById('inspector-panel');

    if (!scene) {
      panel.innerHTML = `<div class="insp-empty">
        <div class="insp-empty-icon">↖</div>
        <div>Select or create a scene</div>
      </div>`;
      Preview.clear();
      return;
    }

    panel.innerHTML = `
      <div class="insp-header">
        <span class="insp-scene-id">${esc(scene.id)}</span>
        <div class="insp-header-gap"></div>
        <button class="btn-icon" id="ed-delete" title="Delete scene">🗑</button>
      </div>

      <div class="insp-section">
        <div class="field">
          <label>Label</label>
          <input id="ed-label" value="${esc(scene.label)}" />
        </div>
        <div class="field-row">
          <div class="field" style="flex:1">
            <label>Type</label>
            <select id="ed-type">
              <option value="story"  ${scene.scene_type==='story' ?'selected':''}>Story</option>
              <option value="choice" ${scene.scene_type==='choice'?'selected':''}>Choice</option>
              <option value="ending" ${scene.scene_type==='ending'?'selected':''}>Ending</option>
              <option value="router" ${scene.scene_type==='router'?'selected':''}>Router</option>
            </select>
          </div>
          <div class="field" id="ed-ending-wrap" style="flex:1;${scene.scene_type!=='ending'?'display:none':''}">
            <label>Ending type</label>
            <select id="ed-ending-type">
              <option value="good"    ${scene.ending_type==='good'   ?'selected':''}>Good</option>
              <option value="neutral" ${scene.ending_type==='neutral'?'selected':''}>Neutral</option>
              <option value="bad"     ${scene.ending_type==='bad'    ?'selected':''}>Bad</option>
            </select>
          </div>
        </div>
      </div>

      <div class="insp-section">
        <div class="insp-section-title">Background <span class="z-badge z-badge-0">z0</span></div>
        <div class="field">
          <div class="field-row">
            <input id="ed-bg" value="${esc(scene.bg_key||'')}" placeholder="select a background…" readonly style="cursor:pointer" />
            <button class="btn btn-secondary btn-sm" id="ed-bg-browse">Browse</button>
          </div>
        </div>
        <div class="field-row" style="gap:12px;align-items:center;margin-top:6px">
          <label style="white-space:nowrap;font-size:11px;color:var(--text-2)">Blur</label>
          <input id="ed-bg-blur" type="range" min="0" max="20" step="0.5"
            value="${scene.bg_blur ?? 0}" style="flex:1" />
          <span id="ed-bg-blur-val" style="font-size:11px;width:34px;text-align:right">${(scene.bg_blur ?? 0).toFixed(1)}</span>
        </div>
      </div>

      <div class="insp-section">
        <div class="insp-section-title">Dialogue Box <span class="z-badge z-badge-2">z2</span></div>
        <div class="field">
          <div class="field-row">
            <input id="ed-ui" value="${esc(_uiLabel(scene.ui_asset_id))}" placeholder="select UI asset…" readonly style="cursor:pointer" />
            <button class="btn btn-secondary btn-sm" id="ed-ui-browse">Browse</button>
            ${scene.ui_asset_id ? `<button class="btn-icon" id="ed-ui-clear" title="Clear">✕</button>` : ''}
          </div>
        </div>
        <div class="field-row" style="gap:12px;align-items:center;margin-top:6px">
          <label style="white-space:nowrap;font-size:11px;color:var(--text-2)">Scale</label>
          <input id="ed-ui-scale" type="range" min="0.2" max="2.0" step="0.05"
            value="${scene.ui_scale ?? APP.state.config?.ui_scale ?? 1.0}" style="flex:1" />
          <span id="ed-ui-scale-val" style="font-size:11px;width:34px;text-align:right">${(scene.ui_scale ?? APP.state.config?.ui_scale ?? 1.0).toFixed(2)}</span>
        </div>
        <div class="field" style="margin-top:8px">
          <label>Text color</label>
          <select id="ed-text-color">
            <option value="black"        ${(scene.text_color||'black')==='black'       ?'selected':''}>Black</option>
            <option value="white"        ${scene.text_color==='white'                  ?'selected':''}>White</option>
            <option value="pink-outline" ${scene.text_color==='pink-outline'           ?'selected':''}>White + Pink outline</option>
          </select>
        </div>
      </div>

      <div class="insp-section">
        <div class="insp-section-title">
          Characters
          <button class="btn-xs" id="ed-add-char">+ Add</button>
        </div>
        <div id="ed-chars">${_renderChars(scene.chars)}</div>
      </div>

      <div class="insp-section">
        <div class="insp-section-title">Dialogue</div>
        <div class="field">
          <label>Speaker</label>
          <input id="ed-speaker" value="${esc(scene.speaker)}" placeholder="narrator" list="party-speaker-list" />
          <datalist id="party-speaker-list">
            ${Array.from({length: APP.state.currentStory?.party_size ?? 3}, (_,i) => `<option value="{party:${i}}">Party Member ${i}</option>`).join('')}
          </datalist>
        </div>
        <div class="field">
          <label>Text</label>
          <textarea id="ed-text" rows="4">${esc(scene.dialogue_text)}</textarea>
        </div>
      </div>

      <div class="insp-section" id="ed-flow">
        <div class="insp-section-title">Flow</div>
        ${_renderFlow(scene)}
      </div>

      <div class="insp-save-row">
        <button class="btn btn-primary" id="ed-save">Save</button>
        <span class="save-status" id="ed-status"></span>
      </div>
    `;

    _bind();
    Preview.drawScene(_scene);
  }

  function _renderChars(chars) {
    if (!chars?.length) return '<div class="char-empty">No characters added yet.</div>';
    return chars.map((c, i) => {
      const cur = c.position || 'C';
      const opts = ['L','CL','C','CR','R'].map(p =>
        `<option value="${p}"${p===cur?' selected':''}>${p}</option>`).join('');
      return `
      <div class="char-item">
        <select class="char-pos-sel" data-idx="${i}" style="width:46px;padding:2px 2px;font-size:11px">${opts}</select>
        <span class="char-item-name">${c.type==='party' ? (() => {
          const slot = c.slot ?? 0;
          const cid = APP.state.currentStory?.test_party?.[slot];
          const ch = cid && APP.state.characters.find(x => x.character_id === cid);
          return ch ? `${esc(ch.name)} <span style="opacity:.5;font-size:10px">[slot ${slot}]</span>` : `Party slot ${slot}`;
        })() : esc(c.character_id||'?')}</span>
        <span class="char-item-type">${c.type==='party'?'party':'static'}</span>
        <button class="btn-icon char-rm" data-idx="${i}">✕</button>
      </div>`;
    }).join('');
  }


  function _parseEffects(str) {
    const out = {};
    (str || '').split(',').forEach(part => {
      const t = part.trim();
      if (!t) return;
      let m = t.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(true|false)$/i);
      if (m) { out[m[1]] = m[2].toLowerCase() === 'true'; return; }
      m = t.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*([+-]?\s*\d+(?:\.\d+)?)$/);
      if (m) { out[m[1]] = parseFloat(m[2].replace(/\s+/g, '')); return; }
    });
    return out;
  }

  function _fmtEffects(obj) {
    return Object.entries(obj || {})
      .map(([k, v]) => typeof v === 'boolean' ? `${k}=${v}` : `${k}${v >= 0 ? '+' : ''}${v}`)
      .join(', ');
  }

  function _effectsField(cls, label, val) {
    return `<div>
      <div class="choice-label">${label}</div>
      <input class="${cls}" value="${esc(_fmtEffects(val))}" placeholder="authority+2, flag=true" />
    </div>`;
  }

  function _renderCondition(c, i) {
    const ops = ['>=', '<=', '>', '<', '==', '!='];
    const cur = c.op || '>=';
    const val = c.value === undefined ? 0 : c.value;
    return `<div class="choice-item cond-item" data-idx="${i}">
      <div class="choice-grid">
        <div>
          <div class="choice-label">Variable</div>
          <input class="cond-var" data-f="var" value="${esc(c.var || '')}" placeholder="authority" />
        </div>
        <div>
          <div class="choice-label">Test</div>
          <select class="cond-op" data-f="op">
            ${ops.map(o => `<option value="${o}"${o === cur ? ' selected' : ''}>${o}</option>`).join('')}
          </select>
        </div>
        <div>
          <div class="choice-label">Value</div>
          <input class="cond-val" data-f="value" value="${esc(String(val))}" placeholder="8" />
        </div>
        <div>
          <div class="choice-label">Then go to</div>
          <input class="cond-scene" data-f="scene" value="${esc(c.scene || '')}" placeholder="scene id" />
        </div>
      </div>
      <button class="btn-icon cond-rm" data-idx="${i}" style="position:absolute;top:6px;right:6px">✕</button>
    </div>`;
  }

  function _renderFlow(scene) {
    if (scene.scene_type === 'router') {
      const conds = scene.conditions || [];
      return `
        <div style="font-size:11px;color:var(--text-3);margin-bottom:8px">
          Router — never rendered. The first matching condition wins; otherwise the fallback is used.
        </div>
        <div id="ed-conds">${conds.map(_renderCondition).join('')}</div>
        <button class="btn-xs" id="ed-add-cond" style="margin-top:6px">+ Add condition</button>
        <div class="field" style="margin-top:10px">
          <label>Fallback scene ID</label>
          <input id="ed-next" value="${esc(scene.next_scene||'')}" placeholder="scene id" />
        </div>`;
    }
    if (scene.scene_type === 'choice') {
      const choices = scene.choices || [];
      return `
        <div id="ed-choices">${choices.map(_renderChoice).join('')}</div>
        <button class="btn-xs" id="ed-add-choice" style="margin-top:6px">+ Add choice</button>`;
    }
    if (scene.scene_type !== 'ending') {
      return `<div class="field">
        <label>Next scene ID</label>
        <input id="ed-next" value="${esc(scene.next_scene||'')}" placeholder="scene id" />
      </div>`;
    }
    const yuan   = scene.reward_yuan        != null ? scene.reward_yuan        : '';
    const resets = scene.reward_roll_resets != null ? scene.reward_roll_resets : '';
    return `
      <div style="font-size:11px;color:var(--text-3);margin-bottom:8px">Ending — no next scene.</div>
      <div class="insp-section-title" style="margin-bottom:6px">Reward</div>
      <div class="field-row" style="gap:10px">
        <div class="field" style="flex:1">
          <label>Yuan</label>
          <input id="ed-reward-yuan" type="number" min="0" value="${yuan}" placeholder="default" />
        </div>
        <div class="field" style="flex:1">
          <label>Roll resets</label>
          <input id="ed-reward-resets" type="number" min="0" value="${resets}" placeholder="default" />
        </div>
      </div>
      <div style="font-size:10px;color:var(--text-3);margin-top:4px">Leave blank to use the bot default reward.</div>
    `;
  }

  // Success odds for 1d20 + modifier >= DC. Stat modifier is 0-10 (a party of
  // three average 50-stat characters sits at +5); featured character and faction
  // bonuses add up to +4 more.
  function _dcRange(dc) {
    const pct = mod => Math.round(Math.min(Math.max(21 - dc + mod, 0), 20) / 20 * 100);
    return `avg ${pct(5)}% · strong ${pct(8)}% · +bonuses ${pct(14)}%`;
  }

  function _renderChoice(c, i) {
    const dc = c.difficulty ?? 14;
    return `<div class="choice-item" data-idx="${i}">
      <div class="field"><input class="ci-text" data-f="text" value="${esc(c.text||'')}" placeholder="Choice text…" /></div>
      <div class="choice-grid">
        <div>
          <div class="choice-label">Stat</div>
          <input class="ci-stat" data-f="stat" value="${esc(c.stat||'')}" placeholder="authority…" />
        </div>
        <div>
          <div class="choice-label">Difficulty · 8 trivial · 11 easy · 14 medium · 18 hard · 22 brutal</div>
          <div style="display:flex;align-items:center;gap:6px">
            <input class="ci-dc" data-f="difficulty" type="number" min="1" max="30" value="${dc}" style="width:56px" />
            <span class="ci-pct" style="font-size:11px;color:var(--muted)">${_dcRange(dc)} success</span>
          </div>
        </div>
        <div>
          <div class="choice-label">Pass → scene</div>
          <input class="ci-pass" data-f="pass_scene" value="${esc(c.pass_scene||'')}" placeholder="scene id" />
        </div>
        <div>
          <div class="choice-label">Fail → scene</div>
          <input class="ci-fail" data-f="fail_scene" value="${esc(c.fail_scene||'')}" placeholder="scene id" />
        </div>
        <div>
          <div class="choice-label">Faction bonus</div>
          <input class="ci-faction" data-f="faction" value="${esc(c.faction||'')}" placeholder="reds…" />
        </div>
      </div>
      <div class="choice-grid" style="margin-top:6px">
        ${_effectsField('ci-eff',      'Effects (always)', c.effects)}
        ${_effectsField('ci-eff-pass', 'Effects on pass',  c.pass_effects)}
        ${_effectsField('ci-eff-fail', 'Effects on fail',  c.fail_effects)}
      </div>
      <button class="btn-icon choice-rm" data-idx="${i}" style="position:absolute;top:6px;right:6px">✕</button>
    </div>`;
  }

  function _bind() {
    const live = ['ed-label','ed-speaker','ed-text','ed-next','ed-type','ed-ending-type','ed-text-color'];
    live.forEach(id => {
      document.getElementById(id)?.addEventListener('input', () => { _sync(); _dirty = true; Preview.drawScene(_scene); });
    });

    const scaleEl    = document.getElementById('ed-ui-scale');
    const scaleValEl = document.getElementById('ed-ui-scale-val');
    scaleEl?.addEventListener('input', () => {
      const v = parseFloat(scaleEl.value);
      scaleValEl.textContent = v.toFixed(2);
      _scene.ui_scale = v;
      _dirty = true;
      Preview.drawScene(_scene);
    });

    const blurEl    = document.getElementById('ed-bg-blur');
    const blurValEl = document.getElementById('ed-bg-blur-val');
    blurEl?.addEventListener('input', () => {
      const v = parseFloat(blurEl.value);
      blurValEl.textContent = v.toFixed(1);
      _scene.bg_blur = v;
      _dirty = true;
      Preview.drawScene(_scene);
    });

    document.getElementById('ed-type')?.addEventListener('change', () => {
      const t = document.getElementById('ed-type').value;
      document.getElementById('ed-ending-wrap').style.display = t === 'ending' ? '' : 'none';
      document.getElementById('ed-flow').innerHTML =
        '<div class="insp-section-title">Flow</div>' + _renderFlow({..._scene, scene_type: t});
      _bindFlow();
    });

    _bindChars();
    _bindFlow();

    document.getElementById('ed-add-char')?.addEventListener('click', _openCharPicker);
    document.getElementById('ed-bg-browse')?.addEventListener('click', _openBgPicker);
    document.getElementById('ed-ui-browse')?.addEventListener('click', _openUiPicker);
    document.getElementById('ed-ui-clear')?.addEventListener('click', () => {
      _scene.ui_asset_id = null;
      render(_scene);
    });
    document.getElementById('ed-save')?.addEventListener('click', _save);
    document.getElementById('ed-delete')?.addEventListener('click', _delete);
  }

  function _bindChars() {
    document.querySelectorAll('.char-rm').forEach(btn => {
      btn.addEventListener('click', () => {
        _scene.chars.splice(parseInt(btn.dataset.idx), 1);
        document.getElementById('ed-chars').innerHTML = _renderChars(_scene.chars);
        _bindChars();
        _dirty = true;
        Preview.drawScene(_scene);
      });
    });
    document.querySelectorAll('.char-pos-sel').forEach(sel => {
      sel.addEventListener('change', () => {
        _scene.chars[parseInt(sel.dataset.idx)].position = sel.value;
        _dirty = true;
        Preview.drawScene(_scene);
      });
    });
  }

  function _bindFlow() {
    document.getElementById('ed-add-choice')?.addEventListener('click', () => {
      if (!_scene.choices) _scene.choices = [];
      _scene.choices.push({ text:'', stat:'', difficulty: 14, pass_scene:'', fail_scene:'' });
      document.getElementById('ed-choices').innerHTML = _scene.choices.map(_renderChoice).join('');
      _bindChoices();
      _dirty = true;
    });
    _bindChoices();
  }

  function _bindChoices() {
    document.querySelectorAll('.choice-item:not(.cond-item)').forEach(row => {
      const idx = parseInt(row.dataset.idx);
      row.querySelectorAll('input[data-f]').forEach(inp => {
        inp.addEventListener('input', () => {
          if (!_scene.choices[idx]) _scene.choices[idx] = {};
          const val = inp.dataset.f === 'difficulty' ? (parseInt(inp.value) || 12) : inp.value;
          _scene.choices[idx][inp.dataset.f] = val;
          if (inp.dataset.f === 'difficulty') {
            const dc = Math.min(Math.max(val, 1), 30);
            row.querySelector('.ci-pct').textContent = `${_dcRange(dc)} success`;
          }
          _dirty = true;
        });
      });
      [['.ci-eff', 'effects'], ['.ci-eff-pass', 'pass_effects'], ['.ci-eff-fail', 'fail_effects']]
        .forEach(([sel, field]) => {
          row.querySelector(sel)?.addEventListener('input', e => {
            if (!_scene.choices[idx]) _scene.choices[idx] = {};
            _scene.choices[idx][field] = _parseEffects(e.target.value);
            _dirty = true;
          });
        });
      row.querySelector('.choice-rm')?.addEventListener('click', () => {
        _scene.choices.splice(idx, 1);
        document.getElementById('ed-choices').innerHTML = _scene.choices.map(_renderChoice).join('');
        _bindChoices();
        _dirty = true;
      });
    });
    _bindConditions();
  }

  function _condValue(raw) {
    const t = (raw || '').trim();
    if (/^true$/i.test(t))  return true;
    if (/^false$/i.test(t)) return false;
    const n = parseFloat(t);
    return isNaN(n) ? 0 : n;
  }

  function _redrawConditions() {
    const host = document.getElementById('ed-conds');
    if (host) host.innerHTML = (_scene.conditions || []).map(_renderCondition).join('');
    _bindConditions();
  }

  function _bindConditions() {
    document.getElementById('ed-add-cond')?.addEventListener('click', () => {
      if (!_scene.conditions) _scene.conditions = [];
      _scene.conditions.push({ var: '', op: '>=', value: 0, scene: '' });
      _redrawConditions();
      _dirty = true;
    });
    document.querySelectorAll('.cond-item').forEach(row => {
      const idx = parseInt(row.dataset.idx);
      row.querySelectorAll('[data-f]').forEach(inp => {
        inp.addEventListener('input', () => {
          if (!_scene.conditions[idx]) _scene.conditions[idx] = {};
          const f = inp.dataset.f;
          _scene.conditions[idx][f] = f === 'value' ? _condValue(inp.value) : inp.value;
          _dirty = true;
        });
        inp.addEventListener('change', () => {
          if (!_scene.conditions[idx]) _scene.conditions[idx] = {};
          const f = inp.dataset.f;
          _scene.conditions[idx][f] = f === 'value' ? _condValue(inp.value) : inp.value;
          _dirty = true;
        });
      });
      row.querySelector('.cond-rm')?.addEventListener('click', () => {
        _scene.conditions.splice(idx, 1);
        _redrawConditions();
        _dirty = true;
      });
    });
  }

  function _sync() {
    if (!_scene) return;
    _scene.label         = document.getElementById('ed-label')?.value ?? _scene.label;
    _scene.speaker       = document.getElementById('ed-speaker')?.value ?? 'narrator';
    _scene.dialogue_text = document.getElementById('ed-text')?.value ?? '';
    _scene.next_scene    = document.getElementById('ed-next')?.value || null;
    _scene.scene_type    = document.getElementById('ed-type')?.value ?? _scene.scene_type;
    _scene.ending_type   = document.getElementById('ed-ending-type')?.value || null;
    _scene.text_color    = document.getElementById('ed-text-color')?.value ?? (_scene.text_color || 'black');
    if (!Array.isArray(_scene.conditions)) _scene.conditions = [];
    const _ry = document.getElementById('ed-reward-yuan');
    const _rr = document.getElementById('ed-reward-resets');
    if (_ry) _scene.reward_yuan          = _ry.value   !== '' ? parseInt(_ry.value,   10) : null;
    if (_rr) _scene.reward_roll_resets   = _rr.value   !== '' ? parseInt(_rr.value,   10) : null;
    // ui_asset_id, ui_scale, and bg_blur are set directly on _scene by their own handlers
  }

  async function _openCharPicker() {
    const chars = APP.state.characters;
    const STARS = { legendary:'★★★★★', epic:'★★★★', rare:'★★★', uncommon:'★★', common:'★' };

    const grid = chars.map(c => {
      const img = c.image_urls?.[0];
      const excl = c.vn_exclusive ? ' char-excl' : '';
      const exclLabel = c.vn_exclusive ? '🔒 VN Only' : '🔓 Pool';
      return `<div class="char-card${excl}" data-id="${esc(c.character_id)}" data-name="${esc(c.name)}">
        ${img ? `<img class="char-card-img" src="${esc(img)}" loading="lazy" />` : '<div class="char-card-img-empty">👤</div>'}
        <div class="char-card-name">${esc(c.name)}</div>
        <div class="char-card-meta">${STARS[c.rarity]||''} ${esc(c.faction)}</div>
        <button class="char-excl-btn${c.vn_exclusive ? ' active' : ''}" data-cid="${esc(c.character_id)}" title="Toggle VN-exclusive (removes from roll pool)">${exclLabel}</button>
      </div>`;
    }).join('') || '<div class="empty-state">No characters in DB</div>';

    const html = `
      <div class="modal-field">
        <label>Type</label>
        <select id="cp-type">
          <option value="static">Static character</option>
          <option value="party">Party slot</option>
        </select>
      </div>
      <div id="cp-party-row" class="modal-field" style="display:none">
        <label>Party slot (0–${(APP.state.currentStory?.party_size ?? 5) - 1})</label>
        <input id="cp-slot" type="number" min="0" max="${(APP.state.currentStory?.party_size ?? 5) - 1}" value="0" />
      </div>
      <div class="modal-field">
        <label>Position</label>
        <select id="cp-pos">${POSITIONS.map(p=>`<option>${p}</option>`).join('')}</select>
      </div>
      <div id="cp-char-wrap" class="modal-field">
        <label>Character</label>
        <input id="cp-search" placeholder="Search name or faction…" style="margin-bottom:8px" />
        <div class="char-grid" id="cp-grid">${grid}</div>
      </div>
      <input type="hidden" id="cp-selected" />
    `;

    const ok = await Modal.open('Add Character', html, { wide: true });
    if (!ok) return;

    const type = document.getElementById('cp-type').value;
    const pos  = document.getElementById('cp-pos').value;
    if (type === 'party') {
      const slot = parseInt(document.getElementById('cp-slot').value) || 0;
      _scene.chars.push({ type:'party', slot, position:pos });
    } else {
      const cid = document.getElementById('cp-selected').value;
      if (!cid) return Toast.show('Select a character', 'error');
      _scene.chars.push({ type:'static', character_id:cid, position:pos });
    }
    document.getElementById('ed-chars').innerHTML = _renderChars(_scene.chars);
    _bindChars();
    _dirty = true;
    Preview.drawScene(_scene);
  }

  async function _openUiPicker() {
    const id = await openUiPickerModal();
    if (id != null) {
      _scene.ui_asset_id = id;
      render(_scene);
    }
  }

  async function _openBgPicker() {
    const key = await openBgPickerModal();
    if (key) {
      _scene.bg_key = key;
      document.getElementById('ed-bg').value = key;
      Preview.drawScene(_scene);
    }
  }

  async function _save() {
    if (!_scene) return;
    _sync();
    const statusEl = document.getElementById('ed-status');
    statusEl.textContent = 'Saving…'; statusEl.className = 'save-status';
    try {
      const updated = await API.updateScene(APP.state.currentStory.id, _scene.id, _scene);
      APP.state.scenes = APP.state.scenes.map(s => s.id === updated.id ? updated : s);
      APP.state.currentScene = updated;
      SceneTree.updateScene(updated);
      _dirty = false;
      statusEl.textContent = 'Saved ✓'; statusEl.className = 'save-status ok';
      setTimeout(() => statusEl.textContent = '', 2500);
      Toast.show('Saved');
    } catch (e) {
      statusEl.textContent = 'Error'; statusEl.className = 'save-status';
      Toast.show(e.message, 'error');
    }
  }

  async function _delete() {
    if (!_scene || !confirm(`Delete scene [${_scene.id}]? This cannot be undone.`)) return;
    try {
      await API.deleteScene(APP.state.currentStory.id, _scene.id);
      APP.state.scenes = APP.state.scenes.filter(s => s.id !== _scene.id);
      SceneTree.removeScene(_scene.id);
      render(null);
      Toast.show('Scene deleted');
    } catch (e) { Toast.show(e.message, 'error'); }
  }

  return { render };
})();

function esc(str) {
  if (str == null) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Shared picker modals (used by SceneEditor and MultiEditor) ────────────────

async function openBgPickerModal() {
  const bgs = APP.state.backgrounds;
  const grid = bgs.map(b => `
    <div class="bg-card" data-key="${esc(b.r2_key)}" data-url="${esc(b.public_url)}">
      <img src="${esc(b.public_url)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'" />
      <div class="bg-card-no-img" style="display:none">No preview</div>
      <div class="bg-card-footer">
        <div class="bg-card-name">${esc(b.name)}</div>
        <div class="bg-card-meta">
          <span>${esc(b.category)}</span>
          <span class="z-badge z-badge-${b.z_layer}">z${b.z_layer}</span>
        </div>
      </div>
    </div>`).join('') || '<div class="empty-state">No backgrounds uploaded yet.</div>';

  const html = `<div class="bg-grid" id="bg-grid">${grid}</div><input type="hidden" id="bg-selected-key" />`;
  const ok = await Modal.open('Choose Background', html, { wide: true });
  if (!ok) return null;
  return document.getElementById('bg-selected-key')?.value || null;
}

async function openUiPickerModal() {
  const assets = APP.state.uiAssets;
  const grid = assets.map(u => `
    <div class="bg-card" data-id="${u.id}" data-name="${esc(u.name)}">
      <img src="${esc(u.public_url)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'" />
      <div class="bg-card-no-img" style="display:none">No preview</div>
      <div class="bg-card-footer">
        <div class="bg-card-name">${esc(u.name)}</div>
        <div class="bg-card-meta"><span>${esc(u.category)}</span><span class="z-badge z-badge-2">z2</span></div>
      </div>
    </div>`).join('') || '<div class="empty-state">No UI assets uploaded yet.</div>';

  const html = `<div class="bg-grid" id="ui-pick-grid">${grid}</div><input type="hidden" id="ui-selected-id" />`;
  const ok = await Modal.open('Choose Dialogue Box', html, { wide: true });
  if (!ok) return null;
  const val = document.getElementById('ui-selected-id')?.value;
  return val ? parseInt(val) : null;
}

// ── Multi-scene editor (shown when marquee-selecting scenes in tree.js) ───────

const MultiEditor = (() => {
  let _sceneIds = [];
  let _newBgKey = undefined;  // undefined = unchanged; '' = clear
  let _newUiId  = undefined;  // undefined = unchanged; 0 = clear

  function render(ids) {
    _sceneIds = ids;
    _newBgKey = undefined;
    _newUiId  = undefined;

    const panel = document.getElementById('inspector-panel');
    if (!ids.length) {
      panel.innerHTML = `<div class="insp-empty">
        <div class="insp-empty-icon">◻</div>
        <div>No scenes in selection</div>
      </div>`;
      return;
    }

    panel.innerHTML = `
      <div class="insp-header">
        <span class="insp-scene-id">${ids.length} scenes selected</span>
      </div>
      <div class="insp-section">
        <div class="insp-section-title">Apply to all selected scenes</div>
        <div class="field">
          <label>Background</label>
          <div class="field-row">
            <input id="me-bg" value="" placeholder="— unchanged —" readonly style="cursor:pointer" />
            <button class="btn btn-secondary btn-sm" id="me-bg-browse">Browse</button>
            <button class="btn-icon" id="me-bg-clear" title="Clear background from all">✕</button>
          </div>
        </div>
        <div class="field" style="margin-top:8px">
          <label>Dialogue Box</label>
          <div class="field-row">
            <input id="me-ui" value="" placeholder="— unchanged —" readonly style="cursor:pointer" />
            <button class="btn btn-secondary btn-sm" id="me-ui-browse">Browse</button>
            <button class="btn-icon" id="me-ui-clear" title="Clear UI asset from all">✕</button>
          </div>
        </div>
      </div>
      <div class="insp-save-row">
        <button class="btn btn-primary" id="me-apply">Apply to ${ids.length} scenes</button>
        <span class="save-status" id="me-status"></span>
      </div>
    `;

    document.getElementById('me-bg-browse')?.addEventListener('click', async () => {
      const key = await openBgPickerModal();
      if (key) { _newBgKey = key; document.getElementById('me-bg').value = key; }
    });

    document.getElementById('me-bg-clear')?.addEventListener('click', () => {
      _newBgKey = '';
      document.getElementById('me-bg').value = '(clear)';
    });

    document.getElementById('me-ui-browse')?.addEventListener('click', async () => {
      const id = await openUiPickerModal();
      if (id != null) {
        _newUiId = id;
        const asset = APP.state.uiAssets.find(u => u.id === id);
        document.getElementById('me-ui').value = asset ? asset.name : `ui#${id}`;
      }
    });

    document.getElementById('me-ui-clear')?.addEventListener('click', () => {
      _newUiId = 0;
      document.getElementById('me-ui').value = '(clear)';
    });

    document.getElementById('me-apply')?.addEventListener('click', async () => {
      if (_newBgKey === undefined && _newUiId === undefined) {
        Toast.show('Pick a background or dialogue box to apply', 'error');
        return;
      }
      const statusEl = document.getElementById('me-status');
      statusEl.textContent = 'Applying…';
      let done = 0;
      for (const sid of _sceneIds) {
        const scene = APP.state.scenes.find(s => s.id === sid);
        if (!scene) continue;
        const updates = { ...scene };
        if (_newBgKey !== undefined) updates.bg_key = _newBgKey || null;
        if (_newUiId  !== undefined) updates.ui_asset_id = _newUiId || null;
        try {
          const updated = await API.updateScene(APP.state.currentStory.id, sid, updates);
          APP.state.scenes = APP.state.scenes.map(s => s.id === updated.id ? updated : s);
          SceneTree.updateScene(updated);
          done++;
        } catch (e) {
          Toast.show(`Error on ${sid}: ${e.message}`, 'error');
        }
      }
      statusEl.textContent = `${done} saved ✓`;
      setTimeout(() => statusEl.textContent = '', 2500);
      Toast.show(`Applied to ${done} scene${done !== 1 ? 's' : ''}`);
    });
  }

  return { render };
})();

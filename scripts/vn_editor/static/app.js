const APP = {
  state: {
    arcs:         [],
    stories:      [],
    scenes:       [],
    characters:   [],
    backgrounds:  [],
    uiAssets:     [],
    config:       { speaker_dx:0, speaker_dy:0, text_dx:0, text_dy:0, speaker_box:true, speaker_box_color:'#c0392b', speaker_font_size:13, text_font_size:13, ui_scale:1.0, char_pad_top:0, char_scale:1.0, text_area_w:0 },
    currentStory: null,
    currentScene: null,
  },

  async init() {
    SceneTree.mount('tree-canvas');
    Preview.mount('preview-canvas');
    _bindNav();
    await _loadAll();
    StoriesPanel.render();
    SceneEditor.render(null);
    _showTab('tab-stories');
  },

  async selectStory(storyId) {
    const story = APP.state.stories.find(s => s.id === storyId);
    if (!story) return;
    APP.state.currentStory = story;
    APP.state.currentScene = null;
    APP.state.scenes = await API.getScenes(storyId);
    StoriesPanel.render();
    SceneTree.load(storyId, APP.state.scenes);
    SceneTree.fitAll();
    SceneEditor.render(null);
    document.getElementById('tree-story-title').textContent = story.title;
    _setBreadcrumb(story.title);
    _showTab('tab-tree');
  },

  selectScene(sceneId) {
    const scene = APP.state.scenes.find(s => s.id === sceneId);
    if (!scene) return;
    APP.state.currentScene = scene;
    SceneTree.setSelected(sceneId);
    SceneEditor.render(scene);
  },

  onMultiSelect(ids) {
    APP.state.currentScene = null;
    SceneTree.setSelected(null);
    MultiEditor.render(ids);
  },
};

async function _loadAll() {
  const [arcs, stories, characters, backgrounds, uiAssets, config] = await Promise.all([
    API.getArcs(),
    API.getStories(),
    API.getCharacters(),
    API.getBackgrounds(),
    API.getUIAssets(),
    API.getConfig().catch(() => ({ speaker_dx:0, speaker_dy:0, text_dx:0, text_dy:0, speaker_box:true, speaker_box_color:'#c0392b', speaker_font_size:13, text_font_size:13, ui_scale:1.0, char_pad_top:0, char_scale:1.0, text_area_w:0 })),
  ]);
  Object.assign(APP.state, { arcs, stories, characters, backgrounds, uiAssets, config });
}

function _setBreadcrumb(storyTitle) {
  const el = document.getElementById('topbar-breadcrumb');
  if (storyTitle) {
    el.innerHTML = `<span>Stories</span><span class="sep">/</span><span class="crumb-active">${esc(storyTitle)}</span>`;
  } else {
    el.innerHTML = `<span>Stories</span>`;
  }
}

function _showTab(tabId) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById(tabId)?.classList.add('active');
}

function _bindNav() {
  document.getElementById('btn-new-story')?.addEventListener('click',
    () => StoriesPanel.openNewStoryModal());
  document.getElementById('btn-new-arc')?.addEventListener('click',
    () => StoriesPanel.openArcModal());
  document.getElementById('btn-import-story')?.addEventListener('click', importEpisode);
  document.getElementById('btn-back-stories')?.addEventListener('click', () => {
    APP.state.currentStory = null;
    _setBreadcrumb(null);
    StoriesPanel.render();
    SceneEditor.render(null);
    _showTab('tab-stories');
  });
  document.getElementById('btn-config')?.addEventListener('click', () => _openConfigModal());
  document.getElementById('btn-fit-tree')?.addEventListener('click', () => SceneTree.fitAll());
  document.getElementById('btn-play')?.addEventListener('click', () => PlayMode.open());
  document.getElementById('btn-new-scene')?.addEventListener('click', async () => {
    const sid = APP.state.currentStory?.id;
    if (!sid) return;
    const prevId = APP.state.currentScene?.id;
    const id = `s${Date.now()}`;
    // read prev fresh from scenes array so we always have post-save data
    const prev = prevId ? APP.state.scenes.find(s => s.id === prevId) : null;
    const base = prev ? {
      scene_type:    prev.scene_type === 'ending' ? 'story' : prev.scene_type,
      bg_key:        prev.bg_key,
      ui_asset_id:   prev.ui_asset_id,
      ui_scale:      prev.ui_scale,
      bg_blur:       prev.bg_blur,
      text_color:    prev.text_color,
      chars:         JSON.parse(JSON.stringify(prev.chars || [])),
      speaker:       prev.speaker,
    } : {};
    const sc = await API.createScene(sid, {
      ...base, id, label: 'New Scene',
      node_x: prev ? prev.node_x : 80,
      node_y: prev ? prev.node_y + 120 : 60,
    });
    APP.state.scenes.push(sc);
    SceneTree.addScene(sc);
    // re-read prev after the async create in case a concurrent save landed during the await
    const freshPrev = prevId ? APP.state.scenes.find(s => s.id === prevId) : null;
    const prevNextValid = freshPrev?.next_scene && APP.state.scenes.some(s => s.id === freshPrev.next_scene);
    if (freshPrev && !prevNextValid && freshPrev.scene_type === 'story') {
      const updated = await API.updateScene(sid, freshPrev.id, { ...freshPrev, next_scene: sc.id });
      APP.state.scenes = APP.state.scenes.map(s => s.id === updated.id ? updated : s);
      SceneTree.updateScene(updated);
    }
    APP.selectScene(sc.id);
  });
  document.getElementById('btn-story-settings')?.addEventListener('click',
    () => _openStorySettings());
  document.getElementById('btn-assets')?.addEventListener('click',
    () => _openAssetsModal());
}

// ── Story settings ──────────────────────────────────────────────────────────
async function _openStorySettings() {
  const story = APP.state.currentStory;
  if (!story) return;
  const arcOptions = APP.state.arcs.map(a =>
    `<option value="${a.id}" ${story.arc_id===a.id?'selected':''}>${esc(a.title)}</option>`
  ).join('');

  const testParty = Array.isArray(story.test_party) ? story.test_party : [];
  const partySlots = Array.from({ length: story.party_size }, (_, i) => {
    const sel = testParty[i] || '';
    return `<div class="modal-field" style="display:flex;gap:6px;align-items:center">
      <label style="min-width:60px">Slot ${i}</label>
      <select id="ss-tp-${i}" style="flex:1"><option value="">— none —</option>${
        APP.state.characters.map(c =>
          `<option value="${c.character_id}"${c.character_id===sel?' selected':''}>${esc(c.name)}</option>`
        ).join('')
      }</select>
    </div>`;
  }).join('');

  const html = `
    <div class="modal-field"><label>Title</label>
      <input id="ss-title" value="${esc(story.title)}" /></div>
    <div class="modal-field"><label>Status</label>
      <select id="ss-status">
        <option value="draft"     ${story.status==='draft'    ?'selected':''}>Draft</option>
        <option value="published" ${story.status==='published'?'selected':''}>Published</option>
        <option value="archived"  ${story.status==='archived' ?'selected':''}>Archived</option>
      </select></div>
    <div class="modal-field"><label>Arc</label>
      <select id="ss-arc"><option value="">— none —</option>${arcOptions}</select></div>
    <div class="modal-field"><label>Episode #</label>
      <input id="ss-episode" type="number" min="1" value="${story.episode_number ?? 1}" /></div>
    <div class="modal-field"><label>Party size</label>
      <input id="ss-party" type="number" min="1" max="5" value="${story.party_size}" /></div>
    <div class="modal-field"><label>Entry scene</label>
      <input id="ss-entry" value="${esc(story.entry_scene)}" /></div>
    <div class="modal-field"><label>Description</label>
      <textarea id="ss-desc" rows="2">${esc(story.description||'')}</textarea></div>
    <hr class="modal-sep" />
    <div class="modal-field"><label>Featured character</label>
      <select id="ss-featured">
        <option value="">— none —</option>
        ${APP.state.characters.map(c =>
          `<option value="${esc(c.character_id)}"${c.character_id===story.featured_char_id?' selected':''}>${esc(c.name)}</option>`
        ).join('')}
      </select>
      <div class="modal-hint">Having them in your party grants a roll bonus for this episode.</div></div>
    <div class="modal-field"><label>Faction bonus</label>
      <select id="ss-faction">
        <option value="">— none —</option>
        ${['reds','capitalists','conquerors','strongmen','philosophers','icons','wildcards'].map(f =>
          `<option value="${f}"${f===story.faction?' selected':''}>${f}</option>`
        ).join('')}
      </select>
      <div class="modal-hint">Two or more party members of this faction grant a roll bonus.</div></div>
    <hr class="modal-sep" />
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <label style="font-weight:600">Test Party</label>
      <button class="btn btn-sm" id="ss-tp-rand" type="button">Randomize</button>
    </div>
    ${partySlots}
    <hr class="modal-sep" />
    <div style="display:flex;gap:8px">
      <button class="btn" id="ss-export" type="button">Export episode</button>
      <button class="btn btn-danger-outline" id="ss-delete">Delete story</button>
    </div>
  `;

  const _ssPromise = Modal.open(`Story Settings`, html);
  document.getElementById('ss-export')?.addEventListener('click', () => exportEpisode(story.id));
  document.getElementById('ss-tp-rand')?.addEventListener('click', () => {
    const size = parseInt(document.getElementById('ss-party').value) || story.party_size;
    const ids = APP.state.characters.map(c => c.character_id);
    const shuffled = [...ids].sort(() => Math.random() - 0.5).slice(0, size);
    for (let i = 0; i < size; i++) {
      const el = document.getElementById(`ss-tp-${i}`);
      if (el) el.value = shuffled[i] || '';
    }
  });
  const ok = await _ssPromise;
  if (!ok) return;

  try {
    const partySize = parseInt(document.getElementById('ss-party').value) || 3;
    const newTestParty = Array.from({ length: partySize }, (_, i) =>
      document.getElementById(`ss-tp-${i}`)?.value || '');
    const updated = await API.updateStory(story.id, {
      title:          document.getElementById('ss-title').value.trim(),
      status:         document.getElementById('ss-status').value,
      arc_id:         document.getElementById('ss-arc').value ? parseInt(document.getElementById('ss-arc').value) : null,
      party_size:     partySize,
      episode_number: parseInt(document.getElementById('ss-episode').value) || 1,
      entry_scene:    document.getElementById('ss-entry').value.trim() || 's1',
      description:    document.getElementById('ss-desc').value.trim(),
      test_party:     newTestParty,
      featured_char_id: document.getElementById('ss-featured').value || null,
      faction:          document.getElementById('ss-faction').value || null,
    });
    APP.state.stories = APP.state.stories.map(s => s.id === story.id ? updated : s);
    APP.state.currentStory = updated;
    document.getElementById('tree-story-title').textContent = updated.title;
    _setBreadcrumb(updated.title);
    StoriesPanel.render();
    Toast.show('Saved');
  } catch (e) { Toast.show(e.message, 'error'); }
}

// ── Global config modal ──────────────────────────────────────────────────────
async function _openConfigModal() {
  const cfg = APP.state.config;

  const bgOptions = APP.state.backgrounds.map(b =>
    `<option value="${b.r2_key}">${esc(b.name)}</option>`).join('');
  const uiOptions = APP.state.uiAssets.map(u =>
    `<option value="${u.id}">${esc(u.name)}</option>`).join('');

  const curBg = APP.state.currentScene?.bg_key || '';
  const curUi = APP.state.currentScene?.ui_asset_id || '';
  const curSpeaker = APP.state.currentScene?.speaker || 'Zhang Wei';
  const curText = APP.state.currentScene?.dialogue_text || 'The Long March has begun. We move at dawn.';
  const curScale = APP.state.currentScene?.ui_scale ?? APP.state.config?.ui_scale ?? 1.0;
  const curTc = APP.state.currentScene?.text_color || 'black';

  const html = `
    <div style="display:flex;gap:20px;align-items:flex-start">

      <!-- Left: controls -->
      <div style="flex:0 0 220px">
        <div class="insp-section-title" style="margin-bottom:8px">Speaker name</div>
        <div class="field-row" style="gap:6px;margin-bottom:6px">
          <label style="width:14px;font-size:11px;color:var(--text-2)">X</label>
          <input id="cfg-sx" type="number" value="${cfg.speaker_dx}" style="width:62px" />
          <label style="width:14px;font-size:11px;color:var(--text-2)">Y</label>
          <input id="cfg-sy" type="number" value="${cfg.speaker_dy}" style="width:62px" />
        </div>
        <div class="field-row" style="gap:6px;align-items:center;margin-top:6px">
          <label style="font-size:11px;color:var(--text-2);white-space:nowrap">Font size</label>
          <input id="cfg-sfs" type="number" min="6" max="48" value="${cfg.speaker_font_size ?? 13}" style="width:52px" />
          <span style="font-size:10px;color:var(--text-3)">px</span>
        </div>
        <div class="field-row" style="gap:6px;align-items:center;margin-top:6px">
          <input id="cfg-sbox" type="checkbox" ${cfg.speaker_box !== false ? 'checked' : ''} />
          <label for="cfg-sbox" style="font-size:11px;color:var(--text-2)">Show name box</label>
        </div>
        <div class="field-row" style="gap:6px;align-items:center;margin-top:4px">
          <label style="font-size:11px;color:var(--text-2);white-space:nowrap">Box color</label>
          <input id="cfg-scolor" type="color" value="${cfg.speaker_box_color || '#c0392b'}" style="width:40px;height:22px;padding:1px;border-radius:3px" />
        </div>

        <div class="insp-section-title" style="margin:14px 0 8px">Dialogue text</div>
        <div class="field-row" style="gap:6px;align-items:center;margin-bottom:6px">
          <label style="font-size:11px;color:var(--text-2);white-space:nowrap">Wrap width</label>
          <input id="cfg-taw" type="number" min="0" max="620" value="${cfg.text_area_w ?? 0}" style="width:62px" />
          <span style="font-size:10px;color:var(--text-3)">px (0=auto)</span>
        </div>
        <div class="field-row" style="gap:6px">
          <label style="width:14px;font-size:11px;color:var(--text-2)">X</label>
          <input id="cfg-tx" type="number" value="${cfg.text_dx}" style="width:62px" />
          <label style="width:14px;font-size:11px;color:var(--text-2)">Y</label>
          <input id="cfg-ty" type="number" value="${cfg.text_dy}" style="width:62px" />
        </div>
        <div class="field-row" style="gap:6px;align-items:center;margin-top:6px">
          <label style="font-size:11px;color:var(--text-2);white-space:nowrap">Font size</label>
          <input id="cfg-tfs" type="number" min="6" max="48" value="${cfg.text_font_size ?? 13}" style="width:52px" />
          <span style="font-size:10px;color:var(--text-3)">px</span>
        </div>

        <div style="margin-top:12px;font-size:10px;color:var(--text-3)">
          Offsets in px (640×360 ref).<br>+X = right · +Y = down
        </div>
        <button class="btn btn-secondary btn-sm" id="cfg-reset" style="margin-top:10px">Reset</button>
      </div>

      <!-- Right: sample inputs + preview -->
      <div style="flex:1;min-width:0">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
          <div class="field">
            <label>Background</label>
            <select id="cfg-bg"><option value="">— none —</option>${bgOptions}</select>
          </div>
          <div class="field">
            <label>UI asset</label>
            <select id="cfg-ui"><option value="">— none —</option>${uiOptions}</select>
          </div>
          <div class="field">
            <label>Speaker name</label>
            <input id="cfg-speaker" value="${esc(curSpeaker)}" />
          </div>
          <div class="field">
            <label>Text color</label>
            <select id="cfg-tc">
              <option value="black"        ${curTc==='black'       ?'selected':''}>Black</option>
              <option value="white"        ${curTc==='white'       ?'selected':''}>White</option>
              <option value="pink-outline" ${curTc==='pink-outline'?'selected':''}>White + Pink outline</option>
            </select>
          </div>
          <div class="field" style="grid-column:1/-1">
            <label>Sample dialogue text</label>
            <textarea id="cfg-text" rows="2">${esc(curText)}</textarea>
          </div>
          <div class="field" style="grid-column:1/-1">
            <label>UI scale</label>
            <div class="field-row" style="gap:8px;align-items:center">
              <input id="cfg-uiscale" type="range" min="0.2" max="2.0" step="0.05"
                value="${curScale}" style="flex:1" />
              <span id="cfg-uiscale-val" style="font-size:11px;width:34px;text-align:right">${curScale.toFixed(2)}</span>
            </div>
          </div>
          <div class="field" style="grid-column:1/-1">
            <label>Character padding from top (px)</label>
            <div class="field-row" style="gap:8px;align-items:center">
              <input id="cfg-charpad" type="range" min="0" max="200" step="1"
                value="${cfg.char_pad_top ?? 0}" style="flex:1" />
              <span id="cfg-charpad-val" style="font-size:11px;width:34px;text-align:right">${cfg.char_pad_top ?? 0}</span>
            </div>
          </div>
          <div class="field" style="grid-column:1/-1">
            <label>Character size</label>
            <div class="field-row" style="gap:8px;align-items:center">
              <input id="cfg-charscale" type="range" min="0.1" max="2.0" step="0.05"
                value="${cfg.char_scale ?? 1.0}" style="flex:1" />
              <span id="cfg-charscale-val" style="font-size:11px;width:34px;text-align:right">${(cfg.char_scale ?? 1.0).toFixed(2)}</span>
            </div>
          </div>
        </div>
        <div style="font-size:11px;color:var(--text-2);margin-bottom:4px">Preview</div>
        <canvas id="cfg-preview" style="width:100%;border-radius:4px;background:#111;display:block"></canvas>
      </div>

    </div>
  `;

  const ok = await Modal.open('Text Layout Config', html, { wide: true });
  if (!ok) return;

  const newCfg = {
    speaker_dx:        parseInt(document.getElementById('cfg-sx').value)    || 0,
    speaker_dy:        parseInt(document.getElementById('cfg-sy').value)    || 0,
    text_dx:           parseInt(document.getElementById('cfg-tx').value)    || 0,
    text_dy:           parseInt(document.getElementById('cfg-ty').value)    || 0,
    speaker_box:       document.getElementById('cfg-sbox').checked,
    speaker_box_color: document.getElementById('cfg-scolor').value,
    speaker_font_size: parseInt(document.getElementById('cfg-sfs').value)   || 13,
    text_font_size:    parseInt(document.getElementById('cfg-tfs').value)   || 13,
    ui_scale:          parseFloat(document.getElementById('cfg-uiscale').value) || 1.0,
    char_pad_top:      parseInt(document.getElementById('cfg-charpad').value)    || 0,
    char_scale:        parseFloat(document.getElementById('cfg-charscale').value) || 1.0,
    text_area_w:       parseInt(document.getElementById('cfg-taw').value) || 0,
  };
  try {
    APP.state.config = await API.saveConfig(newCfg);
    if (APP.state.currentScene) Preview.drawScene(APP.state.currentScene);
    Toast.show('Config saved');
  } catch (e) { Toast.show(e.message, 'error'); }
}

function _initConfigPreview() {
  const canvas = document.getElementById('cfg-preview');
  if (!canvas) return;
  const W = 480, H = 270;
  canvas.width = W; canvas.height = H;

  function readCfg() {
    return {
      speaker_dx:        parseInt(document.getElementById('cfg-sx')?.value)    || 0,
      speaker_dy:        parseInt(document.getElementById('cfg-sy')?.value)    || 0,
      text_dx:           parseInt(document.getElementById('cfg-tx')?.value)    || 0,
      text_dy:           parseInt(document.getElementById('cfg-ty')?.value)    || 0,
      speaker_box:       document.getElementById('cfg-sbox')?.checked ?? true,
      speaker_box_color: document.getElementById('cfg-scolor')?.value || '#c0392b',
      speaker_font_size: parseInt(document.getElementById('cfg-sfs')?.value)   || 13,
      text_font_size:    parseInt(document.getElementById('cfg-tfs')?.value)   || 13,
      ui_scale:          parseFloat(document.getElementById('cfg-uiscale')?.value) || 1.0,
      char_pad_top:      parseInt(document.getElementById('cfg-charpad')?.value)    || 0,
      char_scale:        parseFloat(document.getElementById('cfg-charscale')?.value) || 1.0,
      text_area_w:       parseInt(document.getElementById('cfg-taw')?.value) || 0,
    };
  }

  function readScene() {
    const bgKey = document.getElementById('cfg-bg')?.value   || null;
    const uiVal = document.getElementById('cfg-ui')?.value   || null;
    const uiId  = uiVal ? parseInt(uiVal) : null;
    const scale = parseFloat(document.getElementById('cfg-uiscale')?.value ?? 1.0);
    return {
      bg_key:        bgKey,
      ui_asset_id:   uiId,
      ui_scale:      scale,
      chars:         [{ type: 'static', character_id: '__mockup__', position: 'C' }],
      speaker:       document.getElementById('cfg-speaker')?.value || 'narrator',
      text_color:    document.getElementById('cfg-tc')?.value      || 'black',
      dialogue_text: document.getElementById('cfg-text')?.value    || '',
      scene_type:    'story',
    };
  }

  function redraw() {
    // Pass cfg directly — avoids async race with global swap
    Preview.drawScene(readScene(), canvas.getContext('2d'), W, H, readCfg());
  }

  // text/number/color inputs → 'input'; checkboxes/selects → 'change'
  const inputIds  = ['cfg-sx','cfg-sy','cfg-tx','cfg-ty','cfg-scolor','cfg-speaker','cfg-text','cfg-uiscale','cfg-sfs','cfg-tfs','cfg-charpad','cfg-charscale','cfg-taw'];
  const changeIds = ['cfg-sbox','cfg-bg','cfg-ui','cfg-tc'];
  inputIds .forEach(id => document.getElementById(id)?.addEventListener('input',  redraw));
  changeIds.forEach(id => document.getElementById(id)?.addEventListener('change', redraw));

  document.getElementById('cfg-uiscale')?.addEventListener('input', () => {
    const v = parseFloat(document.getElementById('cfg-uiscale').value);
    const el = document.getElementById('cfg-uiscale-val');
    if (el) el.textContent = v.toFixed(2);
  });

  document.getElementById('cfg-charpad')?.addEventListener('input', () => {
    const v = parseInt(document.getElementById('cfg-charpad').value);
    const el = document.getElementById('cfg-charpad-val');
    if (el) el.textContent = v;
  });

  document.getElementById('cfg-charscale')?.addEventListener('input', () => {
    const v = parseFloat(document.getElementById('cfg-charscale').value);
    const el = document.getElementById('cfg-charscale-val');
    if (el) el.textContent = v.toFixed(2);
  });

  document.getElementById('cfg-reset')?.addEventListener('click', () => {
    document.getElementById('cfg-sx').value     = 0;
    document.getElementById('cfg-sy').value     = 0;
    document.getElementById('cfg-tx').value     = 0;
    document.getElementById('cfg-ty').value     = 0;
    document.getElementById('cfg-sbox').checked  = true;
    document.getElementById('cfg-scolor').value  = '#c0392b';
    document.getElementById('cfg-charpad').value = 0;
    document.getElementById('cfg-charpad-val').textContent = 0;
    document.getElementById('cfg-charscale').value = 1.0;
    document.getElementById('cfg-charscale-val').textContent = '1.00';
    redraw();
  });

  // pre-select current scene's assets
  const curScene = APP.state.currentScene;
  if (curScene?.bg_key)      { const el = document.getElementById('cfg-bg');      if (el) el.value = curScene.bg_key; }
  if (curScene?.ui_asset_id) { const el = document.getElementById('cfg-ui');      if (el) el.value = String(curScene.ui_asset_id); }
  if (curScene?.ui_scale != null) {
    const el  = document.getElementById('cfg-uiscale');
    const vel = document.getElementById('cfg-uiscale-val');
    if (el)  el.value      = curScene.ui_scale;
    if (vel) vel.textContent = curScene.ui_scale.toFixed(2);
  }

  redraw();
}

// ── Assets modal (BG + UI upload/manage) ────────────────────────────────────
async function _openAssetsModal() {
  function buildBgGrid() {
    return APP.state.backgrounds.map(b => `
      <div class="bg-card" data-id="${b.id}">
        <img src="${esc(b.public_url)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'" />
        <div class="bg-card-no-img" style="display:none">No preview</div>
        <div class="bg-card-footer">
          <div class="bg-card-name">${esc(b.name)}</div>
          <div class="bg-card-meta">
            <span>${esc(b.category)}</span>
            <span class="z-badge z-badge-0">z0 · BG</span>
          </div>
        </div>
        <button class="bg-card-del" data-id="${b.id}">✕</button>
      </div>`).join('') || '<div class="empty-state">No backgrounds yet.</div>';
  }

  function buildUiGrid() {
    return APP.state.uiAssets.map(u => `
      <div class="bg-card" data-id="${u.id}">
        <img src="${esc(u.public_url)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'" />
        <div class="bg-card-no-img" style="display:none">No preview</div>
        <div class="bg-card-footer">
          <div class="bg-card-name">${esc(u.name)}</div>
          <div class="bg-card-meta">
            <span>${esc(u.category)}</span>
            <span class="z-badge z-badge-2">z2 · UI</span>
          </div>
        </div>
        <button class="bg-card-del" data-id="${u.id}" data-ui="1">✕</button>
      </div>`).join('') || '<div class="empty-state">No UI assets yet.</div>';
  }

  const html = `
    <div class="asset-tabs">
      <button class="asset-tab active" id="atab-bg">Backgrounds <span class="z-badge z-badge-0">z0</span></button>
      <button class="asset-tab" id="atab-ui">UI Assets <span class="z-badge z-badge-2">z2</span></button>
    </div>

    <!-- BG panel -->
    <div id="apanel-bg">
      <div class="upload-zone" id="bg-upload-zone">
        <div class="upload-zone-icon">🖼</div>
        <div class="upload-zone-text">Drop background image here or click to upload</div>
        <div class="upload-zone-sub">PNG, JPG, WEBP · Goes to R2 vn/bg/</div>
        <input type="file" id="bg-file-input" accept="image/*" />
      </div>
      <div class="bg-grid" id="bg-asset-grid">${buildBgGrid()}</div>
    </div>

    <!-- UI panel -->
    <div id="apanel-ui" style="display:none">
      <div class="upload-zone" id="ui-upload-zone">
        <div class="upload-zone-icon">🪟</div>
        <div class="upload-zone-text">Drop UI element here or click to upload</div>
        <div class="upload-zone-sub">PNG with transparency · Goes to R2 vn/ui/</div>
        <input type="file" id="ui-file-input" accept="image/*" />
      </div>
      <div class="bg-grid" id="ui-asset-grid">${buildUiGrid()}</div>
    </div>
  `;

  Modal.open('Assets', html, { wide: true, noConfirm: true });

  // Tab switching
  document.getElementById('atab-bg').addEventListener('click', () => {
    document.getElementById('atab-bg').classList.add('active');
    document.getElementById('atab-ui').classList.remove('active');
    document.getElementById('apanel-bg').style.display = '';
    document.getElementById('apanel-ui').style.display = 'none';
  });
  document.getElementById('atab-ui').addEventListener('click', () => {
    document.getElementById('atab-ui').classList.add('active');
    document.getElementById('atab-bg').classList.remove('active');
    document.getElementById('apanel-ui').style.display = '';
    document.getElementById('apanel-bg').style.display = 'none';
  });

  // BG upload
  _bindUploadZone('bg-upload-zone', 'bg-file-input', async (file) => {
    const name = file.name.replace(/\.[^.]+$/, '').replace(/_/g,' ');
    const fd = new FormData();
    fd.append('file', file);
    fd.append('name', name);
    fd.append('category', 'misc');
    try {
      const bg = await API.uploadBackground(fd);
      APP.state.backgrounds.push(bg);
      document.getElementById('bg-asset-grid').innerHTML = buildBgGrid();
      _bindDeletes();
      Toast.show('Background uploaded');
    } catch (e) { Toast.show(e.message, 'error'); }
  });

  // UI upload
  _bindUploadZone('ui-upload-zone', 'ui-file-input', async (file) => {
    const name = file.name.replace(/\.[^.]+$/, '').replace(/_/g,' ');
    const fd = new FormData();
    fd.append('file', file);
    fd.append('name', name);
    fd.append('category', 'dialogue');
    try {
      const asset = await API.uploadUI(fd);
      APP.state.uiAssets.push(asset);
      document.getElementById('ui-asset-grid').innerHTML = buildUiGrid();
      _bindDeletes();
      Toast.show('UI asset uploaded');
    } catch (e) { Toast.show(e.message, 'error'); }
  });

  _bindDeletes();
}

function _bindDeletes() {
  document.querySelectorAll('.bg-card-del').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = parseInt(btn.dataset.id);
      const isUi = !!btn.dataset.ui;
      try {
        if (isUi) {
          await API.deleteUIAsset(id);
          APP.state.uiAssets = APP.state.uiAssets.filter(u => u.id !== id);
        } else {
          await API.deleteBackground(id);
          APP.state.backgrounds = APP.state.backgrounds.filter(b => b.id !== id);
        }
        btn.closest('.bg-card').remove();
        Toast.show('Deleted');
      } catch (e) { Toast.show(e.message, 'error'); }
    });
  });
}

function _bindUploadZone(zoneId, inputId, onFile) {
  const zone  = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  if (!zone || !input) return;

  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', () => { if (input.files[0]) onFile(input.files[0]); });

  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) onFile(file);
  });
}

// ── Modal ───────────────────────────────────────────────────────────────────
const Modal = {
  _resolve: null,
  open(title, bodyHtml, opts = {}) {
    return new Promise(resolve => {
      Modal._resolve = resolve;
      const overlay = document.getElementById('modal-overlay');
      const modal   = document.getElementById('modal');
      document.getElementById('modal-title').textContent = title;
      document.getElementById('modal-body').innerHTML = bodyHtml;
      modal.classList.toggle('modal-wide', !!opts.wide);

      const footer = document.getElementById('modal-footer');
      if (opts.noConfirm) {
        footer.style.display = 'none';
        document.getElementById('modal-cancel').textContent = 'Close';
        footer.style.display = '';
        document.getElementById('modal-ok').style.display = 'none';
      } else {
        footer.style.display = '';
        document.getElementById('modal-ok').style.display = '';
        document.getElementById('modal-cancel').textContent = 'Cancel';
      }

      overlay.classList.add('active');

      // Char picker wiring
      document.getElementById('cp-type')?.addEventListener('change', e => {
        const isParty = e.target.value === 'party';
        document.getElementById('cp-party-row').style.display  = isParty ? '' : 'none';
        document.getElementById('cp-char-wrap').style.display  = isParty ? 'none' : '';
      });
      document.getElementById('cp-search')?.addEventListener('input', e => {
        const q = e.target.value.toLowerCase();
        const STARS = { legendary:'★★★★★', epic:'★★★★', rare:'★★★', uncommon:'★★', common:'★' };
        document.getElementById('cp-grid').innerHTML = APP.state.characters
          .filter(c => c.name.toLowerCase().includes(q) || c.faction.toLowerCase().includes(q))
          .map(c => {
            const img = c.image_urls?.[0];
            const excl = c.vn_exclusive ? ' char-excl' : '';
            return `<div class="char-card${excl}" data-id="${esc(c.character_id)}" data-name="${esc(c.name)}">
              ${img ? `<img class="char-card-img" src="${esc(img)}" loading="lazy"/>` : '<div class="char-card-img-empty">👤</div>'}
              <div class="char-card-name">${esc(c.name)}</div>
              <div class="char-card-meta">${STARS[c.rarity]||''} ${esc(c.faction)}</div>
              <button class="char-excl-btn${c.vn_exclusive ? ' active' : ''}" data-cid="${esc(c.character_id)}">${c.vn_exclusive ? '🔒 VN Only' : '🔓 Pool'}</button>
            </div>`;
          }).join('') || '<div class="empty-state">No matches</div>';
        _bindCharCards();
      });
      _bindCharCards();

      // BG picker wiring
      document.querySelectorAll('#bg-grid .bg-card').forEach(card => {
        card.addEventListener('click', () => {
          document.querySelectorAll('#bg-grid .bg-card').forEach(c => c.classList.remove('selected'));
          card.classList.add('selected');
          const sel = document.getElementById('bg-selected-key');
          if (sel) sel.value = card.dataset.key;
        });
        card.addEventListener('dblclick', () => {
          const sel = document.getElementById('bg-selected-key');
          if (sel) sel.value = card.dataset.key;
          Modal._close(true);
        });
      });

      // UI asset picker wiring
      document.querySelectorAll('#ui-pick-grid .bg-card').forEach(card => {
        card.addEventListener('click', () => {
          document.querySelectorAll('#ui-pick-grid .bg-card').forEach(c => c.classList.remove('selected'));
          card.classList.add('selected');
          const sel = document.getElementById('ui-selected-id');
          if (sel) sel.value = card.dataset.id;
        });
        card.addEventListener('dblclick', () => {
          const sel = document.getElementById('ui-selected-id');
          if (sel) sel.value = card.dataset.id;
          Modal._close(true);
        });
      });

      // Config preview
      _initConfigPreview();

      // Story delete button
      document.getElementById('ss-delete')?.addEventListener('click', async () => {
        const story = APP.state.currentStory;
        if (!story || !confirm(`Delete "${story.title}"? All scenes will be removed.`)) return;
        try {
          await API.deleteStory(story.id);
          APP.state.stories = APP.state.stories.filter(s => s.id !== story.id);
          APP.state.currentStory = null;
          Modal._close(false);
          StoriesPanel.render();
          SceneTree.load(null, []);
          SceneEditor.render(null);
          _showTab('tab-stories');
          _setBreadcrumb(null);
          Toast.show('Story deleted');
        } catch (e) { Toast.show(e.message, 'error'); }
      });

      document.getElementById('modal-ok').onclick     = () => Modal._close(true);
      document.getElementById('modal-cancel').onclick = () => Modal._close(false);
      overlay.onclick = e => { if (e.target === overlay) Modal._close(false); };
    });
  },
  _close(ok) {
    document.getElementById('modal-overlay').classList.remove('active');
    document.getElementById('modal-ok').style.display = '';
    if (Modal._resolve) { Modal._resolve(ok); Modal._resolve = null; }
  },
};

function _bindCharCards() {
  document.querySelectorAll('.char-card').forEach(card => {
    card.addEventListener('click', () => {
      document.querySelectorAll('.char-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      const sel = document.getElementById('cp-selected');
      if (sel) sel.value = card.dataset.id;
    });
    card.addEventListener('dblclick', () => {
      const sel = document.getElementById('cp-selected');
      if (sel) sel.value = card.dataset.id;
      Modal._close(true);
    });
  });
  document.querySelectorAll('.char-excl-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const cid  = btn.dataset.cid;
      const excl = !btn.classList.contains('active');
      try {
        await API.setVnExclusive(cid, excl);
        const ch = APP.state.characters.find(c => c.character_id === cid);
        if (ch) ch.vn_exclusive = excl;
        btn.classList.toggle('active', excl);
        btn.textContent = excl ? '🔒 VN Only' : '🔓 Pool';
        btn.closest('.char-card')?.classList.toggle('char-excl', excl);
        Toast.show(excl ? `${ch?.name ?? cid} → VN exclusive` : `${ch?.name ?? cid} → back in pool`);
      } catch (err) {
        Toast.show('Failed to update: ' + err.message, 'error');
      }
    });
  });
}

// ── Toast ───────────────────────────────────────────────────────────────────
const Toast = {
  show(msg, type = 'ok') {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = `toast toast-${type} show`;
    clearTimeout(Toast._t);
    Toast._t = setTimeout(() => el.classList.remove('show'), 3000);
  },
};

window.addEventListener('DOMContentLoaded', () => APP.init());

// ── Play mode ────────────────────────────────────────────────────────────────
const PlayMode = (() => {
  let _canvas, _ctx, _scenes, _current, _W, _H;

  function open(startSceneId) {
    const story = APP.state.currentStory;
    _scenes = APP.state.scenes;
    if (!story || !_scenes.length) return Toast.show('No story loaded', 'error');

    _canvas = document.getElementById('play-canvas');
    const overlay = document.getElementById('play-overlay');

    // size canvas to container
    const container = document.getElementById('play-container');
    _W = container.clientWidth  || 1280;
    _H = Math.round(_W * 9 / 16);
    _canvas.width  = _W;
    _canvas.height = _H;
    _ctx = _canvas.getContext('2d');

    overlay.classList.add('active');
    _goTo(startSceneId || story.entry_scene || _scenes[0]?.id);

    _canvas.onclick    = _onClick;
    document.getElementById('play-close').onclick    = close;
    document.addEventListener('keydown', _onKey);
  }

  function close() {
    document.getElementById('play-overlay').classList.remove('active');
    document.getElementById('play-choices').innerHTML = '';
    document.removeEventListener('keydown', _onKey);
    _canvas && (_canvas.onclick = null);
  }

  function _goTo(sceneId) {
    const scene = _scenes.find(s => s.id === sceneId);
    if (!scene) {
      _drawMessage('Scene not found: ' + sceneId);
      return;
    }
    _current = scene;
    document.getElementById('play-choices').innerHTML = '';
    document.getElementById('play-hint').style.opacity = '1';

    Preview.drawScene(scene, _ctx, _W, _H).then(() => {
      if (scene.scene_type === 'choice') {
        _renderChoices(scene.choices || []);
        document.getElementById('play-hint').style.opacity = '0';
      } else if (scene.scene_type === 'ending') {
        _drawEndingBanner(scene);
        document.getElementById('play-hint').style.opacity = '0';
      }
    });
  }

  function _renderChoices(choices) {
    const el = document.getElementById('play-choices');
    el.innerHTML = choices.map((c, i) =>
      `<button class="play-choice-btn" data-idx="${i}">${esc(c.text || `Choice ${i+1}`)}</button>`
    ).join('');
    el.querySelectorAll('.play-choice-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const c = choices[parseInt(btn.dataset.idx)];
        // no stat check in editor preview — always go pass_scene
        const next = c.pass_scene || c.fail_scene;
        if (next) _goTo(next);
        else _drawMessage('No destination set for this choice.');
      });
    });
  }

  function _drawEndingBanner(scene) {
    const colors = { good: '#27ae60', neutral: '#f39c12', bad: '#c0392b' };
    const col = colors[scene.ending_type] || '#555';
    _ctx.fillStyle = 'rgba(0,0,0,0.6)';
    _ctx.fillRect(0, _H * 0.38, _W, _H * 0.24);
    _ctx.fillStyle = col;
    _ctx.font = `bold ${Math.round(_W / 24)}px system-ui, sans-serif`;
    _ctx.textAlign = 'center';
    _ctx.fillText((scene.ending_type || 'ENDING').toUpperCase(), _W / 2, _H * 0.5 - 4);
    _ctx.fillStyle = '#ccc';
    _ctx.font = `${Math.round(_W / 48)}px system-ui, sans-serif`;
    _ctx.fillText('Press Esc to close', _W / 2, _H * 0.5 + Math.round(_W / 32));
  }

  function _drawMessage(msg) {
    _ctx.fillStyle = '#111';
    _ctx.fillRect(0, 0, _W, _H);
    _ctx.fillStyle = '#aaa';
    _ctx.font = `${Math.round(_W / 60)}px system-ui, sans-serif`;
    _ctx.textAlign = 'center';
    _ctx.fillText(msg, _W / 2, _H / 2);
  }

  function _onClick() {
    if (!_current || _current.scene_type === 'choice' || _current.scene_type === 'ending') return;
    const next = _current.next_scene;
    if (next) _goTo(next);
    else { _drawMessage('End of story.'); document.getElementById('play-hint').style.opacity = '0'; }
  }

  function _onKey(e) {
    if (e.key === 'Escape') close();
    else if (e.key === ' ' || e.key === 'Enter') _onClick();
  }

  return { open, close };
})();


async function exportEpisode(storyId) {
  try {
    const data = await API.exportStory(storyId);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url;
    a.download = `${storyId}.episode.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    Toast.show('Exported');
  } catch (e) { Toast.show(e.message, 'error'); }
}

function _reportHtml(report) {
  const list = (items, cls) => items.length
    ? `<ul class="import-report ${cls}">${items.map(t => `<li>${esc(t)}</li>`).join('')}</ul>`
    : '';
  const head = report.errors.length
    ? `<p><strong>${report.errors.length} problem(s) · nothing was written.</strong></p>`
    : `<p><strong>${report.scenes} scenes ready to import as <code>${esc(report.story_id)}</code>.</strong>`
      + (report.overwrite ? ' This <strong>replaces</strong> the existing episode of that id.' : '')
      + '</p>';
  return head + list(report.errors, 'import-errors') + list(report.warnings, 'import-warnings');
}

async function importEpisode() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.json,application/json';
  input.addEventListener('change', async () => {
    const file = input.files?.[0];
    if (!file) return;
    let episode;
    try {
      episode = JSON.parse(await file.text());
    } catch (e) {
      Toast.show('That file is not valid JSON', 'error');
      return;
    }

    let report;
    try {
      report = await API.importStory({ episode, dry_run: true });
    } catch (e) { Toast.show(e.message, 'error'); return; }

    if (report.errors.length) {
      await Modal.open('Import blocked', _reportHtml(report));
      return;
    }

    const ok = await Modal.open('Import episode', _reportHtml(report));
    if (!ok) return;

    try {
      const done = await API.importStory({ episode, overwrite: report.overwrite });
      if (!done.ok) { await Modal.open('Import failed', _reportHtml(done)); return; }
      Toast.show(`Imported ${done.scenes} scenes`);
      await _loadAll();
      StoriesPanel.render();
      APP.selectStory(done.story_id);
    } catch (e) { Toast.show(e.message, 'error'); }
  });
  input.click();
}

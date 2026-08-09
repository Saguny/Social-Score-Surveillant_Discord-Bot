const StoriesPanel = (() => {
  function render() {
    const { stories, arcs, currentStory } = APP.state;
    const el = document.getElementById('story-list');
    const arcMap = Object.fromEntries(arcs.map(a => [a.id, a]));

    if (!stories.length) {
      el.innerHTML = '<div class="empty-state">No stories yet.<br>Click + New to create one.</div>';
      return;
    }

    el.innerHTML = stories.map(s => {
      const active = currentStory?.id === s.id;
      const arc = s.arc_id ? arcMap[s.arc_id] : null;
      return `<div class="story-card${active ? ' active' : ''}" data-id="${s.id}">
        <div class="story-card-title">
          <span class="status-pill status-${s.status}">${s.status}</span>
          ${esc(s.title)}
        </div>
        <div class="story-card-meta">
          <span class="story-card-id">${esc(s.id)}</span>
          ${arc ? `<span class="tag tag-clickable" data-arc-id="${arc.id}" title="Edit arc">${esc(arc.title)} ✎</span>` : ''}
        </div>
      </div>`;
    }).join('');

    el.querySelectorAll('.story-card').forEach(card => {
      card.addEventListener('click', () => APP.selectStory(card.dataset.id));
    });
    el.querySelectorAll('.tag-clickable[data-arc-id]').forEach(tag => {
      tag.addEventListener('click', e => {
        e.stopPropagation();
        openEditArcModal(parseInt(tag.dataset.arcId));
      });
    });
  }

  async function openNewStoryModal() {
    const arcOptions = APP.state.arcs.map(a =>
      `<option value="${a.id}">${esc(a.title)}</option>`
    ).join('');

    const html = `
      <div class="modal-field"><label>Story ID (slug, no spaces)</label>
        <input id="m-id" placeholder="tiananmen_crisis" /></div>
      <div class="modal-field"><label>Title</label>
        <input id="m-title" placeholder="The Tiananmen Crisis" /></div>
      <div class="modal-field"><label>Arc (optional)</label>
        <select id="m-arc"><option value="">— none —</option>${arcOptions}</select></div>
      <div class="modal-field"><label>Party size</label>
        <input id="m-party" type="number" value="3" min="1" max="5" /></div>
      <div class="modal-field"><label>Description</label>
        <textarea id="m-desc" rows="2" placeholder="Brief summary…"></textarea></div>
    `;

    const ok = await Modal.open('New Story', html);
    if (!ok) return;

    const id    = document.getElementById('m-id').value.trim().toLowerCase().replace(/\s+/g, '_');
    const title = document.getElementById('m-title').value.trim();
    if (!id || !title) return Toast.show('ID and title are required', 'error');

    const arc_id     = document.getElementById('m-arc').value || null;
    const party_size = parseInt(document.getElementById('m-party').value) || 3;
    const description = document.getElementById('m-desc').value.trim();

    try {
      const story = await API.createStory({
        id, title,
        arc_id: arc_id ? parseInt(arc_id) : null,
        party_size, description,
      });
      APP.state.stories.unshift(story);
      render();
      APP.selectStory(story.id);
      Toast.show('Story created');
    } catch (e) {
      Toast.show(e.message, 'error');
    }
  }

  function _arcModalHtml(arc = null) {
    const charOpts = (APP.state.characters || []).map(c =>
      `<option value="${esc(c.character_id)}"${arc?.exclusive_char_id === c.character_id ? ' selected' : ''}>${esc(c.name)}</option>`
    ).join('');
    return `
      <div class="modal-field"><label>Title</label>
        <input id="m-arc-title" placeholder="The Long March" value="${esc(arc?.title ?? '')}" /></div>
      <div class="modal-field"><label>Description</label>
        <textarea id="m-arc-desc" rows="2">${esc(arc?.description ?? '')}</textarea></div>
      <div class="modal-field"><label>Exclusive character (arc completion reward)</label>
        <select id="m-arc-char"><option value="">— none —</option>${charOpts}</select></div>
    `;
  }

  async function openArcModal() {
    const ok = await Modal.open('New Arc', _arcModalHtml());
    if (!ok) return;
    const title = document.getElementById('m-arc-title').value.trim();
    if (!title) return Toast.show('Title required', 'error');
    try {
      const arc = await API.createArc({
        title,
        description: document.getElementById('m-arc-desc').value.trim(),
        exclusive_char_id: document.getElementById('m-arc-char').value || null,
      });
      APP.state.arcs.push(arc);
      Toast.show('Arc created');
    } catch (e) {
      Toast.show(e.message, 'error');
    }
  }

  async function openEditArcModal(arcId) {
    const arc = APP.state.arcs.find(a => a.id === arcId);
    if (!arc) return;
    const ok = await Modal.open(`Edit Arc · ${arc.title}`, _arcModalHtml(arc));
    if (!ok) return;
    const title = document.getElementById('m-arc-title').value.trim();
    if (!title) return Toast.show('Title required', 'error');
    try {
      const updated = await API.updateArc(arc.id, {
        title,
        description: document.getElementById('m-arc-desc').value.trim(),
        status: arc.status || 'draft',
        exclusive_char_id: document.getElementById('m-arc-char').value || null,
      });
      const idx = APP.state.arcs.findIndex(a => a.id === arc.id);
      if (idx !== -1) APP.state.arcs[idx] = updated;
      render();
      Toast.show('Arc saved');
    } catch (e) {
      Toast.show(e.message, 'error');
    }
  }

  return { render, openNewStoryModal, openArcModal, openEditArcModal };
})();

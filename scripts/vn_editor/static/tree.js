// Middle panel — scene flow tree (SVG canvas with draggable nodes)
const SceneTree = (() => {
  const NODE_W = 140, NODE_H = 52, PORT_R = 6;
  let _svg = null, _storyId = null, _scenes = [], _selected = null;
  let _drag = null, _panStart = null, _viewBox = { x: 0, y: 0, zoom: 1 };
  let _marquee = null;     // { startX, startY, endX, endY } in scene coords
  let _multiSelect = new Set();

  const TYPE_COLOR = {
    story:   '#c0392b',
    choice:  '#8e44ad',
    ending:  '#27ae60',
    default: '#555',
  };

  function mount(containerId) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    _svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    _svg.style.cssText = 'width:100%;height:100%;user-select:none;cursor:grab';
    container.appendChild(_svg);

    _svg.addEventListener('mousedown', _onSvgMousedown);
    window.addEventListener('mousemove', _onMousemove);
    window.addEventListener('mouseup',   _onMouseup);
    _svg.addEventListener('wheel', _onWheel, { passive: false });
    _svg.addEventListener('dblclick', _onDblclick);
  }

  function load(storyId, scenes) {
    _storyId = storyId;
    _scenes  = scenes;
    _selected = null;
    _viewBox  = { x: -40, y: -40, zoom: 1 };
    render();
  }

  function render() {
    if (!_svg) return;
    _svg.innerHTML = '';
    if (!_scenes.length) {
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('x', '50%'); t.setAttribute('y', '50%');
      t.setAttribute('text-anchor', 'middle'); t.setAttribute('fill', '#555');
      t.textContent = 'Double-click to add a scene';
      _svg.appendChild(t);
      return;
    }

    // transparent backdrop so clicks on empty space fire on _svg
    const bd = _svg.appendChild(document.createElementNS('http://www.w3.org/2000/svg', 'rect'));
    bd.setAttribute('width', '100%'); bd.setAttribute('height', '100%');
    bd.setAttribute('fill', 'transparent');

    const { x, y, zoom } = _viewBox;
    const g = _svg.appendChild(document.createElementNS('http://www.w3.org/2000/svg', 'g'));
    g.setAttribute('transform', `translate(${-x * zoom},${-y * zoom}) scale(${zoom})`);

    // Draw edges first (behind nodes)
    const edgeG = g.appendChild(document.createElementNS('http://www.w3.org/2000/svg', 'g'));
    const sceneMap = Object.fromEntries(_scenes.map(s => [s.id, s]));

    for (const sc of _scenes) {
      const targets = sc.scene_type === 'choice'
        ? sc.choices.map(c => c.pass_scene).filter(Boolean)
        : sc.next_scene ? [sc.next_scene] : [];

      for (const tid of targets) {
        const t = sceneMap[tid];
        if (!t) continue;
        _drawEdge(edgeG, sc, t, sc.scene_type === 'choice' ? '#8e44ad66' : '#c0392b66');
      }
    }

    // Draw nodes
    for (const sc of _scenes) {
      _drawNode(g, sc);
    }

    // Draw marquee selection rect (in SVG pixel space, on top of everything)
    if (_marquee) {
      const { x: vx, y: vy, zoom } = _viewBox;
      const px1 = (_marquee.startX - vx) * zoom;
      const py1 = (_marquee.startY - vy) * zoom;
      const px2 = (_marquee.endX   - vx) * zoom;
      const py2 = (_marquee.endY   - vy) * zoom;
      const mr = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      mr.setAttribute('x',      Math.min(px1, px2));
      mr.setAttribute('y',      Math.min(py1, py2));
      mr.setAttribute('width',  Math.abs(px2 - px1));
      mr.setAttribute('height', Math.abs(py2 - py1));
      mr.setAttribute('fill',   'rgba(100,149,237,0.12)');
      mr.setAttribute('stroke', '#6495ed');
      mr.setAttribute('stroke-width', '1.5');
      mr.setAttribute('stroke-dasharray', '5,3');
      mr.setAttribute('pointer-events', 'none');
      _svg.appendChild(mr);
    }
  }

  function _ensureArrowMarker() {
    if (_svg.querySelector('#arrow')) return;
    const ns = 'http://www.w3.org/2000/svg';
    const defs   = document.createElementNS(ns, 'defs');
    const marker = document.createElementNS(ns, 'marker');
    marker.setAttribute('id', 'arrow');
    marker.setAttribute('markerWidth', '8');
    marker.setAttribute('markerHeight', '8');
    marker.setAttribute('refX', '7');
    marker.setAttribute('refY', '3');
    marker.setAttribute('orient', 'auto');
    marker.setAttribute('markerUnits', 'userSpaceOnUse');
    const tri = document.createElementNS(ns, 'path');
    tri.setAttribute('d', 'M0,0 L0,6 L7,3 z');
    tri.setAttribute('fill', '#c0392b');
    marker.appendChild(tri);
    defs.appendChild(marker);
    _svg.insertBefore(defs, _svg.firstChild);
  }

  function _drawEdge(parent, from, to, color) {
    _ensureArrowMarker();
    const x1 = from.node_x + NODE_W / 2;
    const y1 = from.node_y + NODE_H;
    const x2 = to.node_x + NODE_W / 2;
    const y2 = to.node_y;
    const mid = (y1 + y2) / 2;

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', `M${x1},${y1} C${x1},${mid} ${x2},${mid} ${x2},${y2}`);
    path.setAttribute('stroke', color);
    path.setAttribute('stroke-width', '2');
    path.setAttribute('fill', 'none');
    path.setAttribute('marker-end', 'url(#arrow)');
    parent.appendChild(path);
  }

  function _drawNode(parent, sc) {
    const isSelected = sc.id === _selected;
    const isMulti    = !isSelected && _multiSelect.has(sc.id);
    const color = TYPE_COLOR[sc.scene_type] || TYPE_COLOR.default;

    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('transform', `translate(${sc.node_x},${sc.node_y})`);
    g.style.cursor = 'pointer';
    g.dataset = sc.id;

    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('width', NODE_W); rect.setAttribute('height', NODE_H);
    rect.setAttribute('rx', '6');
    rect.setAttribute('fill', '#1a1a1a');
    rect.setAttribute('stroke', isSelected ? '#fff' : isMulti ? '#6495ed' : color);
    rect.setAttribute('stroke-width', isSelected || isMulti ? '2' : '1');
    if (isMulti) rect.setAttribute('stroke-dasharray', '4,3');
    g.appendChild(rect);

    const bar = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    bar.setAttribute('width', NODE_W); bar.setAttribute('height', '4');
    bar.setAttribute('rx', '6'); bar.setAttribute('fill', color);
    g.appendChild(bar);

    const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    label.setAttribute('x', NODE_W / 2); label.setAttribute('y', '24');
    label.setAttribute('text-anchor', 'middle');
    label.setAttribute('fill', '#eee'); label.setAttribute('font-size', '11');
    label.setAttribute('font-family', 'monospace');
    label.textContent = sc.label.length > 16 ? sc.label.slice(0, 15) + '…' : sc.label;
    g.appendChild(label);

    const sub = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    sub.setAttribute('x', NODE_W / 2); sub.setAttribute('y', '40');
    sub.setAttribute('text-anchor', 'middle');
    sub.setAttribute('fill', '#777'); sub.setAttribute('font-size', '9');
    sub.setAttribute('font-family', 'monospace');
    sub.textContent = `[${sc.id}] · ${sc.scene_type}`;
    g.appendChild(sub);

    // Invisible hit area for dragging
    const hit = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    hit.setAttribute('width', NODE_W); hit.setAttribute('height', NODE_H);
    hit.setAttribute('fill', 'transparent');
    hit.addEventListener('mousedown', (e) => {
      e.stopPropagation();
      _multiSelect = new Set();
      _drag = { scene: sc, startX: sc.node_x, startY: sc.node_y, mouseX: e.clientX, mouseY: e.clientY };
      APP.selectScene(sc.id);
    });
    g.appendChild(hit);

    // ▶ Play-from-here button (top-right corner, above hit area)
    const playBg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    playBg.setAttribute('x', NODE_W - 20); playBg.setAttribute('y', 6);
    playBg.setAttribute('width', 14); playBg.setAttribute('height', 14);
    playBg.setAttribute('rx', 3);
    playBg.setAttribute('fill', '#1e5c1e');
    playBg.style.cursor = 'pointer';
    g.appendChild(playBg);

    const playIcon = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    playIcon.setAttribute('x', NODE_W - 13); playIcon.setAttribute('y', 17);
    playIcon.setAttribute('text-anchor', 'middle');
    playIcon.setAttribute('fill', '#6fcf6f'); playIcon.setAttribute('font-size', '9');
    playIcon.textContent = '▶';
    playIcon.style.cursor = 'pointer';
    g.appendChild(playIcon);

    const playHit = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    playHit.setAttribute('x', NODE_W - 20); playHit.setAttribute('y', 6);
    playHit.setAttribute('width', 14); playHit.setAttribute('height', 14);
    playHit.setAttribute('fill', 'transparent');
    playHit.style.cursor = 'pointer';
    playHit.addEventListener('mousedown', e => e.stopPropagation());
    playHit.addEventListener('click', (e) => {
      e.stopPropagation();
      if (typeof PlayMode !== 'undefined') PlayMode.open(sc.id);
    });
    g.appendChild(playHit);

    parent.appendChild(g);
  }

  function _svgCoords(e) {
    const rect = _svg.getBoundingClientRect();
    const { x, y, zoom } = _viewBox;
    return {
      x: (e.clientX - rect.left) / zoom + x,
      y: (e.clientY - rect.top)  / zoom + y,
    };
  }

  function _onSvgMousedown(e) {
    if (e.button !== 0) return;
    if (e.ctrlKey) {
      const { x, y } = _svgCoords(e);
      _marquee = { startX: x, startY: y, endX: x, endY: y };
      _multiSelect = new Set();
      _svg.style.cursor = 'crosshair';
    } else {
      _panStart = { mouseX: e.clientX, mouseY: e.clientY, vx: _viewBox.x, vy: _viewBox.y };
      _svg.style.cursor = 'grabbing';
    }
  }

  function _onMousemove(e) {
    if (_drag) {
      const dx = (e.clientX - _drag.mouseX) / _viewBox.zoom;
      const dy = (e.clientY - _drag.mouseY) / _viewBox.zoom;
      _drag.scene.node_x = Math.max(0, Math.round(_drag.startX + dx));
      _drag.scene.node_y = Math.max(0, Math.round(_drag.startY + dy));
      render();
    } else if (_marquee) {
      const { x, y } = _svgCoords(e);
      _marquee.endX = x;
      _marquee.endY = y;
      render();
    } else if (_panStart) {
      _viewBox.x = _panStart.vx - (e.clientX - _panStart.mouseX) / _viewBox.zoom;
      _viewBox.y = _panStart.vy - (e.clientY - _panStart.mouseY) / _viewBox.zoom;
      render();
    }
  }

  async function _onMouseup(e) {
    if (_drag) {
      const sc = _drag.scene;
      _drag = null;
      try {
        await API.moveScene(_storyId, sc.id, { x: sc.node_x, y: sc.node_y });
      } catch (_) {}
    }
    if (_marquee) {
      const minX = Math.min(_marquee.startX, _marquee.endX);
      const minY = Math.min(_marquee.startY, _marquee.endY);
      const maxX = Math.max(_marquee.startX, _marquee.endX);
      const maxY = Math.max(_marquee.startY, _marquee.endY);
      _multiSelect = new Set(
        _scenes
          .filter(s =>
            s.node_x < maxX && s.node_x + NODE_W > minX &&
            s.node_y < maxY && s.node_y + NODE_H > minY
          )
          .map(s => s.id)
      );
      _marquee = null;
      _svg.style.cursor = 'grab';
      render();
      if (typeof APP !== 'undefined') APP.onMultiSelect([..._multiSelect]);
    }
    if (_panStart) {
      _panStart = null;
      _svg.style.cursor = 'grab';
    }
  }

  function _onWheel(e) {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    const rect = _svg.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / _viewBox.zoom + _viewBox.x;
    const my = (e.clientY - rect.top)  / _viewBox.zoom + _viewBox.y;
    _viewBox.zoom = Math.max(0.2, Math.min(3, _viewBox.zoom * factor));
    _viewBox.x = mx - (e.clientX - rect.left) / _viewBox.zoom;
    _viewBox.y = my - (e.clientY - rect.top)  / _viewBox.zoom;
    render();
  }

  async function _onDblclick(e) {
    if (!_storyId) return;
    const { x, y } = _svgCoords(e);
    const id = `s${Date.now()}`;
    try {
      const sc = await API.createScene(_storyId, {
        id, label: 'New Scene', scene_type: 'story',
        node_x: Math.round(x - NODE_W / 2), node_y: Math.round(y - NODE_H / 2),
      });
      _scenes.push(sc);
      if (!APP.state.scenes.find(s => s.id === sc.id)) APP.state.scenes.push(sc);
      render();
      APP.selectScene(sc.id);
      Toast.show('Scene added — edit on the right');
    } catch (e) {
      Toast.show(e.message, 'error');
    }
  }

  function setSelected(sceneId) {
    _selected = sceneId;
    render();
  }

  function addScene(sc) {
    _scenes.push(sc);
    render();
  }

  function removeScene(sceneId) {
    _scenes = _scenes.filter(s => s.id !== sceneId);
    if (_selected === sceneId) _selected = null;
    render();
  }

  function updateScene(sc) {
    const i = _scenes.findIndex(s => s.id === sc.id);
    if (i >= 0) _scenes[i] = sc;
    render();
  }

  function fitAll() {
    if (!_scenes.length || !_svg) return;
    const pad = 40;
    const minX = Math.min(..._scenes.map(s => s.node_x)) - pad;
    const minY = Math.min(..._scenes.map(s => s.node_y)) - pad;
    const maxX = Math.max(..._scenes.map(s => s.node_x + NODE_W)) + pad;
    const maxY = Math.max(..._scenes.map(s => s.node_y + NODE_H)) + pad;
    const rect = _svg.getBoundingClientRect();
    const zoom = Math.min(rect.width / (maxX - minX), rect.height / (maxY - minY), 1.5);
    _viewBox = { x: minX, y: minY, zoom };
    render();
  }

  function clearMultiSelect() {
    _multiSelect = new Set();
    render();
  }

  return { mount, load, render, setSelected, addScene, removeScene, updateScene, fitAll, clearMultiSelect };
})();

const API = {
  async _req(method, path, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error(`${method} ${path} → ${res.status}`);
    return res.json();
  },
  get:   (p)    => API._req('GET',    p),
  post:  (p, b) => API._req('POST',   p, b),
  put:   (p, b) => API._req('PUT',    p, b),
  patch: (p, b) => API._req('PATCH',  p, b),
  del:   (p)    => API._req('DELETE', p),

  // arcs
  getArcs:    ()      => API.get('/api/vn/arcs'),
  createArc:  (data)  => API.post('/api/vn/arcs', data),
  updateArc:  (id, d) => API.put(`/api/vn/arcs/${id}`, d),
  deleteArc:  (id)    => API.del(`/api/vn/arcs/${id}`),

  // stories
  getStories:  ()      => API.get('/api/vn/stories'),
  createStory: (data)  => API.post('/api/vn/stories', data),
  updateStory: (id, d) => API.put(`/api/vn/stories/${id}`, d),
  deleteStory: (id)    => API.del(`/api/vn/stories/${id}`),

  // scenes
  getScenes:   (sid)          => API.get(`/api/vn/stories/${sid}/scenes`),
  createScene: (sid, data)    => API.post(`/api/vn/stories/${sid}/scenes`, data),
  updateScene: (sid, scid, d) => API.put(`/api/vn/stories/${sid}/scenes/${scid}`, d),
  moveScene:   (sid, scid, p) => API.patch(`/api/vn/stories/${sid}/scenes/${scid}/position`, p),
  deleteScene: (sid, scid)    => API.del(`/api/vn/stories/${sid}/scenes/${scid}`),

  // characters
  getCharacters:    ()           => API.get('/api/vn/characters'),
  setVnExclusive:   (id, excl)   => API._req('PATCH', `/api/vn/characters/${encodeURIComponent(id)}/vn-exclusive`, { vn_exclusive: excl }),

  // backgrounds
  getBackgrounds:   () => API.get('/api/vn/backgrounds'),
  deleteBackground: (id) => API.del(`/api/vn/backgrounds/${id}`),

  // ui assets
  getUIAssets:   () => API.get('/api/vn/ui-assets'),
  deleteUIAsset: (id) => API.del(`/api/vn/ui-assets/${id}`),

  // uploads (multipart — handled separately with FormData)
  async uploadBackground(formData) {
    const res = await fetch('/api/vn/upload/background', { method: 'POST', body: formData });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    return res.json();
  },
  async uploadUI(formData) {
    const res = await fetch('/api/vn/upload/ui', { method: 'POST', body: formData });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    return res.json();
  },
  exportStory: (id) => API.get(`/api/vn/stories/${id}/export`),
  importStory: (body) => API.post('/api/vn/import', body),

  getConfig:  ()  => API.get('/api/vn/config'),
  saveConfig: (b) => API._req('PUT', '/api/vn/config', b),
};

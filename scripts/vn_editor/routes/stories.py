import json
from aiohttp import web
from ..db import get_pool

routes = web.RouteTableDef()


def _row(r) -> dict:
    d = dict(r)
    if isinstance(d.get('test_party'), str):
        import json as _json
        d['test_party'] = _json.loads(d['test_party'])
    return d


@routes.get('/api/vn/arcs')
async def list_arcs(request):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch('SELECT * FROM vn_arcs ORDER BY created_at DESC')
    return web.json_response([_row(r) for r in rows])


@routes.post('/api/vn/arcs')
async def create_arc(request):
    data = await request.json()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            'INSERT INTO vn_arcs (title, description) VALUES ($1, $2) RETURNING *',
            data['title'], data.get('description', ''),
        )
    return web.json_response(_row(row))


@routes.put('/api/vn/arcs/{id}')
async def update_arc(request):
    arc_id = int(request.match_info['id'])
    data = await request.json()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            'UPDATE vn_arcs SET title=$1, description=$2, status=$3, exclusive_char_id=$4 WHERE id=$5 RETURNING *',
            data['title'], data.get('description', ''), data.get('status', 'draft'),
            data.get('exclusive_char_id'), arc_id,
        )
    if not row:
        raise web.HTTPNotFound()
    return web.json_response(_row(row))


@routes.delete('/api/vn/arcs/{id}')
async def delete_arc(request):
    arc_id = int(request.match_info['id'])
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM vn_arcs WHERE id=$1', arc_id)
    return web.json_response({'ok': True})


@routes.get('/api/vn/stories')
async def list_stories(request):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch('SELECT * FROM vn_stories ORDER BY created_at DESC')
    return web.json_response([_row(r) for r in rows])


@routes.post('/api/vn/stories')
async def create_story(request):
    data = await request.json()
    story_id = data['id'].strip().lower().replace(' ', '_')
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                '''INSERT INTO vn_stories (id, arc_id, title, description, party_size, entry_scene)
                   VALUES ($1,$2,$3,$4,$5,$6) RETURNING *''',
                story_id, data.get('arc_id'), data['title'],
                data.get('description', ''), data.get('party_size', 3), 's1',
            )
            await conn.execute(
                '''INSERT INTO vn_scenes (id, story_id, label, scene_type, dialogue_text, node_x, node_y)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)''',
                's1', story_id, 'Opening', 'story', 'Your story begins here...', 80, 60,
            )
    return web.json_response(_row(row))


@routes.put('/api/vn/stories/{id}')
async def update_story(request):
    sid = request.match_info['id']
    data = await request.json()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            '''UPDATE vn_stories SET title=$1, description=$2, status=$3, party_size=$4,
               arc_id=$5, entry_scene=$6, test_party=$7::jsonb, episode_number=$9,
               featured_char_id=$10, faction=$11
               WHERE id=$8 RETURNING *''',
            data['title'], data.get('description', ''), data.get('status', 'draft'),
            data.get('party_size', 3), data.get('arc_id'), data.get('entry_scene', 's1'),
            json.dumps(data.get('test_party', [])), sid,
            int(data.get('episode_number', 1)),
            data.get('featured_char_id') or None,
            data.get('faction') or None,
        )
    if not row:
        raise web.HTTPNotFound()
    return web.json_response(_row(row))


@routes.delete('/api/vn/stories/{id}')
async def delete_story(request):
    sid = request.match_info['id']
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM vn_stories WHERE id=$1', sid)
    return web.json_response({'ok': True})

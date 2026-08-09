import json
from aiohttp import web
from ..db import get_pool

routes = web.RouteTableDef()


def _deserialize(row) -> dict:
    d = dict(row)
    for key in ('chars', 'choices', 'conditions'):
        if isinstance(d.get(key), str):
            d[key] = json.loads(d[key])
        elif d.get(key) is None:
            d[key] = []
    return d


@routes.get('/api/vn/stories/{story_id}/scenes')
async def list_scenes(request):
    story_id = request.match_info['story_id']
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            'SELECT * FROM vn_scenes WHERE story_id=$1 ORDER BY node_y, node_x',
            story_id,
        )
    return web.json_response([_deserialize(r) for r in rows])


@routes.post('/api/vn/stories/{story_id}/scenes')
async def create_scene(request):
    story_id = request.match_info['story_id']
    data = await request.json()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            '''INSERT INTO vn_scenes
               (id, story_id, label, scene_type, bg_key, ui_asset_id, ui_scale, text_color,
                bg_blur, chars, speaker, dialogue_text, next_scene, choices, ending_type,
                node_x, node_y, reward_yuan, reward_roll_resets, conditions)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13,$14::jsonb,$15,$16,$17,$18,$19,$20::jsonb)
               RETURNING *''',
            data['id'], story_id,
            data.get('label', 'New Scene'),
            data.get('scene_type', 'story'),
            data.get('bg_key'),
            data.get('ui_asset_id'),
            data.get('ui_scale', 1.0),
            data.get('text_color', 'black'),
            data.get('bg_blur', 0.0),
            json.dumps(data.get('chars', [])),
            data.get('speaker', 'narrator'),
            data.get('dialogue_text', ''),
            data.get('next_scene'),
            json.dumps(data.get('choices', [])),
            data.get('ending_type'),
            data.get('node_x', 80),
            data.get('node_y', 60),
            data.get('reward_yuan'),
            data.get('reward_roll_resets'),
            json.dumps(data.get('conditions', [])),
        )
    return web.json_response(_deserialize(row))


@routes.put('/api/vn/stories/{story_id}/scenes/{scene_id}')
async def update_scene(request):
    story_id = request.match_info['story_id']
    scene_id = request.match_info['scene_id']
    data = await request.json()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            '''UPDATE vn_scenes SET
               label=$1, scene_type=$2, bg_key=$3, ui_asset_id=$4, ui_scale=$5, text_color=$6,
               bg_blur=$7, chars=$8::jsonb, speaker=$9, dialogue_text=$10, next_scene=$11,
               choices=$12::jsonb, ending_type=$13, node_x=$14, node_y=$15,
               reward_yuan=$16, reward_roll_resets=$17, conditions=$18::jsonb
               WHERE id=$19 AND story_id=$20 RETURNING *''',
            data.get('label', 'New Scene'),
            data.get('scene_type', 'story'),
            data.get('bg_key'),
            data.get('ui_asset_id'),
            data.get('ui_scale', 1.0),
            data.get('text_color', 'black'),
            data.get('bg_blur', 0.0),
            json.dumps(data.get('chars', [])),
            data.get('speaker', 'narrator'),
            data.get('dialogue_text', ''),
            data.get('next_scene'),
            json.dumps(data.get('choices', [])),
            data.get('ending_type'),
            data.get('node_x', 80),
            data.get('node_y', 60),
            data.get('reward_yuan'),
            data.get('reward_roll_resets'),
            json.dumps(data.get('conditions', [])),
            scene_id, story_id,
        )
    if not row:
        raise web.HTTPNotFound()
    return web.json_response(_deserialize(row))


@routes.patch('/api/vn/stories/{story_id}/scenes/{scene_id}/position')
async def move_scene(request):
    story_id = request.match_info['story_id']
    scene_id = request.match_info['scene_id']
    data = await request.json()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            'UPDATE vn_scenes SET node_x=$1, node_y=$2 WHERE id=$3 AND story_id=$4',
            data['x'], data['y'], scene_id, story_id,
        )
    return web.json_response({'ok': True})


@routes.delete('/api/vn/stories/{story_id}/scenes/{scene_id}')
async def delete_scene(request):
    story_id = request.match_info['story_id']
    scene_id = request.match_info['scene_id']
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            'DELETE FROM vn_scenes WHERE id=$1 AND story_id=$2',
            scene_id, story_id,
        )
    return web.json_response({'ok': True})

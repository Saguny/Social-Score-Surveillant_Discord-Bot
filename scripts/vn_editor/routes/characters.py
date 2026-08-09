from aiohttp import web
from ..db import get_pool

routes = web.RouteTableDef()


@routes.get('/api/vn/characters')
async def list_characters(request):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            '''SELECT character_id, name, title, faction, rarity, gender,
                      stat_authority, stat_military, stat_charisma, image_urls, vn_exclusive
               FROM gacha_characters
               WHERE enabled = TRUE
               ORDER BY rarity DESC, name ASC'''
        )
    result = []
    for r in rows:
        d = dict(r)
        d['image_urls'] = list(d['image_urls'] or [])
        d['stats'] = {
            'authority': d.pop('stat_authority', 0),
            'military':  d.pop('stat_military', 0),
            'charisma':  d.pop('stat_charisma', 0),
        }
        result.append(d)
    return web.json_response(result)


@routes.patch('/api/vn/characters/{character_id}/vn-exclusive')
async def set_vn_exclusive(request):
    character_id = request.match_info['character_id']
    body = await request.json()
    exclusive = bool(body.get('vn_exclusive', False))
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE gacha_characters SET vn_exclusive = $2 WHERE character_id = $1 AND enabled = TRUE",
            character_id, exclusive,
        )
    if result == "UPDATE 0":
        raise web.HTTPNotFound()
    return web.json_response({'character_id': character_id, 'vn_exclusive': exclusive})

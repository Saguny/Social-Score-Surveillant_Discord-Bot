from aiohttp import web
from ..db import get_pool

routes = web.RouteTableDef()


@routes.get('/api/vn/backgrounds')
async def list_backgrounds(request):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            'SELECT * FROM vn_backgrounds ORDER BY category, name'
        )
    return web.json_response([dict(r) for r in rows])


@routes.delete('/api/vn/backgrounds/{id}')
async def delete_background(request):
    bg_id = int(request.match_info['id'])
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM vn_backgrounds WHERE id=$1', bg_id)
    return web.json_response({'ok': True})

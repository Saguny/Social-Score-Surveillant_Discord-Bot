import mimetypes
import os
import uuid

import aiohttp
from aiohttp import web

from ..db import get_pool

routes = web.RouteTableDef()


def _r2_cfg():
    token      = os.getenv('R2_TOKEN', '')
    account_id = os.getenv('R2_ACCOUNT_ID', '')
    bucket     = os.getenv('R2_BUCKET', 'social-credit-gacha')
    public_url = os.getenv('R2_PUBLIC_URL', '').rstrip('/')
    return token, account_id, bucket, public_url


async def _upload_r2(key: str, data: bytes, content_type: str) -> str:
    token, account_id, bucket, public_url = _r2_cfg()
    print(f'[R2 cfg] TOKEN={token[:8]!r}… ACCOUNT={account_id!r} BUCKET={bucket!r}')
    if not token or not account_id:
        raise web.HTTPInternalServerError(reason=f'R2 not configured — TOKEN={bool(token)} ACCOUNT={bool(account_id)}')
    url = f'https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets/{bucket}/objects/{key}'
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': content_type}
    print(f'[R2] PUT {url}  ({len(data)} bytes)')
    async with aiohttp.ClientSession() as session:
        async with session.put(url, data=data, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=60)) as r:
            body = await r.text()
            print(f'[R2] response {r.status}: {body[:300]}')
            if r.status not in (200, 201):
                raise web.HTTPBadGateway(reason=f'R2 {r.status}: {body[:300]}')
    return f'{public_url}/{key}'


@routes.post('/api/vn/upload/background')
async def upload_background(request):
    reader = await request.multipart()

    name = 'Untitled'
    category = 'misc'
    file_data = None
    filename = 'file.png'

    async for field in reader:
        if field.name == 'name':
            name = (await field.read()).decode()
        elif field.name == 'category':
            category = (await field.read()).decode()
        elif field.name == 'file':
            filename = field.filename or 'file.png'
            file_data = await field.read()

    if not file_data:
        raise web.HTTPBadRequest(reason='No file provided')

    ext = os.path.splitext(filename)[1] or '.png'
    key = f'vn/bg/{uuid.uuid4().hex}{ext}'
    ct = mimetypes.guess_type(filename)[0] or 'image/png'

    public_url = await _upload_r2(key, file_data, ct)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            '''INSERT INTO vn_backgrounds (name, filename, r2_key, public_url, category, z_layer)
               VALUES ($1,$2,$3,$4,$5,0) RETURNING *''',
            name, filename, key, public_url, category,
        )
    return web.json_response(dict(row))


@routes.post('/api/vn/upload/ui')
async def upload_ui(request):
    reader = await request.multipart()

    name = 'Untitled'
    category = 'dialogue'
    file_data = None
    filename = 'file.png'

    async for field in reader:
        if field.name == 'name':
            name = (await field.read()).decode()
        elif field.name == 'category':
            category = (await field.read()).decode()
        elif field.name == 'file':
            filename = field.filename or 'file.png'
            file_data = await field.read()

    if not file_data:
        raise web.HTTPBadRequest(reason='No file provided')

    ext = os.path.splitext(filename)[1] or '.png'
    key = f'vn/ui/{uuid.uuid4().hex}{ext}'
    ct = mimetypes.guess_type(filename)[0] or 'image/png'

    public_url = await _upload_r2(key, file_data, ct)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            '''INSERT INTO vn_ui_assets (name, filename, r2_key, public_url, category, z_layer)
               VALUES ($1,$2,$3,$4,$5,2) RETURNING *''',
            name, filename, key, public_url, category,
        )
    return web.json_response(dict(row))


@routes.get('/api/vn/ui-assets')
async def list_ui_assets(request):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch('SELECT * FROM vn_ui_assets ORDER BY category, name')
    return web.json_response([dict(r) for r in rows])


@routes.delete('/api/vn/ui-assets/{id}')
async def delete_ui_asset(request):
    asset_id = int(request.match_info['id'])
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM vn_ui_assets WHERE id=$1', asset_id)
    return web.json_response({'ok': True})

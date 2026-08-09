from aiohttp import web
from ..db import get_pool

routes = web.RouteTableDef()

_DEFAULTS = dict(
    speaker_dx=0, speaker_dy=0,
    text_dx=0,    text_dy=0,
    speaker_box=True, speaker_box_color='#c0392b',
    speaker_font_size=13, text_font_size=13,
    ui_scale=1.0, char_pad_top=0, char_scale=1.0, text_area_w=0,
)


@routes.get('/api/vn/config')
async def get_config(request):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow('SELECT * FROM vn_config WHERE id=1')
    return web.json_response(dict(row) if row else {**_DEFAULTS, 'id': 1})


@routes.put('/api/vn/config')
async def put_config(request):
    data = await request.json()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow('''
            INSERT INTO vn_config
                (id, speaker_dx, speaker_dy, text_dx, text_dy,
                 speaker_box, speaker_box_color, speaker_font_size, text_font_size, ui_scale, char_pad_top, char_scale, text_area_w)
            VALUES (1, $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (id) DO UPDATE SET
                speaker_dx=EXCLUDED.speaker_dx,           speaker_dy=EXCLUDED.speaker_dy,
                text_dx=EXCLUDED.text_dx,                 text_dy=EXCLUDED.text_dy,
                speaker_box=EXCLUDED.speaker_box,         speaker_box_color=EXCLUDED.speaker_box_color,
                speaker_font_size=EXCLUDED.speaker_font_size, text_font_size=EXCLUDED.text_font_size,
                ui_scale=EXCLUDED.ui_scale,               char_pad_top=EXCLUDED.char_pad_top,
                char_scale=EXCLUDED.char_scale, text_area_w=EXCLUDED.text_area_w
            RETURNING *
        ''',
            int(data.get('speaker_dx', 0)),
            int(data.get('speaker_dy', 0)),
            int(data.get('text_dx', 0)),
            int(data.get('text_dy', 0)),
            bool(data.get('speaker_box', True)),
            data.get('speaker_box_color', '#c0392b'),
            int(data.get('speaker_font_size', 13)),
            int(data.get('text_font_size', 13)),
            float(data.get('ui_scale', 1.0)),
            int(data.get('char_pad_top', 0)),
            float(data.get('char_scale', 1.0)),
            int(data.get('text_area_w', 0)),
        )
    return web.json_response(dict(row))

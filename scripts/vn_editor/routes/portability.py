"""
Episode export / import.

Scenes reference assets two different ways: `bg_key` is an R2 key and is stable
across databases, but `ui_asset_id` is a SERIAL and is not. Export therefore
writes the UI asset's NAME and import resolves it back to a local id, so a file
moved between environments points at the right dialogue box or reports that it
could not find one. Unresolvable references are reported, never silently written.
"""
import json

from aiohttp import web

from ..db import get_pool

routes = web.RouteTableDef()

EPISODE_FORMAT = 1

_STORY_FIELDS = [
    'id', 'arc_id', 'title', 'description', 'status', 'party_size',
    'entry_scene', 'test_party', 'episode_number', 'featured_char_id', 'faction',
]

_SCENE_FIELDS = [
    'id', 'label', 'scene_type', 'bg_key', 'ui_scale', 'text_color', 'bg_blur',
    'chars', 'speaker', 'dialogue_text', 'next_scene', 'choices', 'ending_type',
    'node_x', 'node_y', 'reward_yuan', 'reward_roll_resets', 'conditions',
]

_SCENE_TYPES = {'story', 'choice', 'ending', 'router'}

_JSON_SCENE_FIELDS = ('chars', 'choices', 'conditions')


def _loads(value, fallback):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return fallback
    return value if value is not None else fallback


def _scene_targets(scene: dict):
    """Every scene id this scene can send a player to."""
    out = []
    if scene.get('next_scene'):
        out.append(('next_scene', scene['next_scene']))
    for i, choice in enumerate(scene.get('choices') or []):
        for field in ('pass_scene', 'fail_scene'):
            if choice.get(field):
                out.append((f'choice {i + 1} {field}', choice[field]))
    for i, cond in enumerate(scene.get('conditions') or []):
        if cond.get('scene'):
            out.append((f'condition {i + 1}', cond['scene']))
    return out


# ── export ────────────────────────────────────────────────────────────────────

@routes.get('/api/vn/stories/{story_id}/export')
async def export_story(request):
    story_id = request.match_info['story_id']
    pool = await get_pool()
    async with pool.acquire() as conn:
        story = await conn.fetchrow('SELECT * FROM vn_stories WHERE id = $1', story_id)
        if not story:
            raise web.HTTPNotFound()
        scenes = await conn.fetch(
            'SELECT * FROM vn_scenes WHERE story_id = $1 ORDER BY id', story_id
        )
        ui_names = dict(await conn.fetch('SELECT id, name FROM vn_ui_assets') or [])

    story_out = {k: story[k] for k in _STORY_FIELDS if k in story}
    story_out['test_party'] = _loads(story_out.get('test_party'), [])

    scenes_out = []
    for row in scenes:
        scene = {k: row[k] for k in _SCENE_FIELDS if k in row}
        for field in _JSON_SCENE_FIELDS:
            scene[field] = _loads(scene.get(field), [])
        if row['ui_asset_id']:
            scene['ui_asset'] = ui_names.get(row['ui_asset_id'])
        scenes_out.append(scene)

    payload = {'format': EPISODE_FORMAT, 'story': story_out, 'scenes': scenes_out}
    return web.json_response(
        payload,
        headers={'Content-Disposition': f'attachment; filename="{story_id}.episode.json"'},
    )


# ── import ────────────────────────────────────────────────────────────────────

def _validate(episode: dict, known: dict) -> tuple[list, list]:
    errors: list[str] = []
    warnings: list[str] = []

    story  = episode.get('story') or {}
    scenes = episode.get('scenes') or []

    story_id = (story.get('id') or '').strip()
    if not story_id:
        errors.append('story.id is missing')
    if not (story.get('title') or '').strip():
        errors.append('story.title is missing')
    if not scenes:
        errors.append('episode has no scenes')

    ids = [str(s.get('id') or '').strip() for s in scenes]
    for i, sid in enumerate(ids):
        if not sid:
            errors.append(f'scene {i + 1} has no id')
    dupes = {s for s in ids if s and ids.count(s) > 1}
    for dupe in sorted(dupes):
        errors.append(f'duplicate scene id "{dupe}"')

    id_set = {s for s in ids if s}
    entry = story.get('entry_scene') or 's1'
    if entry not in id_set:
        errors.append(f'entry_scene "{entry}" is not one of the scenes')

    for scene in scenes:
        sid  = scene.get('id')
        kind = scene.get('scene_type') or 'story'
        if kind not in _SCENE_TYPES:
            errors.append(f'scene "{sid}" has unknown scene_type "{kind}"')
        for where, target in _scene_targets(scene):
            if target not in id_set:
                errors.append(f'scene "{sid}" {where} points at missing scene "{target}"')
        if kind == 'router' and not scene.get('conditions') and not scene.get('next_scene'):
            errors.append(f'router "{sid}" has no conditions and no fallback scene')
        if kind == 'ending' and scene.get('next_scene'):
            warnings.append(f'ending "{sid}" has a next_scene, which is ignored')

        bg = scene.get('bg_key')
        if bg and bg not in known['backgrounds']:
            warnings.append(f'scene "{sid}" background "{bg}" is not in this database')
        ui = scene.get('ui_asset')
        if ui and ui not in known['ui_assets']:
            warnings.append(f'scene "{sid}" UI asset "{ui}" is not in this database · will be left unset')
        for entry_char in (scene.get('chars') or []):
            cid = entry_char.get('character_id')
            if entry_char.get('type') != 'party' and cid and cid not in known['characters']:
                warnings.append(f'scene "{sid}" character "{cid}" is not in this database')

    featured = story.get('featured_char_id')
    if featured and featured not in known['characters']:
        warnings.append(f'featured character "{featured}" is not in this database · will be left unset')
    if story.get('arc_id') and story['arc_id'] not in known['arcs']:
        warnings.append(f'arc {story["arc_id"]} does not exist here · the episode will be imported unassigned')

    return errors, warnings


@routes.post('/api/vn/import')
async def import_story(request):
    body     = await request.json()
    episode  = body.get('episode') or {}
    dry_run  = bool(body.get('dry_run'))
    override = (body.get('story_id') or '').strip()
    overwrite = bool(body.get('overwrite'))

    story  = dict(episode.get('story') or {})
    scenes = episode.get('scenes') or []
    if override:
        story['id'] = override

    pool = await get_pool()
    async with pool.acquire() as conn:
        bg_rows   = await conn.fetch('SELECT r2_key FROM vn_backgrounds')
        ui_rows   = await conn.fetch('SELECT id, name FROM vn_ui_assets')
        char_rows = await conn.fetch('SELECT character_id FROM gacha_characters')
        arc_rows  = await conn.fetch('SELECT id FROM vn_arcs')
        existing  = await conn.fetchval(
            'SELECT 1 FROM vn_stories WHERE id = $1', story.get('id') or ''
        )

    ui_by_name = {r['name']: r['id'] for r in ui_rows}
    known = {
        'backgrounds': {r['r2_key'] for r in bg_rows},
        'ui_assets':   set(ui_by_name),
        'characters':  {r['character_id'] for r in char_rows},
        'arcs':        {r['id'] for r in arc_rows},
    }

    errors, warnings = _validate({'story': story, 'scenes': scenes}, known)

    if existing and not overwrite:
        errors.append(
            f'story "{story.get("id")}" already exists · '
            'choose a different id or confirm overwrite'
        )

    report = {
        'ok':        not errors,
        'dry_run':   dry_run,
        'story_id':  story.get('id'),
        'scenes':    len(scenes),
        'errors':    errors,
        'warnings':  warnings,
        'overwrite': bool(existing),
    }

    if errors or dry_run:
        return web.json_response(report)

    arc_id = story.get('arc_id') if story.get('arc_id') in known['arcs'] else None
    featured = story.get('featured_char_id')
    if featured not in known['characters']:
        featured = None

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                '''INSERT INTO vn_stories
                     (id, arc_id, title, description, status, party_size, entry_scene,
                      test_party, episode_number, featured_char_id, faction)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11)
                   ON CONFLICT (id) DO UPDATE SET
                     arc_id=EXCLUDED.arc_id, title=EXCLUDED.title,
                     description=EXCLUDED.description, status=EXCLUDED.status,
                     party_size=EXCLUDED.party_size, entry_scene=EXCLUDED.entry_scene,
                     test_party=EXCLUDED.test_party, episode_number=EXCLUDED.episode_number,
                     featured_char_id=EXCLUDED.featured_char_id, faction=EXCLUDED.faction''',
                story['id'], arc_id, story['title'], story.get('description', ''),
                story.get('status', 'draft'), int(story.get('party_size', 3)),
                story.get('entry_scene', 's1'),
                json.dumps(story.get('test_party') or []),
                int(story.get('episode_number', 1)), featured, story.get('faction') or None,
            )
            await conn.execute('DELETE FROM vn_scenes WHERE story_id = $1', story['id'])
            for scene in scenes:
                await conn.execute(
                    '''INSERT INTO vn_scenes
                         (id, story_id, label, scene_type, bg_key, ui_asset_id, ui_scale,
                          text_color, bg_blur, chars, speaker, dialogue_text, next_scene,
                          choices, ending_type, node_x, node_y, reward_yuan,
                          reward_roll_resets, conditions)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13,
                               $14::jsonb,$15,$16,$17,$18,$19,$20::jsonb)''',
                    scene['id'], story['id'], scene.get('label', 'Scene'),
                    scene.get('scene_type', 'story'), scene.get('bg_key'),
                    ui_by_name.get(scene.get('ui_asset')),
                    float(scene.get('ui_scale') or 1.0),
                    scene.get('text_color', 'black'), float(scene.get('bg_blur') or 0.0),
                    json.dumps(scene.get('chars') or []),
                    scene.get('speaker', 'narrator'), scene.get('dialogue_text', ''),
                    scene.get('next_scene'),
                    json.dumps(scene.get('choices') or []),
                    scene.get('ending_type'),
                    int(scene.get('node_x') or 80), int(scene.get('node_y') or 60),
                    scene.get('reward_yuan'), scene.get('reward_roll_resets'),
                    json.dumps(scene.get('conditions') or []),
                )

    report['imported'] = True
    return web.json_response(report)

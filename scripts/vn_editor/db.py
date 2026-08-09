import asyncpg
from .config import DATABASE_URL

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        await _migrate(_pool)
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def _migrate(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS vn_arcs (
                id           SERIAL PRIMARY KEY,
                title        TEXT NOT NULL,
                description  TEXT NOT NULL DEFAULT '',
                status       TEXT NOT NULL DEFAULT 'draft',
                exclusive_char_id TEXT,
                created_at   BIGINT NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS vn_stories (
                id          TEXT PRIMARY KEY,
                arc_id      INTEGER REFERENCES vn_arcs(id) ON DELETE SET NULL,
                title       TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'draft',
                party_size  INTEGER NOT NULL DEFAULT 3,
                entry_scene TEXT NOT NULL DEFAULT 's1',
                test_party  JSONB NOT NULL DEFAULT '[]',
                created_at  BIGINT NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS vn_scenes (
                id            TEXT NOT NULL,
                story_id      TEXT NOT NULL REFERENCES vn_stories(id) ON DELETE CASCADE,
                label         TEXT NOT NULL DEFAULT 'New Scene',
                scene_type    TEXT NOT NULL DEFAULT 'story',
                bg_key        TEXT,
                chars         JSONB NOT NULL DEFAULT '[]',
                speaker       TEXT NOT NULL DEFAULT 'narrator',
                dialogue_text TEXT NOT NULL DEFAULT '',
                next_scene    TEXT,
                choices       JSONB NOT NULL DEFAULT '[]',
                ending_type   TEXT,
                node_x        INTEGER NOT NULL DEFAULT 80,
                node_y        INTEGER NOT NULL DEFAULT 60,
                PRIMARY KEY (id, story_id)
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS vn_backgrounds (
                id         SERIAL PRIMARY KEY,
                name       TEXT NOT NULL,
                r2_key     TEXT NOT NULL,
                public_url TEXT NOT NULL,
                category   TEXT NOT NULL DEFAULT 'misc',
                z_layer    INTEGER NOT NULL DEFAULT 0,
                created_at BIGINT NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS vn_ui_assets (
                id         SERIAL PRIMARY KEY,
                name       TEXT NOT NULL,
                r2_key     TEXT NOT NULL,
                public_url TEXT NOT NULL,
                category   TEXT NOT NULL DEFAULT 'dialogue',
                z_layer    INTEGER NOT NULL DEFAULT 2,
                created_at BIGINT NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT
            )
        ''')
        try:
            await conn.execute("ALTER TABLE vn_stories ADD COLUMN IF NOT EXISTS test_party JSONB NOT NULL DEFAULT '[]'")
        except Exception:
            pass
        # safe migrations for old installs
        for col, defn in [
            ('r2_key',     "TEXT NOT NULL DEFAULT ''"),
            ('public_url', "TEXT NOT NULL DEFAULT ''"),
            ('z_layer',    'INTEGER NOT NULL DEFAULT 0'),
            ('filename',   "TEXT NOT NULL DEFAULT ''"),
        ]:
            try:
                await conn.execute(f'ALTER TABLE vn_backgrounds ADD COLUMN IF NOT EXISTS {col} {defn}')
                await conn.execute(f'ALTER TABLE vn_ui_assets ADD COLUMN IF NOT EXISTS {col} {defn}')
            except Exception:
                pass
        for col, defn in [
            ('ui_asset_id', 'INTEGER'),
            ('ui_scale',    'REAL NOT NULL DEFAULT 1.0'),
            ('text_color',  "TEXT NOT NULL DEFAULT 'black'"),
            ('bg_blur',     'REAL NOT NULL DEFAULT 0'),
        ]:
            try:
                await conn.execute(f'ALTER TABLE vn_scenes ADD COLUMN IF NOT EXISTS {col} {defn}')
            except Exception:
                pass
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS vn_config (
                id                  INT PRIMARY KEY CHECK (id = 1),
                speaker_dx          INT NOT NULL DEFAULT 0,
                speaker_dy          INT NOT NULL DEFAULT 0,
                text_dx             INT NOT NULL DEFAULT 0,
                text_dy             INT NOT NULL DEFAULT 0,
                speaker_box         BOOLEAN NOT NULL DEFAULT TRUE,
                speaker_box_color   TEXT NOT NULL DEFAULT '#c0392b'
            )
        ''')
        for col, defn in [
            ('speaker_box',       'BOOLEAN NOT NULL DEFAULT TRUE'),
            ('speaker_box_color', "TEXT NOT NULL DEFAULT '#c0392b'"),
            ('speaker_font_size', 'INT NOT NULL DEFAULT 13'),
            ('text_font_size',    'INT NOT NULL DEFAULT 13'),
            ('ui_scale',          'REAL NOT NULL DEFAULT 1.0'),
            ('char_pad_top',      'INT NOT NULL DEFAULT 0'),
            ('char_scale',        'REAL NOT NULL DEFAULT 1.0'),
            ('text_area_w',       'INT NOT NULL DEFAULT 0'),
        ]:
            try:
                await conn.execute(f'ALTER TABLE vn_config ADD COLUMN IF NOT EXISTS {col} {defn}')
            except Exception:
                pass
        try:
            await conn.execute("ALTER TABLE vn_stories ADD COLUMN IF NOT EXISTS episode_number INT NOT NULL DEFAULT 1")
        except Exception:
            pass
        for col, defn in [
            ('reward_yuan',        'INTEGER'),
            ('reward_roll_resets', 'INTEGER'),
            ('conditions',         "JSONB NOT NULL DEFAULT '[]'"),
        ]:
            try:
                await conn.execute(f'ALTER TABLE vn_scenes ADD COLUMN IF NOT EXISTS {col} {defn}')
            except Exception:
                pass
        for col, defn in [
            ('featured_char_id', 'TEXT'),
            ('faction',          'TEXT'),
        ]:
            try:
                await conn.execute(f'ALTER TABLE vn_stories ADD COLUMN IF NOT EXISTS {col} {defn}')
            except Exception:
                pass
        try:
            await conn.execute(
                "ALTER TABLE gacha_characters ADD COLUMN IF NOT EXISTS vn_exclusive BOOLEAN NOT NULL DEFAULT FALSE"
            )
        except Exception:
            pass
    print('[db] VN tables ready')

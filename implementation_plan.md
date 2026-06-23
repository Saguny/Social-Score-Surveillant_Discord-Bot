# Multi-process scaling: sharded gateway + singleton scheduler + Redis state

## Order (each step unblocks the next; do not reorder)

1. `on_ready` sync fix (cheap, fixes rate-limit risk before scaling makes it worse)
2. Redis introduced as a dependency + connection helper
3. Singleton scheduler process extracted (decay, stocks tick, propaganda loop, posters, voting loops)
4. Gateway workers moved to `AutoShardedClient`, stripped of singleton jobs
5. Per-process in-memory dicts moved to Redis
6. Cross-shard reward dispatch (checkin/vote/achievements "every mutual guild")
7. Web dashboard decoupled into its own service, SSE/cache on Redis, sessions in Redis
8. Connection pool sizing + PgBouncer note

## 1. `on_ready` sync fix — [MODIFY] `bot.py`

Current (`bot.py:333-342` and the `on_guild_join` copy at `bot.py:~172`): every reconnect does
`for guild in self.guilds: tree.copy_global_to(guild); await tree.sync(guild)` serially. With
N gateway processes each doing this independently per shard reconnect, this hits the sync
rate limit harder, not less.

Change: sync once globally (`await self.tree.sync()`, no per-guild copy) on first boot only,
gated by a `guild_config`-adjacent flag or a simple `if not self._synced_once`. Per-guild instant
propagation on `on_guild_join` stays (single guild, cheap), but the blanket per-guild loop in
`on_ready` is removed — global commands propagate within an hour via Discord's own cache, which
is acceptable once you're not relying on instant per-guild sync for every reconnect.

If instant sync semantics must be preserved, the alternative is: only the scheduler process (see
step 3) performs the bulk on_ready sync, since gateway workers reconnecting on their shard range
don't need to re-sync commands global state has not changed.

## 2. Redis dependency — [MODIFY] `requirements.txt`, [NEW] `infra/redis_client.py`

Add `redis>=5.0.0` (async client, `redis.asyncio`). New module exposing a single
`get_redis() -> redis.asyncio.Redis` built from `REDIS_URL` env var, lazily connected, reused
pool — same pattern as `Database._pool`. All steps below depend on this existing first.

New env var: `REDIS_URL=redis://...`

## 3. Singleton scheduler process — [NEW] `scheduler.py`, [MODIFY] `bot.py`, `cogs/stocks.py`,
`cogs/propaganda.py`, `cogs/posters.py`, `cogs/voting.py`

Today a single process owns the gateway connection AND all `tasks.loop` background jobs:
`_decay_task` (`bot.py:123`), `StocksCog._tick` (`cogs/stocks.py:416`), the propaganda
close/conclude loop (`cogs/propaganda.py:23`), the daily poster broadcast
(`cogs/posters.py:61`), and `_check_reminders`/`_post_stats`/`_rotate_presence` in
`cogs/voting.py:177-178`. Running N gateway processes means N copies of each loop firing.

Plan: introduce a `RUN_MODE` env var (`gateway` | `scheduler`, default `gateway` for backward
compat in dev). `scheduler.py` is a new entry point that constructs a `discord.Client` (or reuses
`SocialCreditBot` with gateway intents disabled — needs a real Discord connection only because
several jobs send messages/embeds via channel objects; a `discord.Client` with `Intents.guilds`
plus `chunk_guilds_at_startup=False` is enough since the scheduler does not process gateway
events, only sends messages it initiates). It loads only the background-job cogs (`stocks` tick
loop, `propaganda` loop, `posters` loop, `voting`'s `_check_reminders`/`_post_stats`, and
`_decay_task`), never the message-handling cogs (`scoring`, `economy`, `social`, etc. stay
gateway-only). `_rotate_presence_task` also moves here since presence is a single global value,
not per-shard.

Gateway worker processes (`bot.py`'s existing entry point) drop the `asyncio.create_task` calls
for `_decay_task`/`_rotate_presence_task` (`bot.py:329-330`) and never load `StocksCog`'s tick
loop, `PropagandaCog`'s loop, or `PostersCog`'s loop's `.start()` — those cogs' command handlers
(`/stocks buy`, `/propaganda submit`, `ccp poster`) still load on every gateway worker since
users can run them from any shard; only the `tasks.loop` background job itself is
scheduler-exclusive. Practically: guard each `.start()` call behind
`if os.getenv("RUN_MODE") == "scheduler"`.

`web/server.py`'s startup (`bot.py:238`/`328`, `asyncio.create_task(start_web_server(bot))`)
also moves to be scheduler-owned in this step as an interim measure, ahead of step 7's full
decoupling, so it does not run once per gateway shard either.

## 4. `AutoShardedClient` for gateway workers — [MODIFY] `bot.py`

`SocialCreditBot(commands.Bot)` currently constructs a plain client. Switch the base/constructor
to pass `shard_count`/`shard_ids` so a single process can own a contiguous shard range
(`SHARD_COUNT` / `SHARD_IDS` env vars, comma-separated list for the latter), using
`commands.AutoShardedBot` in place of `commands.Bot` (drop-in superclass swap — same
`setup_hook`/`on_ready`/cog-loading code path, discord.py handles the multi-shard gateway
connections internally). This is what removes the ~2,500-guild single-shard ceiling: deploy
multiple gateway processes, each `RUN_MODE=gateway` with a disjoint `SHARD_IDS` range and a
shared `SHARD_COUNT`.

`CreditCommandTree`'s per-user cooldown (`_cmd_cooldowns`) and the ContextVar-setting logic stay
as-is structurally but the dict itself moves to Redis in step 5 since it's now shared across
shard processes that may both see the same user (DMs, or a user issuing commands while shard
processes restart independently).

## 5. In-memory dicts → Redis — [MODIFY] `cogs/scoring.py`, `bot.py`, `cogs/achievements.py`,
`database/_effects.py`

Six structures move from process-local dict to Redis-backed key/value, each with the same TTL
semantics it has today so behavior is unchanged, only the storage backend:

- `_effect_cache` (`database/_effects.py:12-38`, 30s TTL, keyed `(guild_id, user_id, effect_type)`)
  → `redis.set(key, value, ex=30)` / `redis.get(key)`; `invalidate_effect_cache` →
  `redis.delete(key)`. This one is already inside `database/db.py`'s class hierarchy
  (`EffectsMixin`), so it gets the Redis client injected alongside `self._pool`.
- `_lang_cache` (`cogs/scoring.py:56`, 1h TTL, keyed `(guild_id, user_id)`) → Redis with
  `ex=3600`, value is `lang` string only (the TTL replaces the manual `(lang, now)` tuple +
  `_clean_caches` sweep at `cogs/scoring.py:82-85`).
- `_pos_streaks` (`cogs/scoring.py:57`, no TTL, keyed `(guild_id, user_id)`) → Redis `INCR`/`SET`,
  no expiry (matches current unbounded lifetime).
- `_daily_tracking` (`cogs/scoring.py:58`, resets at UTC day boundary) → Redis hash per key with
  `ex` set to seconds-until-midnight-UTC on each write, simpler than the current manual
  `today_start` comparison sweep.
- `_cmd_cooldowns` (`bot.py:252`, 2s per-user cooldown) → Redis `SET key 1 NX EX 2`-style check,
  since this is checked on every single command/message and needs to stay sub-millisecond — a
  local Redis or Redis with low latency to the gateway processes is required here, this is the
  most latency-sensitive of the six.
- Achievement announce debounce queue (`cogs/achievements.py:16-18`,
  `_pending_ids`/`_pending_channel`/`_pending_tasks`) → this one is structurally different: it is
  not just state but also an `asyncio.Task` (the debounce sleep). Move to a Redis list
  (`RPUSH`/pending ids) plus a Redis-backed lock or a lightweight job: the debounce timer itself
  should be owned by the scheduler process (step 3), not by whichever gateway process happens to
  unlock the achievement — gateway workers `RPUSH` the achievement id and `SET` a
  `pending:{guild_id}:{user_id}` flag; the scheduler runs its own polling/pubsub loop watching
  for newly-set pending flags and flushes the announcement after the 2.0s debounce, since only
  the scheduler is guaranteed to be a single instance.

A small `RedisCache` helper (new, `infra/redis_cache.py`) wrapping `get`/`set ex=`/`delete` is
worth building once and reusing across all five TTL-style caches rather than hand-rolling Redis
calls five times.

## 6. Cross-shard reward dispatch — [MODIFY] `database/db.py` (`do_checkin`), `cogs/voting.py`
(`process_vote`), `cogs/achievements.py` (`_apply_rewards_everywhere`)

`do_checkin(user_id, guild_ids)` (caller: `cogs/checkin.py:22`, builds `guild_ids` from
`self.bot.guilds`), `process_vote`'s `_reward_guild` fan-out (`cogs/voting.py:125`,
`for guild in bot.guilds`), and `AchievementsCog._apply_rewards_everywhere`
(`cogs/achievements.py:53`) all assume the current process can see every guild the user shares
with the bot. Once guilds are split across shard processes by `AutoShardedClient`/multiple
processes, this is no longer true — a gateway process only sees its own shard's guilds.

Two pieces:

- **Guild ownership lookup**: there needs to be a way to ask "which gateway process owns guild
  X" or, more simply, "apply this reward to guild X" without needing to know which process owns
  it. Since `database/db.py`'s reward-writing methods (`tick_user`, `update_score`,
  `adjust_yuan`, etc.) already go straight to Postgres with no process-local state (per
  CLAUDE.md's existing note), the actual score/yuan writes do **not** need to move — any process
  can write to any guild's row directly via `bot.db`. The part that needs cross-process dispatch
  is only the *Discord-side* effects: sending a confirmation/announcement embed into a channel in
  guild X, which requires a real gateway connection to that guild's shard.
- **RPC hop**: introduce a Redis pub/sub channel (e.g. `guild-notify:{guild_id}`) that any
  process can publish to with a small payload (`{type: "checkin_reward", channel_id, embed_dict}`
  or similar); every gateway process subscribes to the channels for guilds in its own shard range
  and ignores messages for guilds it doesn't own (cheap `guild_id in self.bot.guilds` check after
  receiving, or a smarter shard-id filter to avoid every process receiving every message). The DB
  write that previously happened inline per-guild (`_apply_rewards_everywhere`'s per-guild
  yuan/score update, `_reward_guild`'s per-guild combo-bonus check) still happens wherever the
  triggering action originated, since that part is pure Postgres I/O; only the resulting Discord
  notification gets published for the owning shard to deliver.

This is the highest-risk step — it changes a currently-synchronous "did the reward apply"
guarantee into an eventually-consistent notify. Worth a dedicated test pass (mock Redis pub/sub)
before merging, not bundled into the same PR as steps 3-5.

## 7. Web dashboard decoupling — [NEW] `web_service.py` (or promote `web/server.py`'s
`start_web_server` to its own entry point), [MODIFY] `web/cache.py`, `web/sse.py`,
`web/server.py` (session auth)

- `StatCache` (`web/cache.py`) currently refreshes from `bot.db` directly inside the same
  process as the gateway connection it was originally bundled with (now the scheduler process,
  per step 3's interim move). Final state: a standalone `web_service.py` process that constructs
  its own `Database` instance (talks to Postgres directly, no `bot` object needed at all — every
  `StatCache` refresh method already calls `db.get_global_stats()`/`db.get_topgg_vote_timeline()`
  etc., never touches `bot.guilds` or Discord state) and its own Redis client.
- `SSEHub` (`web/sse.py`, `_clients: set[asyncio.Queue]`) → replace the in-process queue set with
  Redis pub/sub: `publish(event, data)` becomes `redis.publish(channel, json)`, and each dashboard
  replica's `/api/stream` handler subscribes to the same Redis channel instead of registering a
  local queue. This is what makes multiple dashboard replicas behind a load balancer see the same
  live feed.
- Session auth (`web/server.py`'s cookie-session check, currently invalidated on bot restart per
  CLAUDE.md) → store session tokens in Redis with an expiry instead of a process-local set/dict,
  so a restart of one dashboard replica doesn't invalidate sessions held by another, and so an
  admin-panel restart doesn't require restarting the bot (this also fully resolves once
  `web_service.py` is a separate process from the bot entirely — restarting it was already
  decoupled from the gateway by step 3's move, this step just removes the scheduler dependency
  too).
- The embed-broadcast and user-lookup admin endpoints (`web/server.py`'s
  `/api/admin/broadcast-embed`, `/api/admin/user-lookup`) are the one part of `web/server.py`
  that *does* need a live Discord connection (`bot.get_user()`, `channel.send()`). These move to
  publishing a Redis job (`admin-broadcast:{guild_id}` or `admin-broadcast:dm:{user_id}`) that the
  scheduler process (which still holds a `discord.Client`) picks up and executes, same RPC pattern
  as step 6. `web_service.py` itself never needs a discord.py client.

## 8. Connection pooling — [MODIFY] `database/db.py`, [NEW] `Procfile`/deploy config note

`asyncpg.create_pool(min_size=2, max_size=40)` (`database/db.py:218`) is per-process. Once
running N gateway processes + 1 scheduler + M dashboard replicas, total possible connections is
`(N+1+M) * 40`, which will exceed Postgres `max_connections` (typically 100-200 on
Railway-managed Postgres) well before N=3.

- Lower `max_size` per process role: gateway workers need far fewer connections than the
  scheduler (which runs the heavy daily aggregate queries) — e.g. `max_size=10` for gateway,
  `max_size=20` for scheduler, `max_size=10` per dashboard replica, tunable via a `DB_POOL_MAX`
  env var read in `Database.__init__` (already reads `DATABASE_URL` there per the existing
  CLAUDE.md note about `load_dotenv()` ordering — same place to add this).
- Recommend PgBouncer (transaction-mode pooling) in front of Postgres for the actual fix, since
  even tuned per-process limits get fragile as process count grows; this is a deploy-infra change
  (Railway plugin or sidecar), not application code — call this out in `CLAUDE.md`'s Environment
  section as a deployment prerequisite once step 3+ ships, rather than implementing it in Python.

## Explicitly out of scope / unchanged

- `CountersMixin`/`user_counters` and the rest of `database/db.py` — already Postgres-only, no
  process-local state, horizontally safe as-is.
- The sentiment `ProcessPoolExecutor` in `cogs/scoring.py` — correct to keep one pool per gateway
  worker; more shards/processes scales sentiment throughput for free, no change needed.

## Suggested PR split

1. PR 1 — `on_ready` fix (step 1), standalone, ships immediately, no Redis dependency.
2. PR 2 — Redis client + scheduler process extraction (steps 2-3), bot still single-shard.
3. PR 3 — `AutoShardedClient` + Redis-backed caches (steps 4-5), still single gateway process
   (`SHARD_IDS` covering all shards) to de-risk before going multi-process.
4. PR 4 — cross-shard reward dispatch (step 6), the highest-risk step, behind its own test pass.
5. PR 5 — web service decoupling (step 7).
6. PR 6 — pool sizing + PgBouncer deploy note (step 8), can land any time after PR 2.

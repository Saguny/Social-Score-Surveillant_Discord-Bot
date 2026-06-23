import os

RUN_MODE = os.getenv("RUN_MODE", "gateway")
IS_SCHEDULER = RUN_MODE == "scheduler"
IS_GATEWAY = RUN_MODE == "gateway"

_shard_count_env = os.getenv("SHARD_COUNT")
SHARD_COUNT = int(_shard_count_env) if _shard_count_env else None

_shard_ids_env = os.getenv("SHARD_IDS")
SHARD_IDS = [int(s) for s in _shard_ids_env.split(",") if s.strip()] if _shard_ids_env else None

# /state_report overhaul (final direction)

Superseded the original tabbed-leaderboard plan. User redirected: state_report should
mirror /daily_report's single-embed ANSI-table style, aggregated server-wide instead of
per-citizen.

## Implemented
- `database/_stats.py::get_guild_daily_report(guild_id)` replaces `get_guild_stats`.
  Two parallel queries: score_history today-vs-yesterday pos/neg sums + message-type
  counts + distinct active users today, and users table SUM(yuan)/SUM(prev_day_yuan)/
  COUNT(*) for guild citizens. Shape mirrors `get_daily_stats` but guild-wide (no
  user_id filter).
- `cogs/stats.py::state_report` rewritten as a single ANSI code-block embed, same
  GREEN/RED/GRAY color convention as `/daily_report`: SCORE GAINED/LOST/NET TODAY
  (vs yesterday), POSITIVE/NEGATIVE/NEUTRAL MSGS, ACTIVE CITIZENS (today/total),
  YUAN IN CIRC. (vs yesterday). Dropped the tabbed `StateReportView` entirely.

## Verified
- No existing tests reference `get_guild_stats` or `state_report`, nothing to update.
- Logic verified via standalone reproduction script against mock data.

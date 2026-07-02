# Social Credit Bot

A CCP-themed Discord social credit bot. Every message is silently evaluated. Rank changes trigger official bureau notifications. Made for fun.

> **DISCLAIMER:** This is a satirical meme project. It is not affiliated with, endorsed by, or representative of the Chinese Communist Party or the Chinese government. The creator does not support, condone, or endorse the human rights abuses, authoritarian policies, or surveillance practices of the CCP, including but not limited to the treatment of Uyghurs, Tibetans, Hong Kongers, and political dissidents, the Tiananmen Square massacre, or real-world social credit systems. This is a joke. The irony is the point.

**Invite:** [Add to your server](https://discord.com/oauth2/authorize?client_id=856163780265902151&permissions=2416438352&integration_type=0&scope=bot) · **Support:** [Support Server](https://discord.gg/k4W6YAPYhC) · **Prefix:** `ccp `

Built with discord.py 2.x · PostgreSQL (asyncpg) · vaderSentiment · langdetect · aiohttp · Redis · Deployed on Railway

---

## Social Credit Score

Everyone starts at **750**. Every message is silently evaluated for tone, structure, and content. Score changes are silent - rank changes are not.

- **Range:** 600 (floor) to 1300 (ceiling)
- **Execution threshold:** ≤ 610 - triggers the "Execution Date: Tomorrow" role, confiscates all Yuan and redistributes it to other guild members
- **Prestige:** reach 1290 and `/prestige` to reset for cosmetic stars

**Ranks**

| Range     | Rank                 |
| --------- | -------------------- |
| 600–699   | Enemy of the State   |
| 700–774   | Person of Interest   |
| 775–849   | Unremarkable Citizen |
| 850–924   | Compliant Citizen    |
| 925–999   | Model Citizen        |
| 1000–1099 | Party Loyalist       |
| 1100–1199 | Cadre Member         |
| 1200–1300 | General Secretary    |

Rank changes award or deduct Yuan automatically. Demotion requires a 1.0-point buffer below a threshold to prevent oscillation at boundaries.

---

## Scoring Rules

**Sentiment analysis** - each message is scored via VADER. Non-English messages are translated via Google Translate first. Positive and negative messages move your score; neutral messages award a small civic participation bonus (+0.03). Consecutive positive messages build a streak multiplier (up to ×1.5 at streak 15+).

**Banned topics** - counter-revolutionary speech (Tiananmen, Taiwan independence, Tibet, Xinjiang, Falun Gong, Hong Kong independence, etc.) is penalized immediately, regardless of tone.

**Structural penalties**

- Repeated message: −0.7
- Excessive caps (10+ char messages): −0.4

**Daily caps** - positive score gains diminish after a net +6.0 per day and are capped at +8.0. Negative score is never capped. Yuan per message also diminishes after 50 Yuan earned in a day.

**Score decay** - citizens inactive for more than 7 days are nudged toward 750 daily (−0.1).

**Defense effects** - `/buy` items like `exception`, `immunity`, `appeal`, `protection`, `legal_rep`, and `criticism` stack to reduce or block negative score events.

---

## Yuan Economy

- **10 Yuan** earned per message (diminishing after the daily threshold)
- **Support server members** earn a 15% yuan-per-message bonus
- **Wealth tax** - holdings above ¥100,000 are taxed 10% daily

**State Shop** - purchase with `/buy <item> [target]`

| Item           | Cost          | Effect                                                         |
| -------------- | ------------- | -------------------------------------------------------------- |
| `report`       | ¥500          | Dock a citizen 2 score points                                  |
| `denounce`     | ¥1,000        | Public condemnation with custom text (48h cooldown per target) |
| `inspection`   | ¥300          | DM alerts on a target's score changes for 24h                  |
| `rehabilitate` | ¥400+         | Recover 3 score points (cost doubles each use)                 |
| `expunge`      | ¥600          | Wipe your last 5 score changes from history                    |
| `freeze`       | ¥800          | Freeze your score for 1 hour                                   |
| `dispute`      | ¥450          | Contest your last penalty                                      |
| `exception`    | ¥1,200        | Block the next negative score event entirely                   |
| `immunity`     | ¥900          | 50% chance to fully block the next penalty                     |
| `appeal`       | ¥600          | Halve the next negative score event                            |
| `protection`   | ¥750          | Halve the next negative score event (stacks with appeal)       |
| `legal_rep`    | ¥2,000        | Passive - halves all incoming penalties while active           |
| `criticism`    | ¥500          | Passive - doubles all incoming penalties to a target           |
| `pact`         | ¥1,500        | Mutual score-protection agreement with another citizen         |
| `tip`          | ¥200          | Anonymous tip about a citizen                                  |
| Lottery tiers  | ¥500–¥250,000 | 70% lose · 20% win · 10% jackpot                               |

Most items can optionally target another citizen. Several items are gift-able.

---

## Features

**Daily check-in** - `/checkin` once per day for Yuan and score. Streak reward scales up to ¥2,000/day and +5.0 score at max streak. Applied across every server you share with the bot.

**Peer ratings** - `/endorse` or `/rebuke` a citizen ±1.5 score with an optional reason. 24h cooldown per target.

**Community fundraisers** - `/fundraise create` proposes a task for Yuan. Others donate. The organizer fulfills it, then the community votes to pay out or refund.

**Propaganda events** (mod) - `/propaganda start` opens a submission event. Citizens submit quotes; banned content earns a −5.0 penalty and event ban. After the window closes, submissions go to a reaction vote. The winner becomes a guild decree visible via `/decree`.

**Daily propaganda posters** - posted at 12:00 UTC in enabled channels. React with ❤️ for +3 score +¥250; react with 😡 for −1 score (defense effects apply). Sourced from [chineseposters.net](https://chineseposters.net).

**Top.gg voting** - `/vote` for Yuan and score rewards that scale with your vote streak, with weekend double rewards and a check-in combo bonus. Includes an optional DM reminder.

**Beijing Stock Exchange** - `/stocks` · real ADR stocks (via yfinance), one BSE ETF, and synthetic penny stocks. Turbo certificates (leveraged long/short with knockout barriers). Market hours enforced per exchange. Portfolio gains passively boost your social credit score daily.

**Achievements** - unlock badges and rewards for milestones across endorsements, check-ins, voting, stocks, streaks, and more. Rarity tiers: common, uncommon (reaction), rare (announce), legendary (meta). View with `/achievements`.

**Badges & cosmetics** - earn cosmetic badge suffixes from achievements, the shop, and voting. Pin a preferred badge with `/badge select`.

**Prestige** - reach score 1290 and `/prestige` to reset score and Yuan in the current server for cosmetic prestige stars (global counter).

**Server ranking** - `/serverrank` - guild-vs-guild leaderboard across 6 metrics: happiness, GDP, civic participation, literacy, incarceration rate, and politburo score. Bracket system: Hamlet -> Village -> Town -> City -> Metropolis.

**Privacy** - `/optout` atomically deletes all your data and blocks further data collection. `/optin` starts you fresh.

---

## Commands

**Citizen (slash)**

- `/score [citizen]` - current score and rank
- `/stats [citizen]` - full breakdown: trends, peak/low, streaks, lottery, economy
- `/leaderboard` - top/bottom score, economy, activity, social
- `/daily_report` - your score and yuan vs yesterday
- `/state_report` - server-wide summary
- `/shop` - browse shop items
- `/buy <item> [target] [text]` - purchase from the State Shop
- `/confess <text>` - public confession (cost scales with score gap, 1h cooldown)
- `/checkin` - daily check-in
- `/endorse <citizen> [reason]` / `/rebuke <citizen> [reason]` - peer ratings
- `/transfer <citizen> <amount>` / `/requestyuan <citizen> <amount>` - yuan transfers
- `/fundraise create/donate/complete/vote/list/info` - community fundraisers
- `/propaganda submit <text>` - submit to active propaganda event
- `/stocks buy/sell/portfolio/list` · `/turbos open/close/list` - stock exchange
- `/serverrank top/me/card/visibility` - guild leaderboard
- `/achievements` - view unlocked and locked achievements
- `/badge select/clear` - pin a cosmetic badge
- `/vote` - vote for the bot on top.gg for rewards
- `/prestige` - reset score for cosmetic prestige stars (requires 1290)
- `/optout` / `/optin` - data privacy
- `/decree` - receive an official proclamation
- `/guide` - full in-bot documentation
- `/disclaimer` · `/botinfo` · `/uptime` · `/ping` · `/credits` · `/invite`

**Moderator (prefix)**

- `ccp initialize` - register all current members
- `ccp adjust <@citizen> <delta> <reason>` - manual score adjustment
- `ccp reset <@citizen>` - reset to 750
- `ccp threshold <n>` - set fundraiser vote threshold
- `ccp executions [#channel]` - set execution announcement channel
- `ccp achievementnotification [on|off]` - toggle achievement announcements
- `ccp achievementchannel [#channel]` - set achievement announcement channel
- `ccp poster` - display a random propaganda poster
- `ccp posters [on|off]` - toggle daily poster broadcasts in this channel
- `ccp posterschannel [#channel]` - set dedicated poster broadcast channel
- `/propaganda start <submit_channel> <reveal_channel> <duration_hours>` - start a propaganda event
- `/serverrank visibility` - opt into the public server leaderboard

---

## Web Dashboard

A standalone public dashboard at port 8080. Live score feed, activity charts, economy stats, and a timeline - all fully anonymized (real Discord IDs replaced with stable pseudonyms).

The `/admin` panel (IP-allowlist + token gated) provides server management: manual score/yuan adjustments, bot sync, cog reload, user lookup, broadcast embeds, and a vote timeline chart.

---

## Self-Hosting

Requires Python 3.10+, PostgreSQL, and Redis.

```
DISCORD_TOKEN=...
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
ADMIN_TOKEN=...
PSEUDONYM_SALT=...          # random secret for anonymizing public dashboard IDs
PORT=8080
TOPGG_WEBHOOK_SECRET=...    # optional
TOPGG_TOKEN=...             # optional
ADMIN_ALLOWED_IPS=...       # optional, comma-separated IP allowlist for /admin
```

Run three processes:

```bash
python bot.py           # gateway - slash commands, message scoring
python scheduler.py     # scheduler - decay, daily jobs, background loops
python web_service.py   # web dashboard
```

On Railway, create three separate services pointing at the same repo. Set `RUN_MODE=scheduler` on the scheduler service. Attach the public domain to the web service only.

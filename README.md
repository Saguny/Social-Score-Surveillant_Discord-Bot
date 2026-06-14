# Social Score Surveillant - A Discord Bot

## DISCLAIMER

This bot is MAINLY proposed for english speaking guilds since Vader is only for english. Any non english message will be translated using googles api, I will possibly update one day to support all languages

This bot is a satirical meme project and is not affiliated with, endorsed by, or representative of the Chinese Communist Party or the Chinese government. The creator does not support, condone, or endorse the human rights abuses, authoritarian policies, or surveillance practices of the CCP, including but not limited to the treatment of Uyghurs, Tibetans, Hong Kongers, and political dissidents, the Tiananmen Square massacre, or real-world social credit systems. This is a joke. The irony is the point.

# Version Beta 1.0.2

This is a side project made for fun by me because me and a friend are flying to china this year and i was in the midst of reviving my old bot project from 2021, so i got enough motivation and a refresh of the discordpy library enough, that I just said "fuck it, im doing a ccp bot"
here we are

**Invite:** [https://discord.com/oauth2/authorize?client_id=856163780265902151&permissions=2416438352&integration_type=0&scope=bot](https://discord.com/oauth2/authorize?client_id=856163780265902151&permissions=2416036928&integration_type=0&scope=bot)

Built with discord.py 2.x · PostgreSQL (asyncpg) · vaderSentiment · langdetect · aiohttp · Deployed on Railway

Prefix: `ccp `

---

# About

A CCP-themed social credit bot for Discord. Every message is silently evaluated. Rank changes trigger official bureau notifications. Made for fun in small friend group servers.

`/guide` will be your best friend! it contains all information needed.

---

## Social Credit Score System

- Score range: 600 (floor) to 1300 (ceiling). Everyone starts at 750.
- Every message is evaluated for tone and structure. Score changes accumulate silently.
- Citizens inactive for more than 7 days have their score nudged toward 750 daily.

**Ranks**

| Range        | Rank                 |
| ------------ | -------------------- |
| 600 to 699   | Enemy of the State   |
| 700 to 774   | Person of Interest   |
| 775 to 849   | Unremarkable Citizen |
| 850 to 924   | Compliant Citizen    |
| 925 to 999   | Model Citizen        |
| 1000 to 1099 | Party Loyalist       |
| 1100 to 1199 | Cadre Member         |
| 1200 to 1300 | General Secretary    |

---

## Scoring Rules

**Sentiment Analysis** - each message is analyzed for tone. Max impact: +0.2 (positive) or -0.2 (negative). Neutral messages have no effect.

**Counter-Revolutionary Speech** - messages referencing banned topics (Tiananmen, Taiwan independence, Tibet, Xinjiang, Falun Gong, Hong Kong independence, etc.) are penalized -0.2 regardless of tone.

**Structural Penalties**

- Same message sent twice in a row: -1.0
- Excessive caps on messages 10+ characters: -0.2

---

## Features

**Yuan Economy**

- 1 Yuan earned per message automatically.
- `/checkin` - daily check-in for bonus Yuan and +0.2 score. Streak builds up to 150 Yuan/day.
- State Shop items purchasable with `/buy`:
  - `report` (500) - dock a citizen 2 score points
  - `denounce` (1000) - post a public custom condemnation (100 char max)
  - `surveillance` (300) - DM alerts on a target's score changes for 24h
  - `rehabilitate` (400+) - recover 3 score points; cost doubles each use
  - `expunge` (600) - wipe your last 5 score changes from public history
  - `freeze` (800) - freeze your score for 1 hour
  - `propaganda` (350) - bot posts a state-approved commendation of you

**Peer-to-Peer Ratings**

- `/endorse` / `/rebuke` - +/-3.0 score adjustment, one use per target per 24h, optional reason.

**Community Fundraisers**

- Citizens propose a task in exchange for Yuan. Others donate. Once funded, the organizer fulfills the task and opens a community vote. Confirm threshold = payout; deny threshold = full refund.

**Propaganda Events** (mod only)

- `/propaganda start` - open a submission event with a reveal channel and duration.
- `/propaganda submit` - citizens submit quotes. Banned content = -5.0 score + event ban.
- After the window closes, submissions are posted with reaction voting. Winner is enshrined as a guild decree via `/decree`.

**Daily Propaganda Posters**

- Posted at 12:00 UTC in enabled channels. React with heart for +1 score +20 Yuan, angry for -1 score.
- Posters sourced from [chineseposters.net](https://chineseposters.net)

**Web Dashboard**

- Auto-starts on port 8080. Accessible at `/` for public leaderboard (if webconsent is on) and `/admin` for server management. Both Protected by `ADMIN_TOKEN`.

---

## Commands

**Citizen**

- `/score [citizen]` - current score and rank
- `/stats [citizen]` - full breakdown: trends, peak/low, messages, check-in streak, propaganda wins
- `/history [citizen]` - last 5 score changes (mod required to view others)
- `/leaderboard` - 8 categories: top/bottom score, richest/poorest, most active, most endorsed, most rebuked, top informants
- `/state_report` - server-wide summary
- `/yuan` - Yuan balance and lifetime stats
- `/shop` - browse shop items
- `/buy <item> [target] [text]` - purchase from the State Shop
- `/confess <text>` - public confession; cost scales with score gap (200 to 750 Yuan), grants +0.5 on acceptance
- `/checkin` - daily check-in
- `/endorse <citizen> [reason]` / `/rebuke <citizen> [reason]` - peer ratings
- `/fundraise create/donate/complete/vote/list/info` - community fundraisers
- `/propaganda submit <text>` - submit to active propaganda event
- `/decree` - receive an official proclamation
- `/guide` - full in-bot documentation
- `/disclaimer` - legal and ethical disclaimer
- `/botinfo` · `/uptime` · `/ping` · `/credits`

**Moderator (prefix)**

- `ccp initialize` - register all current members
- `ccp adjust <@citizen> <delta> <reason>` - manual score adjustment
- `ccp reset <@citizen>` - reset to 750
- `ccp threshold <n>` - set fundraiser vote threshold (default 3)

- `ccp poster` - display a random propaganda poster
- `ccp posters` - toggle daily poster broadcasts in this channel
- `/propaganda start <submit_channel> <reveal_channel> <duration_hours>` - start a propaganda event

# Feature requests

Just message me on discord under `saguny` if you have any requests or changes or additions or whatever

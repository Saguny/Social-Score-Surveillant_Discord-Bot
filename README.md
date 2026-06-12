# Social Score Surveillant - A Discord Bot

## DISCLAIMER
This bot is MAINLY proposed for english speaking guilds since Vader is only for english. Any non english message will be translated using googles api, I will possibly update one day to support all languages

This bot is a satirical meme project and is not affiliated with, endorsed by, or representative of the Chinese Communist Party or the Chinese government.

The creator, I, does not support, condone, or endorse the human rights abuses, authoritarian policies, or surveillance practices of the CCP — including but not limited to the treatment of Uyghurs, Tibetans, Hong Kongers, and political dissidents, the Tiananmen Square massacre, or real-world social credit systems.

This is a joke. The irony is the point.

# Version Beta 1.0.1
This is the first release of the Social Score Surveillant Discord Bot, a side project made for fun by ✨ me ✨

Invite: https://discord.com/oauth2/authorize?client_id=856163780265902151&permissions=8&integration_type=0&scope=bot

# About
This is a fun and engaging Discord Bot made for the sole purpose of surveilling in small friend group servers and playing and trolling eachother.
It reads and scores every single message (besides attachments and links) through the usage of vaderSentiment (https://github.com/cjhutto/vadersentiment)
Vaders interpretation is then rounded to represent either a loss of .2 credits or a gain of .2 credits which will be added to the users social credit.
The Social Credit Score ranges from 600 to 1300, with 750 being the initial score
The Bot relies on a postgreSql database and is deployed on railway

prefix `ccp `

# Features
This bot is mainly designed to be a silent observer which sends updates when a new Rank has been achieved.
You can view your score using `ccp score`

`/guide` will be your best friend it contains all information needed

Social Credit Score System

    Automatic Tracking: Every message sent is silently evaluated for tone and structure to dynamically adjust user scores.

    Score Range: Operates on a strict floor of 600 to a ceiling of 1300. All citizens start at 750.

    Dynamic Ranks: Automatic rank promotions or demotions based on current credit brackets:

        600 to 699: Enemy of the State

        700 to 774: Person of Interest

        775 to 849: Unremarkable Citizen

        850 to 924: Compliant Citizen

        925 to 999: Model Citizen

        1000 to 1099: Party Loyalist

        1100 to 1199: Cadre Member

        1200 to 1300: General Secretary

Scoring & Structural Rules

    Sentiment Analysis: Automated tone evaluation nudges scores by up to +0.2 (positive) or -0.2 (negative) per message. Neutral messages have no effect.

    Anti-Spam & Formatting Penalties:

        Sending the exact same message twice in a row: -1.0

        Excessive capitalization on longer messages: -0.2

        Low-effort messages under 4 characters: -0.1

Yuan Economy & State Shop

    Passive Income: Users automatically earn 1 Yuan for every chat message sent.

    The State Shop: Spend accumulated Yuan on strategic utility actions:

        report (500 Yuan): Dock a targeted citizen's score by 2 points via official report.

        denounce (1000 Yuan): Broadcast a public, custom condemnation message (max 100 characters).

        surveillance (300 Yuan): Receive direct message notifications for every score change a target incurs over 24 hours.

        rehabilitate (400+ Yuan): Recover 3 score points (cost doubles with consecutive uses).

        expunge (600 Yuan): Wipe the last 5 score changes from public history.

        freeze (800 Yuan): Immune score changes for 1 hour.

        propaganda (350 Yuan): Force the bot to post a state-approved commendation of yourself in the channel.

Peer-to-Peer Social Ratings

    Endorsements: Grant a citizen a positive rating (+3.0 score adjustment). Limited to 1 use per target every 24 hours.

    Rebukes: Issue a negative rating against a citizen (-3.0 score adjustment). Limited to 1 use per target every 24 hours.

Community Fundraisers

    Allows citizens to propose tasks/goals in exchange for Yuan.

    Crowdfunding & Verification: Server members donate toward the goal. Once funded, the organizer must fulfill their promise, triggering a democratic community vote to either release the funds or refund the donors.

Commands
Citizen Commands

    /score [citizen] - View your own or another user's current score and rank.

    /stats [citizen] - Display a full breakdown including trends, peak/low scores, total messages, and report history.

    /history [citizen] - View the last 5 score changes (requires mod permissions to view others).

    /leaderboard - Display the top 3 most compliant citizens and the top 3 greatest threats.

    /state_report - Generates a server-wide summary (biggest rise/fall, top informant, total Yuan in circulation, and average score).

    /yuan - Check your current Yuan balance and lifetime earned/spent statistics.

    /shop - Browse available shop items and costs.

    /buy <item> [target] [text] - Purchase an item or action from the State Shop.

Peer-to-Peer Commands

    /endorse <citizen> [reason] - Positively rate a fellow citizen.

    /rebuke <citizen> [reason] - Negatively rate a fellow citizen.

Fundraiser Commands

    /fundraise create <goal> <description> - Create an open community goal and set a target funding amount.

    /fundraise donate <id> <amount> - Donate Yuan toward an active fundraiser.

    /fundraise complete <id> - Mark a funded goal as complete to open the community voting phase.

    /fundraise vote <id> <confirm|deny> - Vote on whether the organizer successfully fulfilled their obligation.

    /fundraise list - List all active fundraisers running in the server.

    /fundraise info <id> - View comprehensive details and live vote counts for a specific fundraiser.

Moderator Commands (Prefix)

    Note: These are chat-prefix commands handled directly in text channels.

    ccp initialize - Registers all existing server members into the database.

    ccp adjust <@citizen> <delta> <reason> - Manually adjust a citizen's score by any positive or negative integer.

    ccp reset <@citizen> - Hard reset a citizen's standing back to the default 750.

    ccp threshold <n> - Adjust the minimum required votes needed to resolve a fundraiser (Default is 3).

    ccp webconsent <on|off> - Enable or disable message content logging for the external web dashboard*.

    ccp posters - enabled propaganda posters with reactions to either earn score and yuan or lose score. at 12 UTC
    powered by https://chineseposters.net



--------------------------------
*This is a deprecated local use feature for me to debug the message scoring, will be removed in future updates





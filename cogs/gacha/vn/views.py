from __future__ import annotations
import random
import discord
from database._vn import PARTY_SIZE

_STAT_EMOJI = {"military": "⚔️", "authority": "👑", "charisma": "💬"}
_STAT_KEY   = {"military": "stat_military", "authority": "stat_authority", "charisma": "stat_charisma"}

# Character stats run 0-100 (the admin editor's sliders), so a full party tops
# out at PARTY_SIZE * 100. Scaling against that means an average party lands
# mid-curve; the previous flat 150 put a party of three average characters at
# the cap, which made every party above "completely average" identical.
_STAT_MAX   = PARTY_SIZE * 100
_MOD_MAX    = 10
_DEFAULT_DC = 14

# Suggested difficulties, quoted as the success chance for an average party
# (+5 from stats, no bonuses). A strong party with both bonuses adds up to +9
# on top of that, which is what makes collection worth doing.
DC_TIERS = {
    "trivial": 8,    # ~90%
    "easy":    11,   # ~75%
    "medium":  14,   # ~60%
    "hard":    18,   # ~40%
    "brutal":  22,   # ~20%
}


def _roll_choice(
    choice: dict,
    party_chars: list,
    bonus: int = 0,
    bonus_labels: list | None = None,
) -> tuple[str, str, bool]:
    stat     = choice.get("stat") or ""
    dc       = int(choice.get("difficulty") or _DEFAULT_DC)
    stat_key = _STAT_KEY.get(stat)

    total_stat = 0
    if stat_key:
        for ch in party_chars:
            if ch:
                total_stat += ch.get(stat_key) or 0

    stat_mod = round(min(total_stat, _STAT_MAX) / _STAT_MAX * _MOD_MAX)
    modifier = stat_mod + bonus
    roll     = random.randint(1, 20)
    result   = roll + modifier
    passed   = result >= dc

    emoji   = _STAT_EMOJI.get(stat, "🎲")
    outcome = "PASS" if passed else "FAIL"
    text    = f"{emoji} Rolled **{roll}** + {modifier} = **{result}** · needed {dc} · {outcome}"
    if bonus_labels:
        text += "\n" + " · ".join(bonus_labels)

    next_scene = choice.get("pass_scene") if passed else choice.get("fail_scene")
    return next_scene, text, passed


def _vncid(*parts) -> str:
    return "vn:" + ":".join(str(p) for p in parts)


# ── Story player view ─────────────────────────────────────────────────────────

class VNView(discord.ui.View):
    """
    Persistent render-only view. timeout=None so buttons survive bot restarts.
    All interaction handling is done by VNCog.on_interaction via custom_id routing.
    """
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        story_id: str,
        scene: dict,
        next_story_id: str | None = None,
        endings_left: int = 0,
    ):
        super().__init__(timeout=None)
        self.guild_id      = guild_id
        self.user_id       = user_id
        self.story_id      = story_id
        self.scene         = scene
        self.next_story_id = next_story_id
        self.endings_left  = endings_left
        self._build()

    def _build(self):
        self.clear_items()
        scene_type = self.scene.get("scene_type", "story")
        scene_id   = self.scene.get("id", "")
        uid        = self.user_id
        sid        = self.story_id

        self.add_item(discord.ui.Button(
            label="✕ Quit",
            style=discord.ButtonStyle.danger,
            custom_id=_vncid("quit", uid),
        ))

        if scene_type == "story":
            next_id = self.scene.get("next_scene")
            self.add_item(discord.ui.Button(
                label="Next →",
                style=discord.ButtonStyle.primary,
                disabled=not next_id,
                custom_id=_vncid("next", sid, next_id or "_", uid),
            ))

        elif scene_type == "choice":
            choices = self.scene.get("choices") or []
            for i, ch in enumerate(choices[:5]):
                stat  = ch.get("stat") or ""
                emoji = _STAT_EMOJI.get(stat, "")
                text  = ch.get("text") or f"Choice {i + 1}"
                label = f"{emoji} {text}" if emoji else text
                self.add_item(discord.ui.Button(
                    label=label[:80],
                    style=discord.ButtonStyle.secondary,
                    custom_id=_vncid("ch", sid, scene_id, i, uid),
                    row=(i // 3) + 1,
                ))

        elif scene_type == "ending":
            if self.next_story_id:
                self.add_item(discord.ui.Button(
                    label="Next Ep → · 🎫 1 ticket",
                    style=discord.ButtonStyle.success,
                    custom_id=_vncid("ep", self.next_story_id, uid),
                ))
            if self.endings_left > 0:
                plural = "s" if self.endings_left != 1 else ""
                replay_label = f"▶ Play Again · {self.endings_left} ending{plural} left"
                replay_style = discord.ButtonStyle.primary
            else:
                replay_label = "▶ Play Again"
                replay_style = discord.ButtonStyle.secondary
            self.add_item(discord.ui.Button(
                label=replay_label,
                style=replay_style,
                custom_id=_vncid("replay", sid, uid),
            ))


# ── Party editor view ─────────────────────────────────────────────────────────

def build_party_embed(party: list, harem: list) -> discord.Embed:
    char_map = {ch["character_id"]: ch for ch in harem}
    lines     = []
    thumb_url = None
    totals    = {"military": 0, "authority": 0, "charisma": 0}
    filled    = 0

    for i in range(PARTY_SIZE):
        cid = party[i] if i < len(party) else None
        if cid and cid in char_map:
            ch     = char_map[cid]
            title  = ch.get("title") or ""
            suffix = f" · *{title}*" if title else ""
            lines.append(f"**Slot {i + 1}** — **{ch['name']}**{suffix}")
            if thumb_url is None:
                imgs = ch.get("image_urls") or []
                if imgs:
                    thumb_url = imgs[0]
            totals["military"]  += ch.get("stat_military")  or 0
            totals["authority"] += ch.get("stat_authority") or 0
            totals["charisma"]  += ch.get("stat_charisma")  or 0
            filled += 1
        else:
            lines.append(f"**Slot {i + 1}** — *empty*")

    embed = discord.Embed(title="Your VN Party", description="\n".join(lines), color=0xc0392b)
    if thumb_url:
        embed.set_thumbnail(url=thumb_url)
    if filled:
        embed.add_field(
            name="PARTY STATS",
            value=(
                f"⚔️ Military **{totals['military']}** · "
                f"👑 Authority **{totals['authority']}** · "
                f"💬 Charisma **{totals['charisma']}**"
            ),
            inline=False,
        )
    embed.set_footer(text="Changes save immediately · party applies to all stories in an arc")
    return embed


class VNPartyView(discord.ui.View):
    """
    Persistent party-editor view. Selects use custom_ids so interactions survive
    bot restarts and are routed to VNCog.on_interaction.
    """
    def __init__(self, guild_id: int, user_id: int, party: list, harem: list):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.user_id  = user_id
        self.party    = list(party)
        self.harem    = harem
        while len(self.party) < PARTY_SIZE:
            self.party.append(None)
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        for slot in range(PARTY_SIZE):
            self.add_item(self._make_select(slot))

    def _make_select(self, slot: int) -> discord.ui.Select:
        current = self.party[slot] if slot < len(self.party) else None

        ph_name = "Empty"
        for ch in self.harem:
            if ch["character_id"] == current:
                ph_name = ch["name"]
                break

        options = [discord.SelectOption(
            label="— Empty slot —",
            value="__empty__",
            default=(current is None),
        )]
        for ch in self.harem[:24]:
            cid  = ch["character_id"]
            desc = (ch.get("title") or ch.get("rarity") or "")[:100]
            options.append(discord.SelectOption(
                label=ch.get("name", cid)[:100],
                value=cid,
                description=desc or None,
                default=(cid == current),
            ))

        return discord.ui.Select(
            placeholder=f"Slot {slot + 1} · {ph_name}",
            options=options,
            custom_id=_vncid("pslot", slot, self.guild_id, self.user_id),
            row=slot,
        )

import asyncio
import traceback

import discord
from discord import app_commands
from discord.ext import commands

from cogs.achievements import unlock as unlock_achievement, check_milestone
from database._vn import PARTY_SIZE
from .render   import build_scene_render
from .runstate import apply_effects, choice_effects, party_bonuses, resolve_scene
from .views    import VNView, VNPartyView, build_party_embed, _roll_choice

_VN_TICKET_KEY      = "vn:tickets"
_VN_ROLL_RESET_KEY  = "vn:roll_resets"

_REWARD_YUAN_GOOD        = 750
_REWARD_YUAN_NORMAL      = 500
_REWARD_YUAN_NEW_ENDING  = 250
_REWARD_YUAN_REPLAY      = 100
_REWARD_ROLL_RESETS      = 1
_REWARD_ALL_ENDINGS_RR   = 1


class VNCog(commands.Cog, name="VN"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _ending_name(scene: dict) -> str:
        label = (scene.get("label") or "").strip()
        if label and label != "New Scene":
            return label
        return f"{(scene.get('ending_type') or 'normal').upper()} ENDING"

    @staticmethod
    def _rarity_line(discoverers: int, players: int, own_collection: bool = False) -> str | None:
        if discoverers <= 1:
            return "only you have found this" if own_collection else "First on this server to find it."
        if players <= 0:
            return None
        pct = discoverers / players * 100
        return f"{discoverers} of {players} players here have found this · {pct:.0f}%"

    async def _announce_ending(
        self,
        interaction: discord.Interaction,
        story: dict,
        scene: dict,
        seen: int,
        total: int,
    ) -> None:
        channel = interaction.channel
        if channel is None:
            return

        discoverers, players = await self.bot.db.get_vn_ending_rarity(
            interaction.guild.id, story["id"], scene["id"]
        )

        embed = discord.Embed(
            title="Ending Discovered",
            description=f"{interaction.user.mention} reached a new ending in **{story['title']}**.",
            color=0xFFD700,
        )
        embed.add_field(name="ENDING", value=f"||{self._ending_name(scene)}||", inline=False)
        if total:
            embed.add_field(name="COLLECTION", value=f"**{seen}/{total}** endings discovered", inline=True)

        rarity = self._rarity_line(discoverers, players)
        if rarity:
            embed.add_field(name="RARITY", value=rarity, inline=False)
        embed.timestamp = discord.utils.utcnow()

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _load_party_chars(self, party_ids: list) -> list:
        by_id = await self.bot.db.get_vn_party_chars(party_ids)
        return [by_id.get(cid) if cid else None for cid in party_ids]

    async def _resolve(self, story_id: str, scene_id: str, run_vars: dict):
        """Follow routers from scene_id to the next scene that actually renders."""
        return await resolve_scene(self.bot.db.get_vn_scene, story_id, scene_id, run_vars)

    async def _build_view(
        self,
        guild_id: int,
        user_id: int,
        story: dict,
        scene: dict,
        party_chars: list | None = None,
        endings_left: int = 0,
    ) -> VNView:
        next_story_id = None
        if scene.get("scene_type") == "ending" and story.get("arc_id"):
            nxt = await self.bot.db.get_next_arc_episode(
                story["arc_id"], story.get("episode_number", 1)
            )
            if nxt:
                next_story_id = nxt["id"]

        return VNView(
            guild_id, user_id, story["id"], scene,
            next_story_id=next_story_id,
            endings_left=endings_left,
        )

    async def _give_episode_reward(
        self,
        guild_id: int,
        user_id: int,
        story: dict,
        scene: dict,
    ) -> dict:
        ending_type = scene.get("ending_type") or "normal"
        story_id    = story["id"]

        is_new_ending, is_first = await asyncio.gather(
            self.bot.db.record_vn_ending(guild_id, user_id, story_id, scene["id"], ending_type),
            self.bot.db.vn_complete_episode(guild_id, user_id, story_id, ending_type, scene["id"]),
        )
        seen, total = await asyncio.gather(
            self.bot.db.count_vn_endings_seen(guild_id, user_id, story_id),
            self.bot.db.count_story_endings(story_id),
        )
        completed_set = is_new_ending and not is_first and total > 0 and seen >= total

        if is_first:
            default_yuan = _REWARD_YUAN_GOOD if ending_type == "good" else _REWARD_YUAN_NORMAL
            yuan         = scene["reward_yuan"]        if scene.get("reward_yuan")        is not None else default_yuan
            roll_resets  = scene["reward_roll_resets"] if scene.get("reward_roll_resets") is not None else _REWARD_ROLL_RESETS
        elif is_new_ending:
            yuan        = _REWARD_YUAN_NEW_ENDING
            roll_resets = 0
        else:
            yuan        = _REWARD_YUAN_REPLAY
            roll_resets = 0

        if completed_set:
            roll_resets += _REWARD_ALL_ENDINGS_RR

        await self.bot.db.adjust_yuan(guild_id, user_id, yuan)
        if roll_resets:
            await self.bot.db.increment_counter(user_id, _VN_ROLL_RESET_KEY, roll_resets)

        return {
            "yuan":          yuan,
            "roll_resets":   roll_resets,
            "is_first":      is_first,
            "is_new_ending": is_new_ending,
            "completed_set": completed_set,
            "seen":          seen,
            "total":         total,
        }

    async def _deliver_scene(
        self,
        interaction: discord.Interaction,
        story: dict,
        scene: dict,
        party_chars: list,
        edit: bool = False,
        roll_text: str | None = None,
        run_vars: dict | None = None,
    ) -> None:
        guild_id = interaction.guild.id
        user_id  = interaction.user.id

        reward_text: str | None = roll_text
        endings_left = 0
        r: dict | None = None
        if scene.get("scene_type") == "ending":
            await self.bot.db.end_vn_run(guild_id, user_id, story["id"])
            r = await self._give_episode_reward(guild_id, user_id, story, scene)
            endings_left = max(0, r["total"] - r["seen"])
            ending_type_str = scene.get("ending_type") or "normal"
            et = ending_type_str.upper()

            parts = [f"¥{r['yuan']:,}"]
            if r["roll_resets"]:
                plural = "s" if r["roll_resets"] != 1 else ""
                parts.append(f"+{r['roll_resets']} roll reset ticket{plural}")

            if r["is_first"]:
                headline = f"**{et} ENDING**"
            elif r["is_new_ending"]:
                headline = f"**NEW ENDING** · {et}"
            else:
                headline = f"**{et} ENDING** · already found"

            lines = [f"{headline} · " + " · ".join(parts)]
            if r["total"]:
                lines.append(f"ENDINGS FOUND **{r['seen']}/{r['total']}**")
            if r["completed_set"]:
                lines.append("**ALL ENDINGS FOUND** for this episode")

            ending_line = "\n".join(lines)
            reward_text = f"{roll_text}\n{ending_line}" if roll_text else ending_line

            if r["is_first"]:
                episodes_done = await self.bot.db.increment_counter(user_id, "vn_episodes_completed")
                await asyncio.gather(
                    unlock_achievement(self.bot, interaction.guild, interaction.user, "vn_first_episode", channel=interaction.channel),
                    check_milestone(self.bot, interaction.guild, interaction.user, "vn_episodes_completed", episodes_done, channel=interaction.channel),
                )
                if ending_type_str == "good":
                    await unlock_achievement(self.bot, interaction.guild, interaction.user, "vn_good_ending", channel=interaction.channel)
                elif ending_type_str == "bad":
                    await unlock_achievement(self.bot, interaction.guild, interaction.user, "vn_bad_ending", channel=interaction.channel)
                arc_id = story.get("arc_id")
                if arc_id:
                    all_done = await self.bot.db.vn_arc_all_complete(guild_id, user_id, arc_id)
                    if all_done:
                        await unlock_achievement(self.bot, interaction.guild, interaction.user, "vn_arc_complete", channel=interaction.channel)
                        arc     = await self.bot.db.get_vn_arc(arc_id)
                        excl_id = arc.get("exclusive_char_id") if arc else None
                        if excl_id:
                            char   = await self.bot.db.get_gacha_character(excl_id)
                            is_new = await self.bot.db.claim_character(guild_id, user_id, excl_id)
                            if char:
                                reward_text = (reward_text + "\n") if reward_text else ""
                                name = char.get("name", excl_id)
                                if is_new:
                                    reward_text += f"🌟 **ARC COMPLETE** · **{name}** has joined your collection!"
                                else:
                                    reward_text += f"🌟 **ARC COMPLETE** · You already have **{name}**."

        file, embed = await build_scene_render(self.bot.db, story, scene, party_chars, reward_text=reward_text)
        view        = await self._build_view(
            guild_id, user_id, story, scene,
            party_chars=party_chars, endings_left=endings_left,
        )

        if edit:
            await interaction.edit_original_response(attachments=[file], embed=embed, view=view)
        else:
            await interaction.followup.send(file=file, embed=embed, view=view)

        if r and r["is_new_ending"]:
            await self._announce_ending(interaction, story, scene, r["seen"], r["total"])

    # ── persistent interaction handler ────────────────────────────────────────

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        cid = interaction.data.get("custom_id", "")
        if not cid.startswith("vn:"):
            return

        parts  = cid.split(":")
        action = parts[1] if len(parts) > 1 else ""

        try:
            if action == "quit":
                # vn:quit:{user_id}
                if len(parts) < 3:
                    return
                if interaction.user.id != int(parts[2]):
                    await interaction.response.send_message("This isn't your story!", ephemeral=True)
                    return
                await interaction.response.edit_message(view=discord.ui.View())

            elif action == "next":
                # vn:next:{story_id}:{next_scene_id}:{user_id}
                if len(parts) < 5:
                    return
                if interaction.user.id != int(parts[4]):
                    await interaction.response.send_message("This isn't your story!", ephemeral=True)
                    return
                await self.advance_to_scene(interaction, parts[2], parts[3])

            elif action == "ch":
                # vn:ch:{story_id}:{scene_id}:{choice_idx}:{user_id}
                if len(parts) < 6:
                    return
                if interaction.user.id != int(parts[5]):
                    await interaction.response.send_message("This isn't your story!", ephemeral=True)
                    return
                await interaction.response.defer()

                story_id   = parts[2]
                scene_id   = parts[3]
                choice_idx = int(parts[4])
                guild_id   = interaction.guild.id
                user_id    = interaction.user.id

                scene = await self.bot.db.get_vn_scene(story_id, scene_id)
                if not scene:
                    await interaction.followup.send("Scene not found.", ephemeral=True)
                    return
                choices = scene.get("choices") or []
                if choice_idx >= len(choices):
                    await interaction.followup.send("Invalid choice.", ephemeral=True)
                    return
                choice = choices[choice_idx]

                story       = await self.bot.db.get_vn_story(story_id)
                guild_party = await self.bot.db.get_vn_party(guild_id, user_id)
                party_ids   = guild_party[:story["party_size"]]
                party_chars = await self._load_party_chars(party_ids)

                run      = await self.bot.db.get_active_vn_run(guild_id, user_id, story_id)
                run_vars = (run or {}).get("vars") or {}

                bonus, labels = party_bonuses(story, party_chars, choice)
                next_scene, roll_text, passed = _roll_choice(choice, party_chars, bonus, labels)
                if not next_scene:
                    await interaction.followup.send("This choice isn't connected yet.", ephemeral=True)
                    return

                run_vars = apply_effects(run_vars, choice_effects(choice, passed))
                await self.advance_to_scene(
                    interaction, story_id, next_scene,
                    roll_text=roll_text, run_vars=run_vars, _deferred=True,
                )

            elif action == "ep":
                # vn:ep:{next_story_id}:{user_id}
                if len(parts) < 4:
                    return
                if interaction.user.id != int(parts[3]):
                    await interaction.response.send_message("This isn't your story!", ephemeral=True)
                    return
                await interaction.response.defer()
                await self.start_story(interaction, parts[2], edit=True)

            elif action == "replay":
                # vn:replay:{story_id}:{user_id}
                if len(parts) < 4:
                    return
                if interaction.user.id != int(parts[3]):
                    await interaction.response.send_message("This isn't your story!", ephemeral=True)
                    return
                await interaction.response.defer()
                await self.start_story(interaction, parts[2], edit=True, force_restart=True)

            elif action == "pslot":
                # vn:pslot:{slot}:{guild_id}:{user_id}
                if len(parts) < 5:
                    return
                slot     = int(parts[2])
                guild_id = int(parts[3])
                user_id  = int(parts[4])
                if interaction.user.id != user_id:
                    await interaction.response.send_message("This isn't your party!", ephemeral=True)
                    return

                chosen = interaction.data["values"][0]
                party  = await self.bot.db.get_vn_party(guild_id, user_id)
                while len(party) < PARTY_SIZE:
                    party.append(None)
                party[slot] = None if chosen == "__empty__" else chosen
                await self.bot.db.set_vn_party(guild_id, user_id, party)
                harem = await self.bot.db.get_harem_for_party(guild_id, user_id)
                await interaction.response.edit_message(
                    embed=build_party_embed(party, harem),
                    view=VNPartyView(guild_id, user_id, party, harem),
                )

        except Exception:
            traceback.print_exc()
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("An error occurred.", ephemeral=True)
                else:
                    await interaction.followup.send("An error occurred.", ephemeral=True)
            except Exception:
                pass

    # ── /party ────────────────────────────────────────────────────────────────

    @app_commands.command(name="party", description="View and edit your VN party")
    async def slash_party(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        user_id  = interaction.user.id

        harem = await self.bot.db.get_harem_for_party(guild_id, user_id)
        if not harem:
            await interaction.followup.send(
                "You don't have any characters yet! Use `/roll` to get some.",
                ephemeral=True,
            )
            return

        party = await self.bot.db.get_vn_party(guild_id, user_id)
        await interaction.followup.send(
            embed=build_party_embed(party, harem),
            view=VNPartyView(guild_id, user_id, party, harem),
            ephemeral=True,
        )

    # ── /vn ───────────────────────────────────────────────────────────────────

    vn = app_commands.Group(name="vn", description="Play visual novel arcs with your gacha party")

    @vn.command(name="play", description="Start a VN arc")
    @app_commands.describe(arc_id="Arc to play")
    async def vn_play(self, interaction: discord.Interaction, arc_id: str | None = None):
        await interaction.response.defer()

        if arc_id is None:
            arcs = await self.bot.db.get_vn_arcs_progress(interaction.guild.id, interaction.user.id)
            if not arcs:
                await interaction.followup.send(
                    "No arcs are available yet. Check back soon!", ephemeral=True
                )
                return
            tickets = await self.bot.db.get_counter(interaction.user.id, _VN_TICKET_KEY) or 0
            lines   = []
            for a in arcs:
                ep_count  = a.get("episode_count", 0)
                done      = a.get("completed_count", 0)
                ep_label  = f"{done}/{ep_count} episode{'s' if ep_count != 1 else ''}"
                bits      = [ep_label]
                if a.get("endings_total"):
                    bits.append(f"{a['endings_seen']}/{a['endings_total']} endings")
                lines.append(
                    f"**`{a['id']}`** · {a['title']} · *{' · '.join(bits)}*\n{a.get('description') or ''}"
                )
            embed = discord.Embed(
                title="Available Arcs",
                description="\n\n".join(lines),
                color=0xc0392b,
            )
            embed.set_footer(text=f"🎫 {tickets} VN ticket{'s' if tickets != 1 else ''} · /vn play <arc> to start · /vn progress for detail")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        await self.start_arc(interaction, int(arc_id))

    @vn_play.autocomplete("arc_id")
    async def _arc_ac(self, interaction: discord.Interaction, current: str):
        arcs = await self.bot.db.get_vn_arcs_with_stories()
        return [
            app_commands.Choice(name=a["title"], value=str(a["id"]))
            for a in arcs
            if current.lower() in a["title"].lower()
        ][:25]

    @vn.command(name="endings", description="Your ending collection and how rare each one is")
    async def vn_endings(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        rows = await self.bot.db.get_vn_ending_catalog(interaction.guild.id, interaction.user.id)
        if not rows:
            await interaction.followup.send(
                "No episodes with endings are published yet.", ephemeral=True
            )
            return

        by_story: dict[str, list] = {}
        for row in rows:
            by_story.setdefault(row["story_id"], []).append(row)

        embed = discord.Embed(
            title="Your Ending Collection",
            description="Endings you haven't reached yet stay hidden.",
            color=0xc0392b,
        )

        found_total = len(rows)
        found_mine  = 0

        for story_rows in list(by_story.values())[:25]:
            first = story_rows[0]
            lines = []
            for i, row in enumerate(story_rows, 1):
                if row["found"]:
                    found_mine += 1
                    rarity = self._rarity_line(row["discoverers"], row["players"], own_collection=True)
                    detail = f" · *{rarity}*" if rarity else ""
                    lines.append(f"`{i}` **{self._ending_name(row)}**{detail}")
                else:
                    lines.append(f"`{i}` ???")
            mine  = sum(1 for r in story_rows if r["found"])
            title = f"Ep {first['episode_number']} · {first['story_title']} · {mine}/{len(story_rows)}"
            embed.add_field(name=title[:256], value="\n".join(lines)[:1024], inline=False)

        embed.set_footer(text=f"{found_mine}/{found_total} endings discovered · /vn play to hunt the rest")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @vn.command(name="progress", description="See how far you've gotten and which endings you've found")
    async def vn_progress(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        user_id  = interaction.user.id

        arcs = await self.bot.db.get_vn_arcs_progress(guild_id, user_id)
        if not arcs:
            await interaction.followup.send("No arcs are available yet.", ephemeral=True)
            return

        tickets, by_arc = await asyncio.gather(
            self.bot.db.get_counter(user_id, _VN_TICKET_KEY),
            self.bot.db.get_vn_episode_progress(guild_id, user_id, [a["id"] for a in arcs]),
        )

        embed = discord.Embed(title="Your VN Progress", color=0xc0392b)
        total_seen = total_endings = 0

        for arc in arcs:
            episodes = by_arc.get(arc["id"], [])
            rows = []
            for ep in episodes:
                mark  = "✓" if ep["completed"] else "·"
                label = f"Ep {ep['episode_number']} · {ep['title']}"
                if ep["endings_total"]:
                    total_seen    += ep["endings_seen"]
                    total_endings += ep["endings_total"]
                    label += f" · {ep['endings_seen']}/{ep['endings_total']} endings"
                rows.append(f"`{mark}` {label}")

            done = arc.get("completed_count", 0)
            head = f"{done}/{arc.get('episode_count', 0)} complete"
            if arc.get("endings_total"):
                head += f" · {arc['endings_seen']}/{arc['endings_total']} endings"
            rows.insert(0, f"*{head}*")

            embed.add_field(name=arc["title"], value="\n".join(rows)[:1024], inline=False)

        summary = f"🎫 {tickets or 0} ticket{'s' if (tickets or 0) != 1 else ''}"
        if total_endings:
            summary += f" · {total_seen}/{total_endings} endings found overall"
        embed.set_footer(text=f"{summary} · replay for endings you haven't seen")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── internal flow ─────────────────────────────────────────────────────────

    async def start_arc(self, interaction: discord.Interaction, arc_id: int):
        guild_id = interaction.guild.id
        user_id  = interaction.user.id

        stories = await self.bot.db.get_vn_arc_stories(arc_id)
        if not stories:
            await interaction.followup.send("This arc has no published episodes yet.", ephemeral=True)
            return

        completions  = await asyncio.gather(
            *(self.bot.db.get_vn_completion(guild_id, user_id, s["id"]) for s in stories)
        )
        story_to_play = stories[-1]
        for s, done in zip(stories, completions):
            if not done:
                story_to_play = s
                break

        await self.start_story(interaction, story_to_play["id"])

    async def start_story(
        self,
        interaction: discord.Interaction,
        story_id: str,
        edit: bool = False,
        force_restart: bool = False,
    ):
        guild_id = interaction.guild.id
        user_id  = interaction.user.id

        story = await self.bot.db.get_vn_story(story_id)
        if not story:
            await interaction.followup.send(f"Story `{story_id}` not found.", ephemeral=True)
            return

        run = None if force_restart else await self.bot.db.get_active_vn_run(guild_id, user_id, story_id)

        if run:
            # Resuming a run you already paid for — no second ticket.
            scene_id  = run["scene_id"]
            run_vars  = run.get("vars") or {}
            party_ids = (run.get("party") or [])[:story["party_size"]]
            resumed   = True
        else:
            spent = await self.bot.db.spend_user_counter(user_id, _VN_TICKET_KEY)
            if spent < 0:
                await interaction.followup.send(
                    "You don't have any VN tickets.\n"
                    "Earn 1 from `/checkin` each day and 1 from each `/vote`.",
                    ephemeral=True,
                )
                return
            guild_party = await self.bot.db.get_vn_party(guild_id, user_id)
            party_ids   = guild_party[:story["party_size"]]
            scene_id    = story["entry_scene"]
            run_vars    = {}
            resumed     = False

        scene = await self._resolve(story_id, scene_id, run_vars)
        if not scene:
            await interaction.followup.send(
                "This story has no scenes yet." if not resumed
                else "Your saved scene no longer exists · starting over.",
                ephemeral=True,
            )
            if resumed:
                await self.bot.db.end_vn_run(guild_id, user_id, story_id)
            return

        if not resumed:
            await self.bot.db.start_vn_run(guild_id, user_id, story_id, scene["id"], party_ids)

        party_chars = await self._load_party_chars(party_ids)
        await self._deliver_scene(
            interaction, story, scene, party_chars, edit=edit,
            run_vars=run_vars,
            roll_text="Resuming where you left off." if resumed else None,
        )

    async def advance_to_scene(
        self,
        interaction: discord.Interaction,
        story_id: str,
        scene_id: str,
        roll_text: str | None = None,
        run_vars: dict | None = None,
        _deferred: bool = False,
    ):
        if not _deferred:
            await interaction.response.defer()

        guild_id = interaction.guild.id
        user_id  = interaction.user.id

        story, run = await asyncio.gather(
            self.bot.db.get_vn_story(story_id),
            self.bot.db.get_active_vn_run(guild_id, user_id, story_id),
        )
        if not story:
            await interaction.followup.send("Scene not found.", ephemeral=True)
            return

        if run_vars is None:
            run_vars = (run or {}).get("vars") or {}

        scene = await self._resolve(story_id, scene_id, run_vars)
        if not scene:
            await interaction.followup.send("Scene not found.", ephemeral=True)
            return

        party_ids = (run or {}).get("party") or []
        if not party_ids:
            party_ids = await self.bot.db.get_vn_party(guild_id, user_id)
        party_ids = party_ids[:story["party_size"]]

        party_chars, _ = await asyncio.gather(
            self._load_party_chars(party_ids),
            self.bot.db.save_vn_run(guild_id, user_id, story_id, scene["id"], run_vars),
        )

        await self._deliver_scene(
            interaction, story, scene, party_chars,
            edit=True, roll_text=roll_text, run_vars=run_vars,
        )

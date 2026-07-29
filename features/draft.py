"""Captain draft and map-ban flow: /pick plus the shared draft helpers."""
import random

import discord

from checks import ensure_queue_channel
from config import MAPS
from db import get_player_name
from state import active_matches, drafts


def get_draft_list(draft):
    """Formatted overview of both teams and the remaining pool for a draft."""
    team1 = "\n".join(get_player_name(p) for p in draft["team1"])
    team2 = "\n".join(get_player_name(p) for p in draft["team2"])
    remaining = "\n".join(get_player_name(p) for p in draft["remaining"])

    return (
        f"🔴 **Team 1**\n"
        f"{team1}\n\n"
        f"🔵 **Team 2**\n"
        f"{team2}\n\n"
        f"👥 **Available Players**\n"
        f"{remaining}"
    )


async def start_map_ban(channel, mode, first_banner, second_banner, on_complete):
    """Run the interactive 3-map ban between two captains, then call on_complete(map).

    first_banner bans first, second_banner second. Sides (red/blue) aren't decided
    yet at this point, so captains are referred to by name only.
    """
    maps = random.sample(MAPS[mode], 3)

    class MapBanView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.maps = maps.copy()
            self.turn = 0
            self.banned = []
            self.message = None
            self.create_buttons()

        def create_buttons(self):
            self.clear_items()

            for game_map in self.maps:
                button = discord.ui.Button(
                    label=game_map,
                    style=discord.ButtonStyle.danger,
                )

                async def callback(interaction, selected_map=game_map):
                    await self.ban_map(interaction, selected_map)

                button.callback = callback
                self.add_item(button)

        async def ban_map(self, interaction, selected_map):
            captain = first_banner if self.turn == 0 else second_banner

            if interaction.user.id != captain.id:
                await interaction.response.send_message(
                    "❌ It is not your turn to ban.",
                    ephemeral=True,
                )
                return

            self.maps.remove(selected_map)
            self.banned.append(selected_map)

            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(view=self)

            if self.turn == 0:
                self.turn = 1
                self.create_buttons()
                await self.update_message(
                    f"🚫 **{get_player_name(interaction.user)} banned {selected_map}**\n\n"
                    f"⚔️ **{get_player_name(second_banner)}** bans next."
                )
                await channel.send(f"🗺️ <@{second_banner.id}>, your turn to ban!")
            else:
                winner = self.maps[0]

                for item in self.children:
                    item.disabled = True

                await self.update_message(
                    f"🚫 **{get_player_name(interaction.user)} banned {selected_map}**\n\n"
                    f"🗺️ **Map Selected: {winner}**"
                )
                self.stop()
                await on_complete(winner)

        async def update_message(self, extra):
            embed = discord.Embed(
                title="🗺️ Map Ban Phase",
                color=discord.Color.orange(),
            )
            embed.add_field(
                name="Remaining Maps",
                value="\n".join(f"🟩 {m}" for m in self.maps),
                inline=False,
            )
            if self.banned:
                embed.add_field(
                    name="Banned Maps",
                    value="\n".join(f"🚫 {m}" for m in self.banned),
                    inline=False,
                )
            embed.add_field(name="Status", value=extra, inline=False)

            await self.message.edit(embed=embed, view=self)

        async def on_timeout(self):
            if len(self.maps) <= 1:
                return

            # The view is now dead, so no more clicks will come — resolve every
            # remaining ban randomly and finish.
            notes = []
            while len(self.maps) > 1:
                captain = first_banner if self.turn == 0 else second_banner
                banned = random.choice(self.maps)
                self.maps.remove(banned)
                self.banned.append(banned)
                notes.append(
                    f"⏰ **{get_player_name(captain)} timed out** — random ban: {banned}"
                )
                self.turn = 1

            for item in self.children:
                item.disabled = True

            winner = self.maps[0]
            await self.update_message(
                "\n".join(notes) + f"\n\n🗺️ **Map Selected: {winner}**"
            )
            await on_complete(winner)

    view = MapBanView()

    embed = discord.Embed(
        title="🗺️ Map Ban Phase",
        color=discord.Color.orange(),
    )
    embed.add_field(
        name="Remaining Maps",
        value="\n".join(f"🟩 {m}" for m in maps),
        inline=False,
    )
    embed.add_field(
        name="Status",
        value=f"⚔️ **{get_player_name(first_banner)}** bans first.",
        inline=False,
    )

    view.message = await channel.send(
        content=f"🗺️ <@{first_banner.id}>, you ban first!",
        embed=embed,
        view=view,
    )


def setup(bot):
    @bot.tree.command(name="pick", description="Pick a player for your team")
    async def pick(interaction: discord.Interaction, player_name: str):
        if not await ensure_queue_channel(interaction):
            return

        # Find the draft this user is a captain of.
        draft = None
        for d in drafts.values():
            if interaction.user in (d["captain1"], d["captain2"]):
                draft = d
                break

        if draft is None:
            await interaction.response.send_message(
                "❌ You are not in a captain draft.",
                ephemeral=True,
            )
            return

        player = None
        for p in draft["remaining"]:
            if get_player_name(p).lower() == player_name.lower():
                player = p
                break

        if player is None:
            await interaction.response.send_message(
                "❌ Player not found.",
                ephemeral=True,
            )
            return

        # Apply the pick to the current captain's team (turn not flipped yet).
        current = draft["turn"]
        if current == 1:
            if interaction.user != draft["captain1"]:
                await interaction.response.send_message("❌ It is not your turn.", ephemeral=True)
                return
            draft["team1"].append(player)
        else:
            if interaction.user != draft["captain2"]:
                await interaction.response.send_message("❌ It is not your turn.", ephemeral=True)
                return
            draft["team2"].append(player)

        draft["remaining"].remove(player)

        # Snake endgame: when 3 remain, the second-pick captain picks 2 in a row and
        # the first-pick captain is auto-given the last player (compensates first pick).
        rem = len(draft["remaining"])
        other = 2 if current == 1 else 1
        auto_assigned = None
        bonus_pick = False
        if rem == 2:
            draft["turn"] = current      # same (second-pick) captain picks again
            bonus_pick = True
        elif rem == 1:
            auto_assigned = draft["remaining"].pop()   # last player -> first-pick captain
            (draft["team1"] if other == 1 else draft["team2"]).append(auto_assigned)
        elif rem > 2:
            draft["turn"] = other        # normal alternation

        if draft["remaining"]:
            next_captain = draft["captain1"] if draft["turn"] == 1 else draft["captain2"]
            bonus = " **(bonus pick — you pick again!)**" if bonus_pick else ""
            await interaction.response.send_message(
                f"✅ {get_player_name(player)} was picked!\n\n"
                f"{get_draft_list(draft)}\n\n"
                f"🎯 <@{next_captain.id}>, your turn to pick!{bonus}\n"
                f"Use `/pick PlayerName`"
            )
            return

        # Draft finished (the last player may have been auto-assigned above).
        # Keyed by (channel_id, mode) so concurrent matches never collide.
        game_map = draft.get("map")
        key = (draft["channel_id"], draft["mode"])
        active_matches[key] = {
            "channel_id": draft["channel_id"],
            "mode": draft["mode"],
            "team1": draft["team1"],
            "team2": draft["team2"],
            "captain1": draft["captain1"],
            "captain2": draft["captain2"],
            "map": game_map,
        }
        drafts.pop(key, None)

        pick_msg = f"✅ {get_player_name(player)} was picked!"
        if auto_assigned is not None:
            pick_msg += (
                f"\n🤖 {get_player_name(auto_assigned)} was auto-assigned "
                f"(last remaining player)."
            )
        map_line = f"\n🗺️ Map: **{game_map}**" if game_map else ""
        await interaction.response.send_message(
            f"{pick_msg}\n\n🏆 **Teams are complete!**{map_line}\n\n{get_draft_list(draft)}\n\n"
            f"🎮 **Everything is set — good luck and have fun!**\n"
            f"When the game is over, a captain reports the result with `/result <winning team>`."
        )

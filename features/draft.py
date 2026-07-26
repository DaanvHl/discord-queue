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


async def start_map_ban(channel, mode):
    """Run the interactive 3-map ban between the two captains."""
    maps = random.sample(MAPS[mode], 3)

    match = active_matches[channel.id]
    red_captain = match["captain1"]
    blue_captain = match["captain2"]

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
            captain = red_captain if self.turn == 0 else blue_captain

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
                    f"🔵 **{get_player_name(blue_captain)}** bans next."
                )
            else:
                winner = self.maps[0]
                active_matches[channel.id]["map"] = winner

                for item in self.children:
                    item.disabled = True

                await self.update_message(
                    f"🚫 **{get_player_name(interaction.user)} banned {selected_map}**\n\n"
                    f"🗺️ **Map Selected: {winner}**\n\n"
                    f"🎮 **Match Ready!**"
                )
                self.stop()

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

            captain = red_captain if self.turn == 0 else blue_captain
            banned = random.choice(self.maps)
            self.maps.remove(banned)
            self.banned.append(banned)

            if self.turn == 0:
                self.turn = 1
                self.create_buttons()
                await self.update_message(
                    f"⏰ **{get_player_name(captain)} timed out.**\n"
                    f"🚫 Random ban: {banned}\n\n"
                    f"🔵 **{get_player_name(blue_captain)} bans next.**"
                )
            else:
                winner = self.maps[0]
                active_matches[channel.id]["map"] = winner
                await self.update_message(
                    f"⏰ **{get_player_name(captain)} timed out.**\n"
                    f"🚫 Random ban: {banned}\n\n"
                    f"🗺️ **Map Selected: {winner}**\n"
                    f"🎮 **Match Ready!**"
                )
                self.stop()

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
        value=f"🔴 **{get_player_name(red_captain)}** bans first.",
        inline=False,
    )

    view.message = await channel.send(embed=embed, view=view)


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

        if draft["turn"] == 1:
            if interaction.user != draft["captain1"]:
                await interaction.response.send_message(
                    "❌ It is not your turn.",
                    ephemeral=True,
                )
                return
            draft["team1"].append(player)
            draft["turn"] = 2
        else:
            if interaction.user != draft["captain2"]:
                await interaction.response.send_message(
                    "❌ It is not your turn.",
                    ephemeral=True,
                )
                return
            draft["team2"].append(player)
            draft["turn"] = 1

        draft["remaining"].remove(player)

        # If only one player would be left, their team is forced — auto-assign them
        # to whoever's turn it is now, saving a pointless final /pick.
        auto_assigned = None
        if len(draft["remaining"]) == 1:
            auto_assigned = draft["remaining"].pop()
            if draft["turn"] == 1:
                draft["team1"].append(auto_assigned)
            else:
                draft["team2"].append(auto_assigned)

        if draft["remaining"]:
            next_captain = (
                draft["captain1"] if draft["turn"] == 1 else draft["captain2"]
            )
            await interaction.response.send_message(
                f"✅ {get_player_name(player)} was picked!\n\n"
                f"{get_draft_list(draft)}\n\n"
                f"🎯 {get_player_name(next_captain)}'s turn\n"
                f"Use `/pick PlayerName`"
            )
            return

        # Draft finished (the last player may have been auto-assigned above).
        active_matches[interaction.channel.id] = {
            "mode": draft["mode"],
            "team1": draft["team1"],
            "team2": draft["team2"],
            "captain1": draft["captain1"],
            "captain2": draft["captain2"],
            "map": None,
        }
        drafts.pop(draft["mode"], None)

        pick_msg = f"✅ {get_player_name(player)} was picked!"
        if auto_assigned is not None:
            pick_msg += (
                f"\n🤖 {get_player_name(auto_assigned)} was auto-assigned "
                f"(last remaining player)."
            )
        await interaction.response.send_message(
            f"{pick_msg}\n\n🏆 Teams are complete!\n\n{get_draft_list(draft)}"
        )

        await start_map_ban(interaction.channel, draft["mode"])

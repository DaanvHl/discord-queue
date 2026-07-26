"""Queue commands: /join, /leave, /queues, /clear, /captain, /uncaptain.

Match lifecycle for a mode:
  1. Players /join -> they wait in queues[mode]. Nothing else happens.
  2. Queue reaches full size -> it becomes a lobby (lobbies[mode]) and the bot
     asks two players to claim captain. The queue is cleared.
  3. During the lobby, exactly two players use /captain (changeable via /uncaptain).
  4. Once two captains are set, the draft starts and captains lock in.
"""
import random

import discord
from discord import app_commands

from checks import ensure_queue_channel
from config import GAME_MODES
from db import get_player_name, is_registered
from features.draft import get_draft_list, start_map_ban
from state import drafts, lobbies, queues

MODE_CHOICES = [
    app_commands.Choice(name=mode, value=mode) for mode in GAME_MODES
]


def _lobby_full_embed(mode):
    """Announcement shown when a queue fills and captains are needed."""
    lobby = lobbies[mode]
    embed = discord.Embed(
        title=f"🏆 {mode} Queue Full!",
        description=(
            "Two players must claim captain to start the draft.\n"
            "Use `/captain` — first two to claim lead the teams."
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="👥 Players",
        value="\n".join(get_player_name(p) for p in lobby["players"]),
        inline=False,
    )
    return embed


def _begin_draft(mode, red_captain, blue_captain, first_picker):
    """Turn a lobby into a captain draft with the chosen sides; return the draft embed.

    red_captain / blue_captain are the assigned sides; first_picker (one of them)
    takes the first player pick.
    """
    lobby = lobbies.pop(mode)
    players = lobby["players"]

    remaining = [p for p in players if p not in (red_captain, blue_captain)]
    random.shuffle(remaining)

    # team1 == red, team2 == blue; turn 1 means red picks, turn 2 means blue picks.
    turn = 1 if first_picker == red_captain else 2

    drafts[mode] = {
        "mode": mode,
        "captain1": red_captain,
        "captain2": blue_captain,
        "team1": [red_captain],
        "team2": [blue_captain],
        "remaining": remaining,
        "turn": turn,
        "map": lobby.get("map"),
    }

    first_marker = "🔴" if first_picker == red_captain else "🔵"

    embed = discord.Embed(
        title=f"🏆 {mode} Match Ready!",
        description="🎮 Captain draft started!",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="👑 Captains",
        value=(
            f"🔴 **Red Captain:** {get_player_name(red_captain)}\n"
            f"🔵 **Blue Captain:** {get_player_name(blue_captain)}"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎯 First Pick",
        value=f"{first_marker} {get_player_name(first_picker)}",
        inline=False,
    )
    if drafts[mode].get("map"):
        embed.add_field(name="🗺️ Map", value=drafts[mode]["map"], inline=False)
    embed.add_field(
        name="📋 Draft Status",
        value=get_draft_list(drafts[mode]),
        inline=False,
    )
    embed.set_footer(text="Use /pick PlayerName")
    return embed


class _TeamSelectView(discord.ui.View):
    """Lets the first captain pick a side; the other captain gets first pick."""

    def __init__(self, mode, picker, other):
        super().__init__(timeout=60)
        self.mode = mode
        self.picker = picker   # first captain — chooses the side
        self.other = other     # second captain — gets first pick
        self.message = None
        self.done = False

    async def _finish(self, color, interaction=None):
        self.done = True
        if color == "red":
            red_captain, blue_captain = self.picker, self.other
        else:
            red_captain, blue_captain = self.other, self.picker

        for item in self.children:
            item.disabled = True

        picker_marker = "🔴" if color == "red" else "🔵"
        note = (
            f"{picker_marker} **{get_player_name(self.picker)}** chose "
            f"**{color.capitalize()}**.\n"
            f"🎯 **{get_player_name(self.other)}** gets first pick."
        )
        draft_embed = _begin_draft(self.mode, red_captain, blue_captain, first_picker=self.other)

        if interaction is not None:
            await interaction.response.edit_message(content=note, embed=None, view=self)
            await interaction.channel.send(embed=draft_embed)
        elif self.message is not None:
            await self.message.edit(content=note, embed=None, view=self)
            await self.message.channel.send(embed=draft_embed)
        self.stop()

    @discord.ui.button(label="Red", style=discord.ButtonStyle.danger, emoji="🔴")
    async def red(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._on_click(interaction, "red")

    @discord.ui.button(label="Blue", style=discord.ButtonStyle.primary, emoji="🔵")
    async def blue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._on_click(interaction, "blue")

    async def _on_click(self, interaction, color):
        if interaction.user.id != self.picker.id:
            await interaction.response.send_message(
                f"❌ Only {get_player_name(self.picker)} picks the team.",
                ephemeral=True,
            )
            return
        if self.done:
            return
        await self._finish(color, interaction)

    async def on_timeout(self):
        if self.done:
            return
        # Default: the picker takes Red.
        await self._finish("red", interaction=None)


def _find_player_lobby(user):
    """Return the lobby (forming match) the user is part of, or None."""
    for lobby in lobbies.values():
        if user in lobby["players"]:
            return lobby
    return None


def setup(bot):
    @bot.tree.command(name="join", description="Join a queue")
    @app_commands.choices(mode=MODE_CHOICES)
    async def join(interaction: discord.Interaction, mode: app_commands.Choice[str]):
        if not await ensure_queue_channel(interaction):
            return

        if not is_registered(interaction.user.id):
            await interaction.response.send_message(
                "❌ You must register first using `/register`.",
                ephemeral=True,
            )
            return

        queue = queues[mode.value]
        size = GAME_MODES[mode.value]
        user = interaction.user

        if mode.value in lobbies:
            await interaction.response.send_message(
                f"❌ A **{mode.value}** match is already forming. Wait for it to start.",
                ephemeral=True,
            )
            return

        # A player may only be in one queue at a time.
        for other_mode, other_queue in queues.items():
            if user in other_queue:
                if other_mode == mode.value:
                    text = f"You're already in the **{mode.value}** queue."
                else:
                    text = (
                        f"❌ You're already in the **{other_mode}** queue. "
                        f"Use `/leave {other_mode}` before joining another."
                    )
                await interaction.response.send_message(text, ephemeral=True)
                return

        # ...nor in a match that is currently being formed.
        for other_mode, lobby in lobbies.items():
            if user in lobby["players"]:
                await interaction.response.send_message(
                    f"❌ You're in a **{other_mode}** match being formed. Finish it first.",
                    ephemeral=True,
                )
                return

        if len(queue) >= size:
            await interaction.response.send_message(
                f"❌ The **{mode.value}** queue is already full!",
                ephemeral=True,
            )
            return

        queue.append(user)

        if len(queue) < size:
            await interaction.response.send_message(
                f"✅ Joined **{mode.value}** queue ({len(queue)}/{size})"
            )
            return

        # Queue is full: form a lobby and ask for captains. No captains yet.
        lobbies[mode.value] = {
            "mode": mode.value,
            "players": queue.copy(),
            "captains": [],
            "map": None,
            "locked": False,
        }
        queue.clear()
        await interaction.response.send_message(embed=_lobby_full_embed(mode.value))

    @bot.tree.command(name="leave", description="Leave your current queue")
    async def leave(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        user = interaction.user
        current_mode = next((m for m, q in queues.items() if user in q), None)

        if current_mode is None:
            await interaction.response.send_message(
                "You're not in a queue.",
                ephemeral=True,
            )
            return

        queue = queues[current_mode]
        queue.remove(user)
        await interaction.response.send_message(
            f"❌ Left **{current_mode}** ({len(queue)}/{GAME_MODES[current_mode]})"
        )

    @bot.tree.command(name="captain", description="Claim a captain slot after your queue fills")
    async def captain(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        user = interaction.user
        lobby = _find_player_lobby(user)

        if lobby is None:
            await interaction.response.send_message(
                "❌ Captains can only be chosen right after your queue fills.",
                ephemeral=True,
            )
            return

        if user in lobby["captains"]:
            await interaction.response.send_message(
                "❌ You are already a captain.",
                ephemeral=True,
            )
            return

        if len(lobby["captains"]) >= 2:
            await interaction.response.send_message(
                "❌ Both captain slots are already taken.",
                ephemeral=True,
            )
            return

        lobby["captains"].append(user)

        if len(lobby["captains"]) < 2:
            await interaction.response.send_message(
                f"👑 {get_player_name(user)} is captain (1/2).\n"
                f"One more player must use `/captain`."
            )
            return

        # Both captains set. Lock the lobby and run the map ban first; the team pick
        # and player draft follow once the map is decided.
        lobby["locked"] = True
        cap1, cap2 = lobby["captains"][0], lobby["captains"][1]
        mode = lobby["mode"]
        channel = interaction.channel

        async def after_map_ban(selected_map):
            lobby["map"] = selected_map
            picker, other = lobby["captains"][0], lobby["captains"][1]
            view = _TeamSelectView(mode, picker, other)
            embed = discord.Embed(
                title="🎽 Pick a Team",
                description=(
                    f"👑 **{get_player_name(picker)}**, choose your side.\n"
                    f"🎯 **{get_player_name(other)}** will get first pick in the draft."
                ),
                color=discord.Color.gold(),
            )
            view.message = await channel.send(embed=embed, view=view)

        await interaction.response.send_message(
            f"👑 Captains locked in: **{get_player_name(cap1)}** & **{get_player_name(cap2)}**.\n"
            f"🗺️ Map ban starting — **{get_player_name(cap1)}** bans first."
        )
        await start_map_ban(channel, mode, cap1, cap2, after_map_ban)

    @bot.tree.command(name="uncaptain", description="Give up your captain slot before the draft starts")
    async def uncaptain(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        user = interaction.user
        lobby = _find_player_lobby(user)

        if lobby is None or user not in lobby["captains"]:
            await interaction.response.send_message(
                "❌ You are not a captain in an active selection.",
                ephemeral=True,
            )
            return

        if lobby.get("locked"):
            await interaction.response.send_message(
                "❌ The match has already started — captains can no longer change.",
                ephemeral=True,
            )
            return

        lobby["captains"].remove(user)
        await interaction.response.send_message(
            f"✅ {get_player_name(user)} stepped down. "
            f"A player must use `/captain` ({len(lobby['captains'])}/2)."
        )

    @bot.tree.command(name="queues", description="View all queues")
    async def queues_command(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        embed = discord.Embed(title="Current Queues", color=discord.Color.green())

        for mode, players in queues.items():
            size = GAME_MODES[mode]
            if mode in lobbies:
                lobby = lobbies[mode]
                value = (
                    "⏳ *Choosing captains...*\n"
                    + "\n".join(
                        f"👑 {get_player_name(p)}" if p in lobby["captains"]
                        else get_player_name(p)
                        for p in lobby["players"]
                    )
                )
                header = f"{mode} (full — {len(lobby['captains'])}/2 captains)"
            elif players:
                value = "\n".join(get_player_name(p) for p in players)
                header = f"{mode} ({len(players)}/{size})"
            else:
                value = "*Empty*"
                header = f"{mode} (0/{size})"

            embed.add_field(name=header, value=value, inline=False)

        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="clear", description="Clear every queue")
    @app_commands.checks.has_permissions(administrator=True)
    async def clear(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        for q in queues.values():
            q.clear()
        lobbies.clear()

        await interaction.response.send_message("🗑️ All queues cleared.")

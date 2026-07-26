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
from features.draft import get_draft_list
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


def _begin_draft(mode):
    """Turn a lobby with two captains into a captain draft; return the draft embed."""
    lobby = lobbies.pop(mode)
    players = lobby["players"]
    captain1, captain2 = lobby["captains"][0], lobby["captains"][1]

    remaining = [p for p in players if p not in (captain1, captain2)]
    random.shuffle(remaining)

    drafts[mode] = {
        "mode": mode,
        "captain1": captain1,
        "captain2": captain2,
        "team1": [captain1],
        "team2": [captain2],
        "remaining": remaining,
        "turn": 1,
    }

    embed = discord.Embed(
        title=f"🏆 {mode} Match Ready!",
        description="🎮 Captain draft started!",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="👑 Captains",
        value=(
            f"🔴 **Red Captain:** {get_player_name(captain1)}\n"
            f"🔵 **Blue Captain:** {get_player_name(captain2)}"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎯 First Pick",
        value=f"🔴 {get_player_name(captain1)}",
        inline=False,
    )
    embed.add_field(
        name="📋 Draft Status",
        value=get_draft_list(drafts[mode]),
        inline=False,
    )
    embed.set_footer(text="Use /pick PlayerName")
    return embed


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

        # Second captain locked in: start the draft.
        await interaction.response.send_message(embed=_begin_draft(lobby["mode"]))

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

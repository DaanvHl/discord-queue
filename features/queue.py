"""Queue commands: /join, /leave, /queues, /clear, /captain, /uncaptain.

Match lifecycle for a mode:
  1. Players /join -> they wait in queues[mode]. Nothing else happens.
  2. Queue reaches full size -> it becomes a lobby (lobbies[mode]) and the bot
     asks two players to claim captain. The queue is cleared.
  3. During the lobby, exactly two players use /captain (changeable via /uncaptain).
  4. Once two captains are set, the draft starts and captains lock in.
"""
import random
import time

import discord
from discord import app_commands
from discord.ext import tasks

from checks import ensure_queue_channel
from config import GAME_MODES, QUEUE_CHANNEL_ID, QUEUE_INACTIVITY_SECONDS
from db import get_player_name, is_registered
from features.draft import get_draft_list, start_map_ban
from state import drafts, lobbies, queue_last_activity, queues

MODE_CHOICES = [
    app_commands.Choice(name=mode, value=mode) for mode in GAME_MODES
]


def _format_for_count(n):
    """Return the mode whose team size fits n players (even, in range), else None."""
    if n < 4 or n % 2 != 0:
        return None
    mode = f"{n // 2}v{n // 2}"
    return mode if mode in GAME_MODES else None


def _queue_text(mode):
    """Roster panel text for a queue."""
    queue = queues[mode]
    size = GAME_MODES[mode]
    roster = "\n".join(
        f"{i}. {get_player_name(p)}" for i, p in enumerate(queue, 1)
    ) if queue else "*Empty*"

    text = f"🎮 **{mode} queue — {len(queue)}/{size}**\n{roster}"
    if len(queue) >= size:
        text += (
            "\n\n🎉 **Full!** Use `/start` to begin the draft, "
            "or `/expand` to open the next format (+2 players)."
        )
    else:
        text += (
            "\n\nClick **✅ Join** / **🚪 Leave** · "
            "`/close` to start now with the current (even) players."
        )
    return text


def _join_result(user, mode):
    """Try to add a user to a queue. Returns (ok: bool, error_message | None)."""
    if not is_registered(user.id):
        return False, "❌ You must register first using `/register`."
    if mode in lobbies:
        return False, f"❌ A **{mode}** match is already forming. Wait for it to start."
    for other_mode, other_queue in queues.items():
        if any(u.id == user.id for u in other_queue):
            if other_mode == mode:
                return False, f"You're already in the **{mode}** queue."
            return False, (
                f"❌ You're already in the **{other_mode}** queue. "
                f"Leave it before joining another."
            )
    for other_mode, lobby in lobbies.items():
        if any(u.id == user.id for u in lobby["players"]):
            return False, f"❌ You're in a **{other_mode}** match being formed. Finish it first."
    queue = queues[mode]
    if len(queue) >= GAME_MODES[mode]:
        return False, f"❌ The **{mode}** queue is already full!"

    queue.append(user)
    queue_last_activity[mode] = time.monotonic()
    return True, None


def _leave_result(user, mode):
    """Try to remove a user from a queue. Returns (ok: bool, error_message | None)."""
    queue = queues[mode]
    target = next((u for u in queue if u.id == user.id), None)
    if target is None:
        return False, "❌ You're not in this queue."
    queue.remove(target)
    if not queue:
        queue_last_activity.pop(mode, None)
    return True, None


class _QueueView(discord.ui.View):
    """Join / Leave buttons attached to a queue roster panel."""

    def __init__(self, mode):
        super().__init__(timeout=None)
        self.mode = mode

    @discord.ui.button(label="Join", emoji="✅", style=discord.ButtonStyle.success)
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok, error = _join_result(interaction.user, self.mode)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.edit_message(content=_queue_text(self.mode), view=self)

    @discord.ui.button(label="Leave", emoji="🚪", style=discord.ButtonStyle.secondary)
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok, error = _leave_result(interaction.user, self.mode)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.edit_message(content=_queue_text(self.mode), view=self)


def _captain_embed(lobby, locked=False):
    """Captain-selection panel: players, current captains, and instructions."""
    caps = lobby["captains"]
    if caps:
        cap_text = "\n".join(
            f"{'🔴' if i == 0 else '🔵'} {get_player_name(c)}" for i, c in enumerate(caps)
        )
    else:
        cap_text = "*None yet — roll or claim below.*"

    if locked:
        instr = "🔒 Captains locked in!"
    else:
        instr = (
            "🙋 **Claim Captain** to volunteer, or 🎲 **Roll Captains** for random ones.\n"
            "🚪 **Step Down** to withdraw · 🔒 **Lock In** once two are set."
        )

    embed = discord.Embed(
        title=f"🏆 {lobby['mode']} Queue Full!",
        description=instr,
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="👥 Players",
        value="\n".join(get_player_name(p) for p in lobby["players"]),
        inline=False,
    )
    embed.add_field(name=f"👑 Captains ({len(caps)}/2)", value=cap_text, inline=False)
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

        pick_ping = f"🎯 <@{self.other.id}>, you have first pick! Use `/pick PlayerName`."
        if interaction is not None:
            await interaction.response.edit_message(content=note, embed=None, view=self)
            await interaction.channel.send(content=pick_ping, embed=draft_embed)
        elif self.message is not None:
            await self.message.edit(content=note, embed=None, view=self)
            await self.message.channel.send(content=pick_ping, embed=draft_embed)
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


async def _advance_to_map_ban(mode, channel):
    """Lock captains in and start map ban -> team pick -> draft."""
    lobby = lobbies[mode]
    lobby["locked"] = True
    cap1, cap2 = lobby["captains"][0], lobby["captains"][1]

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
        view.message = await channel.send(
            content=f"🎽 <@{picker.id}>, choose your team's side!",
            embed=embed,
            view=view,
        )

    await channel.send(
        f"🔒 Captains locked in: **{get_player_name(cap1)}** & **{get_player_name(cap2)}**.\n"
        f"🗺️ Map ban starting — **{get_player_name(cap1)}** bans first."
    )
    await start_map_ban(channel, mode, cap1, cap2, after_map_ban)


class _CaptainSelectView(discord.ui.View):
    """Roll random captains (rerollable) or lock the current two in."""

    def __init__(self, mode):
        super().__init__(timeout=None)
        self.mode = mode

    async def _lobby_for(self, interaction):
        lobby = lobbies.get(self.mode)
        if lobby is None or lobby.get("locked"):
            await interaction.response.send_message(
                "❌ Captain selection is no longer open.", ephemeral=True
            )
            return None
        if not any(u.id == interaction.user.id for u in lobby["players"]):
            await interaction.response.send_message(
                "❌ You are not part of this match.", ephemeral=True
            )
            return None
        return lobby

    @discord.ui.button(label="Claim Captain", emoji="🙋", style=discord.ButtonStyle.secondary)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = await self._lobby_for(interaction)
        if lobby is None:
            return
        if any(c.id == interaction.user.id for c in lobby["captains"]):
            await interaction.response.send_message("❌ You are already a captain.", ephemeral=True)
            return
        if len(lobby["captains"]) >= 2:
            await interaction.response.send_message(
                "❌ Both captain slots are taken — step down or roll to change.", ephemeral=True
            )
            return
        player = next(u for u in lobby["players"] if u.id == interaction.user.id)
        lobby["captains"].append(player)
        await interaction.response.edit_message(embed=_captain_embed(lobby), view=self)

    @discord.ui.button(label="Step Down", emoji="🚪", style=discord.ButtonStyle.secondary)
    async def stepdown(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = await self._lobby_for(interaction)
        if lobby is None:
            return
        cap = next((c for c in lobby["captains"] if c.id == interaction.user.id), None)
        if cap is None:
            await interaction.response.send_message("❌ You are not a captain.", ephemeral=True)
            return
        lobby["captains"].remove(cap)
        await interaction.response.edit_message(embed=_captain_embed(lobby), view=self)

    @discord.ui.button(label="Roll Captains", emoji="🎲", style=discord.ButtonStyle.primary)
    async def roll(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = await self._lobby_for(interaction)
        if lobby is None:
            return
        lobby["captains"] = random.sample(lobby["players"], 2)
        await interaction.response.edit_message(embed=_captain_embed(lobby), view=self)

    @discord.ui.button(label="Lock In", emoji="🔒", style=discord.ButtonStyle.success)
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        lobby = await self._lobby_for(interaction)
        if lobby is None:
            return
        if len(lobby["captains"]) != 2:
            await interaction.response.send_message(
                "❌ Two captains must be set first — claim or roll.", ephemeral=True
            )
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=_captain_embed(lobby, locked=True), view=self)
        self.stop()
        await _advance_to_map_ban(self.mode, interaction.channel)


def setup(bot):
    @bot.tree.command(name="join", description="Join a queue")
    @app_commands.choices(mode=MODE_CHOICES)
    async def join(interaction: discord.Interaction, mode: app_commands.Choice[str]):
        if not await ensure_queue_channel(interaction):
            return

        ok, error = _join_result(interaction.user, mode.value)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True)
            return

        # Post the queue roster panel with Join / Leave buttons.
        await interaction.response.send_message(
            _queue_text(mode.value), view=_QueueView(mode.value)
        )

    @bot.tree.command(name="leave", description="Leave your current queue")
    async def leave(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        user = interaction.user
        current_mode = next(
            (m for m, q in queues.items() if any(u.id == user.id for u in q)), None
        )

        if current_mode is None:
            if _find_player_lobby(user) is not None:
                await interaction.response.send_message(
                    "❌ The match has already started — you can't leave now.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                "You're not in a queue.",
                ephemeral=True,
            )
            return

        _leave_result(user, current_mode)
        await interaction.response.send_message(
            _queue_text(current_mode), view=_QueueView(current_mode)
        )

    @bot.tree.command(name="start", description="Start the match once your queue is full")
    async def start(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        user = interaction.user
        current_mode = next(
            (m for m, q in queues.items() if any(u.id == user.id for u in q)),
            None,
        )

        if current_mode is None:
            await interaction.response.send_message(
                "❌ You're not in a queue.",
                ephemeral=True,
            )
            return

        queue = queues[current_mode]
        size = GAME_MODES[current_mode]

        if len(queue) < size:
            await interaction.response.send_message(
                f"❌ The **{current_mode}** queue isn't full yet ({len(queue)}/{size}).",
                ephemeral=True,
            )
            return

        if current_mode in lobbies:
            await interaction.response.send_message(
                "❌ This match has already started.",
                ephemeral=True,
            )
            return

        # Lock the queue into a lobby and begin captain selection. No more leaving.
        lobbies[current_mode] = {
            "mode": current_mode,
            "players": queue.copy(),
            "captains": [],
            "map": None,
            "locked": False,
        }
        queue.clear()
        queue_last_activity.pop(current_mode, None)

        # Post the captain-selection panel (claim / step down / roll / lock in).
        view = _CaptainSelectView(current_mode)
        await interaction.response.send_message(
            embed=_captain_embed(lobbies[current_mode]), view=view
        )

    @bot.tree.command(
        name="close",
        description="Close an under-full queue into the format matching your player count",
    )
    async def close(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        user = interaction.user
        mode = next(
            (m for m, q in queues.items() if any(u.id == user.id for u in q)), None
        )
        if mode is None:
            await interaction.response.send_message("❌ You're not in a queue.", ephemeral=True)
            return

        queue = queues[mode]
        n = len(queue)
        target = _format_for_count(n)
        if target is None:
            await interaction.response.send_message(
                f"❌ Closing needs an even number of players (4–20) — you have {n}.",
                ephemeral=True,
            )
            return
        if target in lobbies or (target != mode and queues[target]):
            await interaction.response.send_message(
                f"❌ The **{target}** slot is busy right now — try again shortly.",
                ephemeral=True,
            )
            return

        players = queue.copy()
        queue.clear()
        queue_last_activity.pop(mode, None)
        queues[target].clear()
        queue_last_activity.pop(target, None)
        lobbies[target] = {
            "mode": target,
            "players": players,
            "captains": [],
            "map": None,
            "locked": False,
        }

        view = _CaptainSelectView(target)
        await interaction.response.send_message(
            content=f"🔒 **{mode}** closed into **{target}** with {n} players.",
            embed=_captain_embed(lobbies[target]),
            view=view,
        )

    @bot.tree.command(
        name="expand",
        description="Expand a full queue to the next format up (+2 players)",
    )
    async def expand(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        user = interaction.user
        mode = next(
            (m for m, q in queues.items() if any(u.id == user.id for u in q)), None
        )
        if mode is None:
            await interaction.response.send_message("❌ You're not in a queue.", ephemeral=True)
            return

        queue = queues[mode]
        size = GAME_MODES[mode]
        if len(queue) < size:
            await interaction.response.send_message(
                f"❌ The **{mode}** queue isn't full yet ({len(queue)}/{size}) — "
                f"`/expand` only works on a full queue.",
                ephemeral=True,
            )
            return

        target = _format_for_count(size + 2)
        if target is None:
            await interaction.response.send_message(
                f"❌ **{mode}** is already the largest format — can't expand further.",
                ephemeral=True,
            )
            return
        if target in lobbies or queues[target]:
            await interaction.response.send_message(
                f"❌ The **{target}** slot is busy right now — try again shortly.",
                ephemeral=True,
            )
            return

        players = queue.copy()
        queue.clear()
        queue_last_activity.pop(mode, None)
        queues[target].extend(players)
        queue_last_activity[target] = time.monotonic()

        remaining = GAME_MODES[target] - len(players)
        await interaction.response.send_message(
            f"⬆️ **{mode}** expanded to **{target}** — {remaining} more can join!\n\n"
            + _queue_text(target),
            view=_QueueView(target),
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
        queue_last_activity.clear()

        await interaction.response.send_message("🗑️ All queues cleared.")

    @bot.tree.command(name="remove", description="(Admin) Remove a player from their queue")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove(interaction: discord.Interaction, player: discord.Member):
        if not await ensure_queue_channel(interaction):
            return

        # Find the open (not-yet-full) queue the player is waiting in.
        current_mode = next(
            (m for m, q in queues.items() if any(u.id == player.id for u in q)),
            None,
        )

        if current_mode is None:
            # If they're in a forming lobby, the queue is already full — not allowed.
            in_lobby = any(
                any(u.id == player.id for u in lob["players"])
                for lob in lobbies.values()
            )
            if in_lobby:
                text = "❌ That player's queue is already full and forming a match — can't remove now."
            else:
                text = "❌ That player isn't in any open queue."
            await interaction.response.send_message(text, ephemeral=True)
            return

        queue = queues[current_mode]
        target = next(u for u in queue if u.id == player.id)
        queue.remove(target)
        if not queue:
            queue_last_activity.pop(current_mode, None)

        await interaction.response.send_message(
            f"🚫 {get_player_name(target)} was removed from the **{current_mode}** queue "
            f"by an admin ({len(queue)}/{GAME_MODES[current_mode]})."
        )


def start_background_tasks(bot):
    """Start the loop that auto-closes queues with no join activity."""

    @tasks.loop(seconds=60)
    async def close_idle_queues():
        now = time.monotonic()
        channel = bot.get_channel(QUEUE_CHANNEL_ID)
        for mode, queue in queues.items():
            if not queue or mode in lobbies:
                continue
            last = queue_last_activity.get(mode)
            if last is None:
                # Non-empty queue with no recorded activity — start the clock now.
                queue_last_activity[mode] = now
                continue
            if now - last >= QUEUE_INACTIVITY_SECONDS:
                names = ", ".join(get_player_name(p) for p in queue)
                queue.clear()
                queue_last_activity.pop(mode, None)
                if channel is not None:
                    minutes = QUEUE_INACTIVITY_SECONDS // 60
                    await channel.send(
                        f"⏳ The **{mode}** queue was closed after {minutes} min of "
                        f"inactivity.\nRemoved: {names}. Use `/join` to queue again."
                    )

    @close_idle_queues.before_loop
    async def _before():
        await bot.wait_until_ready()

    close_idle_queues.start()

"""Queue commands: /join, /leave, /start, /close, /expand, /queues, /clear, /remove.

Queues are keyed by (channel_id, mode) so each channel runs its own independent
queues — a 6v6 in one channel is separate from a 6v6 in another.

Match lifecycle for a (channel, mode):
  1. Players /join -> they wait in that channel's queue. Nothing else happens.
  2. Queue reaches full size -> players /start it, forming a captain-selection lobby.
  3. Two captains are chosen (claim/roll) and locked in via buttons.
  4. Map ban -> team-side pick -> player draft -> match awaiting result.
"""
import random
import time

import discord
from discord import app_commands
from discord.ext import tasks

from checks import ensure_organizer, ensure_queue_channel
from config import GAME_MODES, QUEUE_INACTIVITY_SECONDS
from db import get_player_name, is_registered
from features.draft import (
    _register_match,
    _ready_text,
    _snake_order,
    _teams_overview,
    get_draft_list,
    start_map_ban,
)
from state import (
    active_matches,
    drafts,
    lobbies,
    pending_results,
    queue_last_activity,
    queues,
)

MODE_CHOICES = [
    app_commands.Choice(name=mode, value=mode) for mode in GAME_MODES
]


def _format_for_count(n):
    """Return the mode whose team size fits n players (even, in range), else None."""
    if n < 4 or n % 2 != 0:
        return None
    mode = f"{n // 2}v{n // 2}"
    return mode if mode in GAME_MODES else None


def _find_user_queue_key(user, channel_id=None):
    """The (channel_id, mode) queue key the user is waiting in, or None.

    If channel_id is given, only queues in that channel are considered.
    """
    for key, q in queues.items():
        if channel_id is not None and key[0] != channel_id:
            continue
        if any(u.id == user.id for u in q):
            return key
    return None


def _find_player_lobby(user):
    """Return the lobby (forming match) the user is part of, or None."""
    for lobby in lobbies.values():
        if any(u.id == user.id for u in lobby["players"]):
            return lobby
    return None


def _find_player_lobby_key(user, channel_id=None):
    """The (channel_id, mode) lobby key the user is part of, or None.

    If channel_id is given, only lobbies in that channel are considered.
    """
    for key, lobby in lobbies.items():
        if channel_id is not None and key[0] != channel_id:
            continue
        if any(u.id == user.id for u in lobby["players"]):
            return key
    return None


def _find_player_draft(user):
    """Return the draft (captain pick phase) the user is part of, or None."""
    for draft in drafts.values():
        everyone = draft["team1"] + draft["team2"] + draft["remaining"]
        if any(u.id == user.id for u in everyone):
            return draft
    return None


def _find_player_match(user):
    """Return the active match (started, awaiting a result) the user is in, or None."""
    for match in active_matches.values():
        if any(u.id == user.id for u in match["team1"] + match["team2"]):
            return match
    return None


def _queue_text(key):
    """Roster panel text for a queue key (channel_id, mode)."""
    _cid, mode = key
    queue = queues.get(key, [])
    size = GAME_MODES[mode]
    roster = "\n".join(
        f"{i}. {get_player_name(p)}" for i, p in enumerate(queue, 1)
    ) if queue else "*Empty*"

    text = f"🎮 **{mode} queue — {len(queue)}/{size}**\n{roster}"
    if len(queue) >= size:
        text += (
            "\n\n🎉 **Full!**"
            "\n`/start` to begin the draft"
            "\n`/expand` to open the next format (+2 players)"
        )
    else:
        text += "\n\n`/close` to start now with your current (even) player count"
    return text


def _join_result(user, key):
    """Try to add a user to the (channel, mode) queue. Returns (ok, error | None)."""
    _cid, mode = key
    if not is_registered(user.id):
        return False, "❌ You must register first using `/register`."
    if key in lobbies:
        return False, f"❌ A **{mode}** match is already forming here. Wait for it to start."

    # A player may only be in one queue at a time (across all channels).
    existing = _find_user_queue_key(user)
    if existing is not None:
        if existing == key:
            return False, f"You're already in this **{mode}** queue."
        return False, (
            f"❌ You're already in a **{existing[1]}** queue. "
            f"Leave it before joining another."
        )
    if _find_player_lobby(user) is not None:
        return False, "❌ You're in a match being formed. Finish it first."
    if _find_player_draft(user) is not None:
        return False, "❌ You're in a captain draft. Finish the match first."
    if _find_player_match(user) is not None:
        return False, (
            "❌ You're in an active match. Finish it and confirm the result "
            "before joining another queue."
        )

    queue = queues.setdefault(key, [])
    if len(queue) >= GAME_MODES[mode]:
        return False, f"❌ This **{mode}** queue is already full!"

    queue.append(user)
    queue_last_activity[key] = time.monotonic()
    return True, None


def _leave_result(user, key):
    """Try to remove a user from the (channel, mode) queue. Returns (ok, error | None)."""
    queue = queues.get(key, [])
    target = next((u for u in queue if u.id == user.id), None)
    if target is None:
        return False, "❌ You're not in this queue."
    queue.remove(target)
    if not queue:
        queues.pop(key, None)
        queue_last_activity.pop(key, None)
    return True, None


class _QueueView(discord.ui.View):
    """Join / Leave buttons attached to a queue roster panel."""

    def __init__(self, key):
        super().__init__(timeout=None)
        self.key = key

    @discord.ui.button(label="Join", emoji="✅", style=discord.ButtonStyle.success)
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok, error = _join_result(interaction.user, self.key)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.edit_message(content=_queue_text(self.key), view=self)

    @discord.ui.button(label="Leave", emoji="🚪", style=discord.ButtonStyle.secondary)
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok, error = _leave_result(interaction.user, self.key)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.edit_message(content=_queue_text(self.key), view=self)


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


def _begin_draft(key, red_captain, blue_captain, first_picker):
    """Turn a lobby into a captain draft with the chosen sides; return the draft embed."""
    cid, mode = key
    lobby = lobbies.pop(key, None)
    if lobby is None:
        return None  # match was cleared by an admin mid-selection
    players = lobby["players"]

    remaining = [p for p in players if p not in (red_captain, blue_captain)]
    random.shuffle(remaining)

    turn = 1 if first_picker == red_captain else 2
    pick_order = _snake_order(turn, len(remaining))

    drafts[key] = {
        "channel_id": cid,
        "mode": mode,
        "captain1": red_captain,
        "captain2": blue_captain,
        "team1": [red_captain],
        "team2": [blue_captain],
        "remaining": remaining,
        "turn": turn,
        "pick_order": pick_order,
        "pick_index": 0,
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
    if drafts[key].get("map"):
        embed.add_field(name="🗺️ Map", value=drafts[key]["map"], inline=False)
    embed.add_field(
        name="📋 Draft Status",
        value=get_draft_list(drafts[key]),
        inline=False,
    )
    embed.set_footer(text="Use /pick PlayerName")
    return embed


class _TeamSelectView(discord.ui.View):
    """Lets the first captain pick a side; the other captain gets first pick."""

    def __init__(self, key, picker, other):
        super().__init__(timeout=60)
        self.key = key
        self.picker = picker
        self.other = other
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
            f"**{color.capitalize()}**.\n\n"
            "🧩 A captain now picks how to build the teams:"
        )
        method_view = _MethodSelectView(
            self.key, red_captain, blue_captain, first_picker=self.other
        )
        if interaction is not None:
            await interaction.response.edit_message(
                content=note, embed=method_view.embed(), view=method_view
            )
        elif self.message is not None:
            await self.message.edit(content=note, embed=method_view.embed(), view=method_view)
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
        await self._finish("red", interaction=None)


# --------------------------------------------------------------------------
# Team-picking method selection: Random / Snake / Auction
# --------------------------------------------------------------------------

class _MethodSelectView(discord.ui.View):
    """Let a captain choose how the teams get built, after sides are picked."""

    def __init__(self, key, red_captain, blue_captain, first_picker):
        super().__init__(timeout=None)
        self.key = key
        self.red_captain = red_captain
        self.blue_captain = blue_captain
        self.first_picker = first_picker

    def embed(self):
        return discord.Embed(
            title="🧩 Choose team-picking method",
            description=(
                "A **captain** picks how to build the teams:\n\n"
                "🎲 **Random** — shuffle players into two teams (with reroll voting)\n"
                "📋 **Snake Draft** — captains take turns picking (A, B, B, A…)\n"
                "💰 **Auction** — captains bid coins on players"
            ),
            color=discord.Color.blurple(),
        )

    async def _guard(self, interaction):
        if self.key not in lobbies:
            await interaction.response.edit_message(
                content="❌ This match was cleared.", embed=None, view=None
            )
            self.stop()
            return False
        if interaction.user.id not in (self.red_captain.id, self.blue_captain.id):
            await interaction.response.send_message(
                "❌ Only a captain chooses the picking method.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Random", emoji="🎲", style=discord.ButtonStyle.secondary)
    async def random_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.stop()
        await _start_random(interaction, self.key, self.red_captain, self.blue_captain)

    @discord.ui.button(label="Snake Draft", emoji="📋", style=discord.ButtonStyle.primary)
    async def snake_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.stop()
        draft_embed = _begin_draft(
            self.key, self.red_captain, self.blue_captain, first_picker=self.first_picker
        )
        if draft_embed is None:
            await interaction.response.edit_message(
                content="❌ This match was cleared.", embed=None, view=None
            )
            return
        await interaction.response.edit_message(
            content=f"📋 **Snake draft** — 🎯 {get_player_name(self.first_picker)} picks first.",
            embed=None,
            view=None,
        )
        await interaction.channel.send(
            content=f"🎯 <@{self.first_picker.id}>, you have first pick! Use `/pick PlayerName`.",
            embed=draft_embed,
        )

    @discord.ui.button(label="Auction", emoji="💰", style=discord.ButtonStyle.success)
    async def auction_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.stop()
        await _start_auction(interaction, self.key, self.red_captain, self.blue_captain)


async def _start_random(interaction, key, red_captain, blue_captain):
    lobby = lobbies.get(key)
    if lobby is None:
        await interaction.response.edit_message(
            content="❌ This match was cleared.", embed=None, view=None
        )
        return
    others = [
        p for p in lobby["players"]
        if p.id not in (red_captain.id, blue_captain.id)
    ]
    view = _RandomTeamsView(key, red_captain, blue_captain, others, lobby.get("map"))
    view.shuffle()
    await interaction.response.edit_message(content=None, embed=view.embed(), view=view)


class _RandomTeamsView(discord.ui.View):
    """Random teams with a 'vote reroll' button (3 votes reshuffles) and captain accept."""

    REROLL_THRESHOLD = 3

    def __init__(self, key, red_captain, blue_captain, others, game_map):
        super().__init__(timeout=None)
        self.key = key
        self.red_captain = red_captain
        self.blue_captain = blue_captain
        self.others = list(others)
        self.game_map = game_map
        self.team1 = [red_captain]
        self.team2 = [blue_captain]
        self.reroll_votes = set()
        self.note = ""

    def _participants(self):
        return [self.red_captain, self.blue_captain] + self.others

    def shuffle(self):
        pool = list(self.others)
        random.shuffle(pool)
        half = len(pool) // 2
        self.team1 = [self.red_captain] + pool[:half]
        self.team2 = [self.blue_captain] + pool[half:]
        self.reroll_votes.clear()

    def embed(self):
        desc = (f"🗺️ Map: **{self.game_map}**\n\n" if self.game_map else "") + \
            _teams_overview(self.team1, self.team2)
        embed = discord.Embed(title="🎲 Random Teams", description=desc,
                              color=discord.Color.blurple())
        embed.add_field(
            name="🔁 Reroll votes",
            value=f"**{len(self.reroll_votes)}/{self.REROLL_THRESHOLD}** — vote to shuffle again",
            inline=False,
        )
        if self.note:
            embed.add_field(name="​", value=self.note, inline=False)
        embed.set_footer(text="A captain clicks Accept to lock these teams in.")
        return embed

    async def _alive(self, interaction):
        if self.key not in lobbies:
            await interaction.response.edit_message(
                content="❌ This match was cleared.", embed=None, view=None
            )
            self.stop()
            return False
        return True

    @discord.ui.button(label="Vote Reroll", emoji="🔁", style=discord.ButtonStyle.secondary)
    async def reroll_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._alive(interaction):
            return
        if not any(u.id == interaction.user.id for u in self._participants()):
            await interaction.response.send_message(
                "❌ Only players in this match can vote.", ephemeral=True
            )
            return
        if interaction.user.id in self.reroll_votes:
            await interaction.response.send_message(
                "❌ You already voted to reroll.", ephemeral=True
            )
            return
        self.reroll_votes.add(interaction.user.id)
        if len(self.reroll_votes) >= self.REROLL_THRESHOLD:
            self.shuffle()  # clears votes
            self.note = "🔁 **Teams rerolled!**"
        else:
            self.note = ""
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Accept Teams", emoji="✅", style=discord.ButtonStyle.success)
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._alive(interaction):
            return
        if interaction.user.id not in (self.red_captain.id, self.blue_captain.id):
            await interaction.response.send_message(
                "❌ Only a captain can accept the teams.", ephemeral=True
            )
            return
        self.stop()
        _register_match(
            self.key, self.red_captain, self.blue_captain,
            self.team1, self.team2, self.game_map,
        )
        self.note = "✅ **Teams locked in!**"
        await interaction.response.edit_message(embed=self.embed(), view=None)
        await interaction.channel.send(_ready_text(self.team1, self.team2, self.game_map))


async def _start_auction(interaction, key, red_captain, blue_captain):
    lobby = lobbies.get(key)
    if lobby is None:
        await interaction.response.edit_message(
            content="❌ This match was cleared.", embed=None, view=None
        )
        return
    _cid, mode = key
    team_size = GAME_MODES[mode] // 2
    pool = [
        p for p in lobby["players"]
        if p.id not in (red_captain.id, blue_captain.id)
    ]
    view = _AuctionView(key, red_captain, blue_captain, pool, lobby.get("map"), team_size)
    await interaction.response.edit_message(content=None, embed=view.embed(), view=view)


class _AuctionView(discord.ui.View):
    """List-style auction: each player goes up for bid; highest bidder wins and pays.

    Both captains start with BUDGET coins. If both captains skip a player, that player
    goes to the **back of the line**, so wanted players get auctioned first. When a team
    fills, the rest auto-fill the other team; if a whole lap passes with no bids on
    anyone, the leftovers are split evenly and the auction ends.
    """

    BUDGET = 25

    def __init__(self, key, red_captain, blue_captain, pool, game_map, team_size):
        super().__init__(timeout=None)
        self.key = key
        self.red_captain = red_captain
        self.blue_captain = blue_captain
        self.game_map = game_map
        self.team_size = team_size
        self.queue = list(pool)      # front of the queue is the player up for bid
        random.shuffle(self.queue)
        self.team1 = [red_captain]
        self.team2 = [blue_captain]
        self.coins = {red_captain.id: self.BUDGET, blue_captain.id: self.BUDGET}
        self.high_bid = 0
        self.high_bidder = None      # captain object
        self.passed = set()          # captain ids who passed on the current player
        self.skips_since_bid = 0     # consecutive skip-rotations with no bid (loop guard)
        self.note = ""               # last event, shown on the panel

    # ---- state helpers ----
    @property
    def current(self):
        return self.queue[0] if self.queue else None

    def _captain_obj(self, user):
        return self.red_captain if user.id == self.red_captain.id else self.blue_captain

    def _team_of(self, cap):
        return self.team1 if cap.id == self.red_captain.id else self.team2

    def _team_full(self, cap):
        return len(self._team_of(cap)) >= self.team_size

    def _reset_bidding(self):
        self.high_bid = 0
        self.high_bidder = None
        self.passed = set()

    def _assign(self, cap, cost):
        """Give the current (front) player to a captain's team for `cost` coins."""
        player = self.queue.pop(0)
        self._team_of(cap).append(player)
        self.coins[cap.id] -= cost
        self.skips_since_bid = 0
        self._reset_bidding()
        return player

    def _emptier_side(self):
        """The team with fewer players that isn't full (tie -> Team 1)."""
        if len(self.team1) >= self.team_size:
            return self.team2
        if len(self.team2) >= self.team_size:
            return self.team1
        return self.team1 if len(self.team1) <= len(self.team2) else self.team2

    def _auto_fill(self):
        """Once a team is full, the remaining players all go to the other team."""
        while self.queue and (len(self.team1) >= self.team_size or len(self.team2) >= self.team_size):
            target = self.team2 if len(self.team1) >= self.team_size else self.team1
            target.append(self.queue.pop(0))

    def _distribute_remaining(self):
        """Split every remaining player evenly across the teams (used when nobody bids)."""
        while self.queue:
            self._emptier_side().append(self.queue.pop(0))
        self._reset_bidding()

    def embed(self):
        cur = self.current
        embed = discord.Embed(title="💰 Player Auction", color=discord.Color.gold())
        if self.game_map:
            embed.description = f"🗺️ Map: **{self.game_map}**"
        embed.add_field(
            name="💰 Coins left",
            value=(
                f"🔴 {get_player_name(self.red_captain)}: **{self.coins[self.red_captain.id]}**\n"
                f"🔵 {get_player_name(self.blue_captain)}: **{self.coins[self.blue_captain.id]}**"
            ),
            inline=False,
        )
        if self.note:
            embed.add_field(name="​", value=self.note, inline=False)
        if cur is not None:
            bid_line = (
                f"Current bid: **{self.high_bid}** by {get_player_name(self.high_bidder)}"
                if self.high_bidder is not None else "No bids yet — bid or pass"
            )
            embed.add_field(name=f"🎯 Up for bid: {get_player_name(cur)}", value=bid_line, inline=False)
        embed.add_field(
            name="🔴 Team 1",
            value="\n".join(get_player_name(p) for p in self.team1) or "—",
            inline=True,
        )
        embed.add_field(
            name="🔵 Team 2",
            value="\n".join(get_player_name(p) for p in self.team2) or "—",
            inline=True,
        )
        left = max(0, len(self.queue) - 1)
        embed.set_footer(text=f"{left} players left after this · +1/+5 to bid, Pass to skip")
        return embed

    async def _guard(self, interaction):
        if self.key not in lobbies:
            await interaction.response.edit_message(
                content="❌ This match was cleared.", embed=None, view=None
            )
            self.stop()
            return False
        if interaction.user.id not in (self.red_captain.id, self.blue_captain.id):
            await interaction.response.send_message(
                "❌ Only the captains can bid.", ephemeral=True
            )
            return False
        return True

    async def _render(self, interaction):
        """Auto-fill on a full team, then finish or refresh the panel."""
        self._auto_fill()
        if self.current is None:
            self.stop()
            _register_match(
                self.key, self.red_captain, self.blue_captain,
                self.team1, self.team2, self.game_map,
            )
            await interaction.response.edit_message(
                content="✅ **Auction complete!**", embed=self.embed(), view=None
            )
            await interaction.channel.send(_ready_text(self.team1, self.team2, self.game_map))
        else:
            await interaction.response.edit_message(embed=self.embed(), view=self)

    async def _bid(self, interaction, inc):
        if not await self._guard(interaction):
            return
        cap = self._captain_obj(interaction.user)
        if self._team_full(cap):
            await interaction.response.send_message(
                "❌ Your team is already full.", ephemeral=True
            )
            return
        if self.high_bidder is not None and self.high_bidder.id == cap.id:
            await interaction.response.send_message(
                "❌ You're already the high bidder.", ephemeral=True
            )
            return
        new_bid = self.high_bid + inc
        if new_bid > self.coins[cap.id]:
            await interaction.response.send_message(
                f"❌ You only have {self.coins[cap.id]} coins.", ephemeral=True
            )
            return
        self.high_bid = new_bid
        self.high_bidder = cap
        self.passed = set()
        self.skips_since_bid = 0
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def _pass(self, interaction):
        if not await self._guard(interaction):
            return
        cap = self._captain_obj(interaction.user)
        cur = self.current
        if self.high_bidder is not None:
            if self.high_bidder.id == cap.id:
                await interaction.response.send_message(
                    "❌ You're the high bidder — you can't pass.", ephemeral=True
                )
                return
            # The challenger concedes -> the high bidder wins and pays.
            winner, price = self.high_bidder, self.high_bid
            self._assign(winner, price)
            self.note = f"💰 **{get_player_name(cur)}** won by {get_player_name(winner)} for {price}."
            await self._render(interaction)
            return
        # No bids yet on this player.
        self.passed.add(cap.id)
        if len(self.passed) >= 2:
            # Both captains skipped -> send this player to the back of the line so
            # wanted players get auctioned first.
            self.queue.append(self.queue.pop(0))
            self.skips_since_bid += 1
            self._reset_bidding()
            self.note = f"⏭️ **{get_player_name(cur)}** skipped — sent to the back."
            if self.skips_since_bid >= len(self.queue):
                # A whole lap with no bids on anyone -> split the rest evenly and finish.
                self._distribute_remaining()
                self.note = "⏭️ No bids on the remaining players — split evenly."
            await self._render(interaction)
        else:
            await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Bid +1", emoji="💰", style=discord.ButtonStyle.primary)
    async def bid1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._bid(interaction, 1)

    @discord.ui.button(label="Bid +5", emoji="💰", style=discord.ButtonStyle.primary)
    async def bid5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._bid(interaction, 5)

    @discord.ui.button(label="Pass", emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def pass_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pass(interaction)


async def _advance_to_map_ban(key, channel):
    """Lock captains in and start map ban -> team pick -> draft."""
    _cid, mode = key
    lobby = lobbies[key]
    lobby["locked"] = True
    cap1, cap2 = lobby["captains"][0], lobby["captains"][1]

    async def after_map_ban(selected_map):
        lobby["map"] = selected_map
        picker, other = lobby["captains"][0], lobby["captains"][1]
        view = _TeamSelectView(key, picker, other)
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
    """Roll random captains (rerollable), claim/step down, or lock the two in."""

    def __init__(self, key):
        super().__init__(timeout=None)
        self.key = key

    async def _lobby_for(self, interaction):
        lobby = lobbies.get(self.key)
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
        await _advance_to_map_ban(self.key, interaction.channel)


def setup(bot):
    @bot.tree.command(name="join", description="Join a queue")
    @app_commands.choices(mode=MODE_CHOICES)
    async def join(interaction: discord.Interaction, mode: app_commands.Choice[str]):
        if not await ensure_queue_channel(interaction):
            return

        key = (interaction.channel.id, mode.value)
        ok, error = _join_result(interaction.user, key)
        if not ok:
            await interaction.response.send_message(error, ephemeral=True)
            return

        await interaction.response.send_message(_queue_text(key), view=_QueueView(key))

    @bot.tree.command(name="leave", description="Leave your current queue")
    async def leave(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        user = interaction.user
        key = _find_user_queue_key(user, interaction.channel.id)
        if key is None:
            if _find_player_lobby(user) is not None:
                await interaction.response.send_message(
                    "❌ The match has already started — you can't leave now.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                "You're not in a queue in this channel.",
                ephemeral=True,
            )
            return

        _leave_result(user, key)
        await interaction.response.send_message(_queue_text(key), view=_QueueView(key))

    @bot.tree.command(name="start", description="Start the match once your queue is full")
    async def start(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        key = _find_user_queue_key(interaction.user, interaction.channel.id)
        if key is None:
            await interaction.response.send_message(
                "❌ You're not in a queue in this channel.", ephemeral=True
            )
            return

        mode = key[1]
        queue = queues[key]
        size = GAME_MODES[mode]

        if len(queue) < size:
            await interaction.response.send_message(
                f"❌ The **{mode}** queue isn't full yet ({len(queue)}/{size}).",
                ephemeral=True,
            )
            return

        lobbies[key] = {
            "channel_id": key[0],
            "mode": mode,
            "players": queue.copy(),
            "captains": [],
            "map": None,
            "locked": False,
        }
        queues.pop(key, None)
        queue_last_activity.pop(key, None)

        view = _CaptainSelectView(key)
        await interaction.response.send_message(
            embed=_captain_embed(lobbies[key]), view=view
        )

    @bot.tree.command(
        name="open",
        description="Reopen the queue after /start, before captains lock in",
    )
    async def open_queue(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        key = _find_player_lobby_key(interaction.user, interaction.channel.id)
        if key is None:
            await interaction.response.send_message(
                "❌ You're not in a match that's forming in this channel.",
                ephemeral=True,
            )
            return

        lobby = lobbies[key]
        if lobby.get("locked"):
            await interaction.response.send_message(
                "❌ Captains are already locked in — the match is underway.",
                ephemeral=True,
            )
            return

        # Move the lobby back to an open queue so players can leave/expand again.
        players = lobby["players"]
        lobbies.pop(key, None)
        queues[key] = list(players)
        queue_last_activity[key] = time.monotonic()

        await interaction.response.send_message(
            "🔓 **Queue reopened** — players can `/leave` again, or `/expand` for "
            "more slots. Run `/start` when you're ready.\n\n"
            f"{_queue_text(key)}",
            view=_QueueView(key),
        )

    @bot.tree.command(
        name="close",
        description="Close an under-full queue into the format matching your player count",
    )
    async def close(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        key = _find_user_queue_key(interaction.user, interaction.channel.id)
        if key is None:
            await interaction.response.send_message(
                "❌ You're not in a queue in this channel.", ephemeral=True
            )
            return

        cid, mode = key
        queue = queues[key]
        n = len(queue)
        target_mode = _format_for_count(n)
        if target_mode is None:
            await interaction.response.send_message(
                f"❌ Closing needs an even number of players (4–20) — you have {n}.",
                ephemeral=True,
            )
            return

        target = (cid, target_mode)
        if target in lobbies or target in active_matches or (target != key and queues.get(target)):
            await interaction.response.send_message(
                f"❌ The **{target_mode}** slot is busy in this channel — try again shortly.",
                ephemeral=True,
            )
            return

        players = queue.copy()
        queues.pop(key, None)
        queue_last_activity.pop(key, None)
        queues.pop(target, None)
        queue_last_activity.pop(target, None)
        lobbies[target] = {
            "channel_id": cid,
            "mode": target_mode,
            "players": players,
            "captains": [],
            "map": None,
            "locked": False,
        }

        view = _CaptainSelectView(target)
        await interaction.response.send_message(
            content=f"🔒 **{mode}** closed into **{target_mode}** with {n} players.",
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

        key = _find_user_queue_key(interaction.user, interaction.channel.id)
        if key is None:
            await interaction.response.send_message(
                "❌ You're not in a queue in this channel.", ephemeral=True
            )
            return

        cid, mode = key
        queue = queues[key]
        size = GAME_MODES[mode]
        if len(queue) < size:
            await interaction.response.send_message(
                f"❌ The **{mode}** queue isn't full yet ({len(queue)}/{size}) — "
                f"`/expand` only works on a full queue.",
                ephemeral=True,
            )
            return

        target_mode = _format_for_count(size + 2)
        if target_mode is None:
            await interaction.response.send_message(
                f"❌ **{mode}** is already the largest format — can't expand further.",
                ephemeral=True,
            )
            return

        target = (cid, target_mode)
        if target in lobbies or target in active_matches or queues.get(target):
            await interaction.response.send_message(
                f"❌ The **{target_mode}** slot is busy in this channel — try again shortly.",
                ephemeral=True,
            )
            return

        players = queue.copy()
        queues.pop(key, None)
        queue_last_activity.pop(key, None)
        queues[target] = players
        queue_last_activity[target] = time.monotonic()

        remaining = GAME_MODES[target_mode] - len(players)
        await interaction.response.send_message(
            f"⬆️ **{mode}** expanded to **{target_mode}** — {remaining} more can join!\n\n"
            + _queue_text(target),
            view=_QueueView(target),
        )

    @bot.tree.command(name="queues", description="View this channel's queues")
    async def queues_command(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        cid = interaction.channel.id
        embed = discord.Embed(title="Current Queues", color=discord.Color.green())

        keys = {k for k in queues if k[0] == cid} | {k for k in lobbies if k[0] == cid}
        if not keys:
            embed.description = "*No active queues in this channel.*"
        else:
            order = list(GAME_MODES)
            for key in sorted(keys, key=lambda k: order.index(k[1])):
                mode = key[1]
                size = GAME_MODES[mode]
                if key in lobbies:
                    lobby = lobbies[key]
                    value = "⏳ *Choosing captains...*\n" + "\n".join(
                        f"👑 {get_player_name(p)}" if p in lobby["captains"]
                        else get_player_name(p)
                        for p in lobby["players"]
                    )
                    header = f"{mode} (full — {len(lobby['captains'])}/2 captains)"
                else:
                    q = queues.get(key, [])
                    value = "\n".join(get_player_name(p) for p in q) if q else "*Empty*"
                    header = f"{mode} ({len(q)}/{size})"
                embed.add_field(name=header, value=value, inline=False)

        await interaction.response.send_message(embed=embed)

    @bot.tree.command(
        name="clear",
        description="(Admin/Organizer) Clear one queue/match (pick a mode) or all if none given",
    )
    @app_commands.choices(mode=MODE_CHOICES)
    async def clear(interaction: discord.Interaction, mode: app_commands.Choice[str] = None):
        if not await ensure_queue_channel(interaction):
            return
        if not await ensure_organizer(interaction):
            return

        all_state = (queues, lobbies, drafts, active_matches, pending_results, queue_last_activity)

        if mode is None:
            for d in all_state:
                d.clear()
            await interaction.response.send_message("🗑️ All queues and matches cleared.")
            return

        # Clear just this channel's queue/match for the chosen mode — at any stage
        # (waiting, captain selection, draft, or awaiting result).
        key = (interaction.channel.id, mode.value)
        existed = any(key in d for d in (queues, lobbies, drafts, active_matches))
        for d in all_state:
            d.pop(key, None)

        if existed:
            await interaction.response.send_message(
                f"🗑️ Cleared the **{mode.value}** queue/match in this channel."
            )
        else:
            await interaction.response.send_message(
                f"ℹ️ There's no active **{mode.value}** queue or match in this channel.",
                ephemeral=True,
            )

    @bot.tree.command(name="remove", description="(Admin/Organizer) Remove a player from their queue")
    async def remove(interaction: discord.Interaction, player: discord.Member):
        if not await ensure_queue_channel(interaction):
            return
        if not await ensure_organizer(interaction):
            return

        key = _find_user_queue_key(player, interaction.channel.id)
        if key is None:
            in_lobby = any(
                any(u.id == player.id for u in lob["players"])
                for lob in lobbies.values()
                if lob["channel_id"] == interaction.channel.id
            )
            if in_lobby:
                text = "❌ That player's queue is already full and forming a match — can't remove now."
            else:
                text = "❌ That player isn't in an open queue in this channel."
            await interaction.response.send_message(text, ephemeral=True)
            return

        mode = key[1]
        queue = queues[key]
        target = next(u for u in queue if u.id == player.id)
        queue.remove(target)
        if not queue:
            queues.pop(key, None)
            queue_last_activity.pop(key, None)

        await interaction.response.send_message(
            f"🚫 {get_player_name(target)} was removed from the **{mode}** queue "
            f"by an admin ({len(queue)}/{GAME_MODES[mode]})."
        )


def start_background_tasks(bot):
    """Start the loop that auto-closes queues with no join activity."""

    @tasks.loop(seconds=60)
    async def close_idle_queues():
        now = time.monotonic()
        for key, queue in list(queues.items()):
            if not queue or key in lobbies:
                continue
            last = queue_last_activity.get(key)
            if last is None:
                queue_last_activity[key] = now
                continue
            if now - last >= QUEUE_INACTIVITY_SECONDS:
                names = ", ".join(get_player_name(p) for p in queue)
                cid, mode = key
                queues.pop(key, None)
                queue_last_activity.pop(key, None)
                channel = bot.get_channel(cid)
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

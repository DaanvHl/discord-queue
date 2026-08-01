"""Match result reporting and confirmation: /result, /confirm, /force-result."""
import discord
from discord import app_commands

from checks import ensure_organizer, ensure_queue_channel
from config import BRACKET_LABELS, GAME_MODES, RESULTS_CHANNEL_ID
from ranks import update_member_ranks
from db import (
    add_points,
    calculate_points_change,
    commit,
    get_bracket,
    get_player_name,
    get_points,
    get_streak,
    record_game,
    record_match,
    streak_bonus,
)
from state import active_matches, pending_results

MODE_CHOICES = [app_commands.Choice(name=m, value=m) for m in GAME_MODES]
WINNER_CHOICES = [
    app_commands.Choice(name="🔴 Red Team", value="team1"),
    app_commands.Choice(name="🔵 Blue Team", value="team2"),
    app_commands.Choice(name="🤝 Draw", value="draw"),
]


def _apply_result(match, outcome):
    """Apply a confirmed result: update points, records, streaks, and log the match.

    Returns a human-readable summary of the outcome.
    """
    mode = match["mode"]
    bracket = get_bracket(mode)
    team1, team2 = match["team1"], match["team2"]

    # Snapshot ratings before any change; default after == before (used for draws).
    before = {p.id: get_points(p.id, bracket) for p in team1 + team2}
    after = dict(before)

    if outcome == "draw":
        for player in team1 + team2:
            record_game(player.id, mode, "draw")
        summary = "🤝 **Draw** — no points changed."
    else:
        if outcome == "team1":
            winners, losers = team1, team2
            winner_label = "🔴 Red Team"
        else:
            winners, losers = team2, team1
            winner_label = "🔵 Blue Team"

        winner_avg = sum(before[p.id] for p in winners) / len(winners)
        loser_avg = sum(before[p.id] for p in losers) / len(losers)
        gain, loss = calculate_points_change(winner_avg, loser_avg)

        streak_notes = []
        for player in winners:
            record_game(player.id, mode, "win")
            streak = get_streak(player.id, mode)
            bonus = streak_bonus(streak)
            player_gain = round(gain * (1 + bonus))
            after[player.id] = add_points(player.id, bracket, player_gain)
            if bonus > 0:
                streak_notes.append(
                    f"🔥 {get_player_name(player)} — {streak} win streak "
                    f"(+{player_gain}, +{round(bonus * 100)}% bonus)"
                )
        for player in losers:
            after[player.id] = add_points(player.id, bracket, -loss)
            record_game(player.id, mode, "loss")

        summary = (
            f"🏆 **{winner_label} wins!**\n"
            f"Bracket: **{BRACKET_LABELS[bracket]}**\n"
            f"Winners: **+{gain}** points  •  Losers: **-{loss}** points"
        )
        if streak_notes:
            summary += "\n\n" + "\n".join(streak_notes)

    # Log the match for the web history + results channel (team1 = red, team2 = blue).
    def entries(team):
        return [
            {
                "name": get_player_name(p),
                "before": before[p.id],
                "after": after[p.id],
                "delta": after[p.id] - before[p.id],
            }
            for p in team
        ]

    entries1, entries2 = entries(team1), entries(team2)
    match_id = record_match(mode, bracket, match.get("map"), outcome, entries1, entries2)
    log = {
        "id": match_id,
        "mode": mode,
        "bracket": bracket,
        "map": match.get("map"),
        "winner": outcome,
        "team1": entries1,
        "team2": entries2,
    }
    return summary, log


def _fmt_line(p):
    d = p["delta"]
    delta = f"(+{d})" if d > 0 else (f"({d})" if d < 0 else "(+0)")
    return f"{p['name']} — {p['before']} → **{p['after']}** {delta}"


def _team_avg(team, key):
    return round(sum(p[key] for p in team) / len(team)) if team else 0


def _build_log_embed(log):
    """A Discord embed summarising a completed match for the results channel."""
    bracket = log["bracket"].capitalize()
    if log["winner"] == "draw":
        result, colour = "🤝 DRAW", discord.Color.light_grey()
    elif log["winner"] == "team1":
        result, colour = "🔴 Red Team wins", discord.Color.red()
    else:
        result, colour = "🔵 Blue Team wins", discord.Color.blue()

    embed = discord.Embed(
        title=f"Match {log['id']:04d} · {log['mode']} {bracket}",
        description=f"🗺️ Map: **{log['map'] or '—'}**\n🏆 {result}",
        colour=colour,
    )
    t1, t2 = log["team1"], log["team2"]
    embed.add_field(
        name=f"🔴 Red Team — Avg {_team_avg(t1, 'before')} → {_team_avg(t1, 'after')}",
        value="\n".join(_fmt_line(p) for p in t1) or "—",
        inline=False,
    )
    embed.add_field(
        name=f"🔵 Blue Team — Avg {_team_avg(t2, 'before')} → {_team_avg(t2, 'after')}",
        value="\n".join(_fmt_line(p) for p in t2) or "—",
        inline=False,
    )
    return embed


def _match_key_for_captain(user_id):
    """Key (channel_id, mode) of the active match this user is a captain of, or None."""
    for key, match in active_matches.items():
        if user_id in (match["captain1"].id, match["captain2"].id):
            return key
    return None


async def _apply_and_close(key, outcome):
    """Apply an outcome, close the match, and return (summary, log, players)."""
    match = active_matches[key]
    summary, log = _apply_result(match, outcome)
    commit()
    players = match["team1"] + match["team2"]
    pending_results.pop(key, None)
    active_matches.pop(key, None)
    return summary, log, players


async def _post_side_effects(interaction, log, players, outcome):
    """Log to the results channel and re-sync rank roles after a result."""
    if RESULTS_CHANNEL_ID:
        log_channel = interaction.client.get_channel(RESULTS_CHANNEL_ID)
        if log_channel is not None:
            try:
                await log_channel.send(embed=_build_log_embed(log))
            except discord.HTTPException:
                pass
    if outcome != "draw":  # draws move no points
        for player in players:
            await update_member_ranks(interaction.guild, player)


class _ResultView(discord.ui.View):
    """Confirm / Cancel buttons on a pending result — only the opposing captain may use them."""

    def __init__(self, key, reporter_id):
        super().__init__(timeout=None)
        self.key = key
        self.reporter_id = reporter_id

    async def _opposing_ok(self, interaction):
        if self.key not in pending_results or self.key not in active_matches:
            await interaction.response.send_message(
                "❌ This result is no longer pending.", ephemeral=True
            )
            return False
        match = active_matches[self.key]
        uid = interaction.user.id
        if uid not in (match["captain1"].id, match["captain2"].id):
            await interaction.response.send_message(
                "❌ Only the opposing captain can do this.", ephemeral=True
            )
            return False
        if uid == self.reporter_id:
            await interaction.response.send_message(
                "❌ The opposing captain must confirm — not the one who reported.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirm", emoji="✅", style=discord.ButtonStyle.success)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._opposing_ok(interaction):
            return
        outcome = pending_results[self.key]["winner"]
        self.stop()
        summary, log, players = await _apply_and_close(self.key, outcome)
        await interaction.response.edit_message(
            content=f"✅ **{self.key[1]}** result confirmed. Match closed.\n\n{summary}",
            embed=None,
            view=None,
        )
        await _post_side_effects(interaction, log, players, outcome)

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._opposing_ok(interaction):
            return
        pending_results.pop(self.key, None)
        self.stop()
        await interaction.response.edit_message(
            content="✖️ Result cancelled. A captain can report again with `/result`.",
            embed=None,
            view=None,
        )


class _ForceResultView(discord.ui.View):
    """Ephemeral Confirm / Cancel for an admin forcing a result (only the admin sees it)."""

    def __init__(self, key, outcome):
        super().__init__(timeout=120)
        self.key = key
        self.outcome = outcome

    @discord.ui.button(label="Confirm", emoji="✅", style=discord.ButtonStyle.success)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.key not in active_matches:
            self.stop()
            await interaction.response.edit_message(
                content="❌ That match is no longer active — nothing to force.", view=None
            )
            return
        self.stop()
        outcome = self.outcome
        summary, log, players = await _apply_and_close(self.key, outcome)
        await interaction.response.edit_message(
            content=f"✅ Forced the **{self.key[1]}** result. Match closed.", view=None
        )
        # Announce publicly so the players see the outcome.
        try:
            await interaction.channel.send(
                f"🛠️ **{self.key[1]}** result set by an admin. Match closed.\n\n{summary}"
            )
        except discord.HTTPException:
            pass
        await _post_side_effects(interaction, log, players, outcome)

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content="✖️ Cancelled — no result was set.", view=None
        )


def setup(bot):
    @bot.tree.command(name="result", description="Report a match result")
    @app_commands.choices(winner=WINNER_CHOICES)
    async def result(interaction: discord.Interaction, winner: app_commands.Choice[str]):
        if not await ensure_queue_channel(interaction):
            return

        # Find the match this captain belongs to (a captain is in only one).
        key = _match_key_for_captain(interaction.user.id)
        if key is None:
            await interaction.response.send_message(
                "❌ You're not a captain of an active match.",
                ephemeral=True,
            )
            return

        if key in pending_results:
            await interaction.response.send_message(
                "❌ This match already has a pending result.",
                ephemeral=True,
            )
            return

        mode = key[1]
        match = active_matches[key]
        pending_results[key] = {
            "winner": winner.value,
            "reported_by": interaction.user.id,
        }

        # Ping the opposing captain — the one who must confirm.
        if interaction.user.id == match["captain1"].id:
            opposing = match["captain2"]
        else:
            opposing = match["captain1"]

        await interaction.response.send_message(
            f"⚠️ **{mode} result pending confirmation**\n\n"
            f"Reported result: **{winner.name}**\n\n"
            f"<@{opposing.id}>, confirm or cancel below.",
            view=_ResultView(key, interaction.user.id),
        )

    @bot.tree.command(name="confirm", description="Confirm match result")
    async def confirm(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        key = _match_key_for_captain(interaction.user.id)
        if key is None or key not in pending_results:
            await interaction.response.send_message(
                "❌ No pending result for a match you're a captain of.",
                ephemeral=True,
            )
            return

        if interaction.user.id == pending_results[key]["reported_by"]:
            await interaction.response.send_message(
                "❌ The other captain must confirm.",
                ephemeral=True,
            )
            return

        outcome = pending_results[key]["winner"]
        summary, log, players = await _apply_and_close(key, outcome)
        await interaction.response.send_message(
            f"✅ **{key[1]}** result confirmed. Match closed.\n\n{summary}"
        )
        await _post_side_effects(interaction, log, players, outcome)

    @bot.tree.command(
        name="force-result",
        description="(Admin/Organizer) Set a match result without being a captain",
    )
    @app_commands.choices(format=MODE_CHOICES, winner=WINNER_CHOICES)
    async def force_result(
        interaction: discord.Interaction,
        format: app_commands.Choice[str],
        winner: app_commands.Choice[str],
    ):
        if not await ensure_queue_channel(interaction):
            return
        if not await ensure_organizer(interaction):
            return

        key = (interaction.channel.id, format.value)
        if key not in active_matches:
            await interaction.response.send_message(
                f"❌ There's no active **{format.value}** match in this channel "
                f"(a match must be past the draft, awaiting a result).",
                ephemeral=True,
            )
            return

        pending_note = ""
        if key in pending_results:
            pending_note = "\n\n⚠️ This overrides the result currently pending confirmation."

        await interaction.response.send_message(
            f"⚠️ Force the **{format.value}** result to **{winner.name}**?\n"
            f"This closes the match and updates points, records and ranks.{pending_note}",
            view=_ForceResultView(key, winner.value),
            ephemeral=True,
        )

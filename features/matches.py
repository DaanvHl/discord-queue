"""Match result reporting and confirmation: /result, /confirm."""
import discord
from discord import app_commands

from checks import ensure_queue_channel
from config import BRACKET_LABELS
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
    streak_bonus,
)
from state import active_matches, pending_results


def _apply_result(match, outcome):
    """Apply a confirmed result: update points, records, and streaks.

    Returns a human-readable summary of the outcome.
    """
    mode = match["mode"]
    bracket = get_bracket(mode)

    if outcome == "draw":
        for player in match["team1"] + match["team2"]:
            record_game(player.id, mode, "draw")
        return "🤝 **Draw** — no points changed."

    if outcome == "team1":
        winners, losers = match["team1"], match["team2"]
        winner_label = "🔴 Red Team"
    else:
        winners, losers = match["team2"], match["team1"]
        winner_label = "🔵 Blue Team"

    winner_avg = sum(get_points(p.id, bracket) for p in winners) / len(winners)
    loser_avg = sum(get_points(p.id, bracket) for p in losers) / len(losers)
    gain, loss = calculate_points_change(winner_avg, loser_avg)

    streak_notes = []
    for player in winners:
        record_game(player.id, mode, "win")
        streak = get_streak(player.id, mode)
        bonus = streak_bonus(streak)
        player_gain = round(gain * (1 + bonus))
        add_points(player.id, bracket, player_gain)
        if bonus > 0:
            streak_notes.append(
                f"🔥 {get_player_name(player)} — {streak} win streak "
                f"(+{player_gain}, +{round(bonus * 100)}% bonus)"
            )
    for player in losers:
        add_points(player.id, bracket, -loss)
        record_game(player.id, mode, "loss")

    summary = (
        f"🏆 **{winner_label} wins!**\n"
        f"Bracket: **{BRACKET_LABELS[bracket]}**\n"
        f"Winners: **+{gain}** points  •  Losers: **-{loss}** points"
    )
    if streak_notes:
        summary += "\n\n" + "\n".join(streak_notes)
    return summary


def setup(bot):
    @bot.tree.command(name="result", description="Report a match result")
    @app_commands.choices(winner=[
        app_commands.Choice(name="🔴 Red Team", value="team1"),
        app_commands.Choice(name="🔵 Blue Team", value="team2"),
        app_commands.Choice(name="🤝 Draw", value="draw"),
    ])
    async def result(interaction: discord.Interaction, winner: app_commands.Choice[str]):
        if not await ensure_queue_channel(interaction):
            return

        channel_id = interaction.channel.id

        if channel_id not in active_matches:
            await interaction.response.send_message(
                "❌ No active match found in this channel.",
                ephemeral=True,
            )
            return

        match = active_matches[channel_id]
        captains = [match["captain1"].id, match["captain2"].id]

        if interaction.user.id not in captains:
            await interaction.response.send_message(
                "❌ Only captains can report results.",
                ephemeral=True,
            )
            return

        if channel_id in pending_results:
            await interaction.response.send_message(
                "❌ This match already has a pending result.",
                ephemeral=True,
            )
            return

        pending_results[channel_id] = {
            "winner": winner.value,
            "reported_by": interaction.user.id,
        }

        await interaction.response.send_message(
            f"⚠️ **Result pending confirmation**\n\n"
            f"Reported result: **{winner.name}**\n\n"
            f"The opposing captain must use:\n"
            f"`/confirm`"
        )

    @bot.tree.command(name="confirm", description="Confirm match result")
    async def confirm(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        channel_id = interaction.channel.id

        if channel_id not in pending_results:
            await interaction.response.send_message(
                "❌ No pending result.",
                ephemeral=True,
            )
            return

        if channel_id not in active_matches:
            await interaction.response.send_message(
                "❌ No active match.",
                ephemeral=True,
            )
            return

        match = active_matches[channel_id]
        captains = [match["captain1"].id, match["captain2"].id]
        report = pending_results[channel_id]

        if interaction.user.id == report["reported_by"]:
            await interaction.response.send_message(
                "❌ The other captain must confirm.",
                ephemeral=True,
            )
            return

        if interaction.user.id not in captains:
            await interaction.response.send_message(
                "❌ Only captains can confirm.",
                ephemeral=True,
            )
            return

        outcome = report["winner"]
        summary = _apply_result(match, outcome)
        commit()

        players = match["team1"] + match["team2"]
        del pending_results[channel_id]
        del active_matches[channel_id]

        await interaction.response.send_message(
            f"✅ Result confirmed. Match closed.\n\n{summary}"
        )

        # Sync rank roles after points change (skipped on draws — no points move).
        if outcome != "draw":
            for player in players:
                await update_member_ranks(interaction.guild, player)

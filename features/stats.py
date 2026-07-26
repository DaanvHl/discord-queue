"""Player stats and rankings: /stats, /leaderboard."""
import discord
from discord import app_commands

from checks import ensure_queue_channel
from config import BRACKET_LABELS, BRACKETS, GAME_MODES, STREAK_THRESHOLD
from db import (
    get_bracket_record,
    get_format_stats,
    get_leaderboard,
    get_player_name,
    get_points,
    is_registered,
    win_rate,
)
from ranks import rank_for_points

BRACKET_CHOICES = [
    app_commands.Choice(name=BRACKET_LABELS[b], value=b) for b in BRACKETS
]


def setup(bot):
    @bot.tree.command(name="stats", description="View your points and match record")
    async def stats(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        if not is_registered(interaction.user.id):
            await interaction.response.send_message(
                "❌ You are not registered.",
                ephemeral=True,
            )
            return

        user_id = interaction.user.id
        name = get_player_name(interaction.user)

        embed = discord.Embed(
            title=f"📊 {name}'s Statistics",
            color=discord.Color.blue(),
        )

        # Rating + record per bracket.
        bracket_lines = []
        for b in BRACKETS:
            wins, losses = get_bracket_record(user_id, b)
            points = get_points(user_id, b)
            bracket_lines.append(
                f"**{BRACKET_LABELS[b]}:** {points} pts · {rank_for_points(points)} · "
                f"{wins}W / {losses}L ({win_rate(wins, losses)}%)"
            )
        embed.add_field(name="🏅 Points & Record", value="\n".join(bracket_lines), inline=False)

        # Win/loss record per format, ordered like GAME_MODES.
        rows = get_format_stats(user_id)
        if rows:
            order = list(GAME_MODES)
            rows.sort(key=lambda r: order.index(r[0]) if r[0] in order else len(order))

            lines = []
            for mode, games, wins, losses, streak in rows:
                winrate = round((wins / games) * 100, 1) if games > 0 else 0
                line = f"**{mode}:** {wins}W / {losses}L ({winrate}%)"
                if streak >= STREAK_THRESHOLD:
                    line += f" 🔥{streak}"
                lines.append(line)
            record_text = "\n".join(lines)
        else:
            record_text = "*No games played yet.*"

        embed.add_field(name="🎮 Record by Format", value=record_text, inline=False)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="leaderboard", description="View the top players in a bracket")
    @app_commands.choices(bracket=BRACKET_CHOICES)
    async def leaderboard(interaction: discord.Interaction, bracket: app_commands.Choice[str]):
        if not await ensure_queue_channel(interaction):
            return

        rows = get_leaderboard(bracket.value)

        embed = discord.Embed(
            title=f"🏆 Leaderboard — {BRACKET_LABELS[bracket.value]}",
            color=discord.Color.gold(),
        )

        if rows:
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for i, (username, user_id, points) in enumerate(rows):
                rank = medals[i] if i < len(medals) else f"**{i + 1}.**"
                wins, losses = get_bracket_record(user_id, bracket.value)
                lines.append(
                    f"{rank} {username} — **{points}** · "
                    f"{wins}W/{losses}L ({win_rate(wins, losses)}%)"
                )
            embed.description = "\n".join(lines)
        else:
            embed.description = "*No ranked players yet.*"

        await interaction.response.send_message(embed=embed)

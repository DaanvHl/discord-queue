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
from ranks import RANK_COLORS, rank_for_points

BRACKET_CHOICES = [
    app_commands.Choice(name=BRACKET_LABELS[b], value=b) for b in BRACKETS
]


def build_profile_embed(user):
    """A profile card: avatar + registered name, record summary, ratings, formats."""
    user_id = user.id
    name = get_player_name(user)

    # Overall record across every format.
    rows = get_format_stats(user_id)
    total_w = sum(r[2] for r in rows)
    total_l = sum(r[3] for r in rows)
    total_games = sum(r[1] for r in rows)

    # Highest-rated section drives the card colour + headline.
    best_bracket = max(BRACKETS, key=lambda b: get_points(user_id, b))
    best_points = get_points(user_id, best_bracket)
    best_rank = rank_for_points(best_points)

    embed = discord.Embed(color=discord.Color(RANK_COLORS.get(best_rank, 0x4FD1C5)))
    embed.set_author(name=name, icon_url=user.display_avatar.url)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.description = (
        f"**{best_rank}** · {best_points} pts  —  peak section: "
        f"{BRACKET_LABELS[best_bracket].split(' ')[0]}"
    )

    # Overall record.
    embed.add_field(
        name="Record",
        value=(
            f"**{total_w}**W – **{total_l}**L · {win_rate(total_w, total_l)}% winrate\n"
            f"{total_games} games played"
        ),
        inline=False,
    )

    # Rating per section.
    rating_lines = []
    for b in BRACKETS:
        pts = get_points(user_id, b)
        w, l = get_bracket_record(user_id, b)
        rating_lines.append(
            f"**{BRACKET_LABELS[b]}** — {rank_for_points(pts)} · {pts} pts · "
            f"{w}W/{l}L ({win_rate(w, l)}%)"
        )
    embed.add_field(name="Ratings", value="\n".join(rating_lines), inline=False)

    # Per-format breakdown (only formats actually played), ordered like GAME_MODES.
    if rows:
        order = list(GAME_MODES)
        rows.sort(key=lambda r: order.index(r[0]) if r[0] in order else len(order))
        lines = []
        for mode, _games, w, l, streak in rows:
            line = f"`{mode}` {w}W/{l}L ({win_rate(w, l)}%)"
            if streak >= STREAK_THRESHOLD:
                line += f" · 🔥 {streak} streak"
            lines.append(line)
        embed.add_field(name="By Format", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="By Format", value="*No games played yet.*", inline=False)

    return embed


def setup(bot):
    @bot.tree.command(name="stats", description="View your profile card")
    async def stats(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        if not is_registered(interaction.user.id):
            await interaction.response.send_message(
                "❌ You are not registered.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(embed=build_profile_embed(interaction.user))

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

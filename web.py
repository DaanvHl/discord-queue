"""Embedded read-only web server: serves the leaderboard site + JSON stats.

Runs inside the bot process (same asyncio loop) and reads the same SQLite
database in READ-ONLY mode, so it can never modify bot data.
"""
import json
import os
import sqlite3

import discord
from aiohttp import web

from config import BRACKETS, DB_PATH, GAME_MODES, SETUPS_ENABLED, SETUPS_SECRET
from db import get_bracket
from ranks import rank_for_points

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

# Set by start_web_server so the setups callback can post to a channel.
_bot_client = None


def _connect():
    """Open a read-only connection to the database file."""
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def _leaderboard(bracket):
    """Players in a bracket, highest points first, with aggregated W/L/D."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT p.discord_id, p.username, r.points
            FROM ratings r
            JOIN players p ON p.discord_id = r.discord_id
            WHERE r.bracket = ?
            ORDER BY r.points DESC
            """,
            (bracket,),
        )
        players = cur.fetchall()

        result = []
        for i, (uid, name, points) in enumerate(players):
            cur.execute(
                "SELECT mode, games, wins, losses FROM format_stats WHERE discord_id=?",
                (uid,),
            )
            games = wins = losses = 0
            for mode, g, w, l in cur.fetchall():
                if mode in GAME_MODES and get_bracket(mode) == bracket:
                    games += g
                    wins += w
                    losses += l
            draws = max(0, games - wins - losses)
            decided = wins + losses
            winrate = round(wins / decided * 100, 1) if decided else 0.0

            result.append({
                "rank": i + 1,
                "player": name,
                "tier": rank_for_points(points),
                "points": points,
                "w": wins,
                "l": losses,
                "d": draws,
                "winrate": winrate,
            })
        return result
    finally:
        conn.close()


def _most_active(limit=10):
    """Players ordered by total games played across all formats."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT p.username, COALESCE(SUM(f.wins + f.losses), 0) AS total
            FROM players p
            LEFT JOIN format_stats f ON f.discord_id = p.discord_id
            GROUP BY p.discord_id
            HAVING total > 0
            ORDER BY total DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [{"player": name, "games": total} for name, total in cur.fetchall()]
    finally:
        conn.close()


def _matches(limit=50):
    """Recent matches, newest first, with parsed rosters and team averages."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, created_at, mode, bracket, game_map, winner, team1, team2
            FROM matches
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        out = []
        for mid, created, mode, bracket, game_map, winner, t1, t2 in cur.fetchall():
            team1 = json.loads(t1)
            team2 = json.loads(t2)

            def avg(team, key):
                return round(sum(p[key] for p in team) / len(team)) if team else 0

            out.append({
                "id": mid,
                "created_at": created,
                "mode": mode,
                "bracket": bracket,
                "map": game_map,
                "winner": winner,
                "team1": team1,
                "team2": team2,
                "team1_avg_before": avg(team1, "before"),
                "team1_avg_after": avg(team1, "after"),
                "team2_avg_before": avg(team2, "before"),
                "team2_avg_after": avg(team2, "after"),
            })
        return out
    finally:
        conn.close()


async def _handle_index(request):
    return web.FileResponse(os.path.join(WEB_DIR, "index.html"))


async def _handle_leaderboard(request):
    bracket = request.query.get("bracket", "medium")
    if bracket not in BRACKETS:
        bracket = "medium"
    return web.json_response(_leaderboard(bracket))


async def _handle_active(request):
    return web.json_response(_most_active())


async def _handle_matches(request):
    return web.json_response(_matches())


# --- Setups pick & ban callback (only wired up when the feature is enabled) ---

def _build_setups_embed(data):
    """Render a finished setups draft (host/guest bans + loadouts) as an embed."""
    host, guest = data["host"], data["guest"]

    def fmt_bans(side):
        return ", ".join(f"~~{b['name']}~~" for b in side.get("bans", [])) or "_no bans_"

    def fmt_setups(side):
        lines = [
            f"`{s['n']}.` {s.get('turret') or '—'} · {s.get('hull') or '—'} · {s.get('paint') or '_no paint_'}"
            for s in side.get("setups", [])
        ]
        return "\n".join(lines) or "_no setups_"

    embed = discord.Embed(
        title="🎮 Setup Draft — complete",
        description="Pick & ban finished. Here are both captains' loadouts.",
        color=discord.Color.green(),
    )
    embed.add_field(name=f"🔵 {host['name']}",
                    value=f"<@{host['discordId']}>\n{fmt_bans(host)}", inline=True)
    embed.add_field(name=f"🔴 {guest['name']}",
                    value=f"<@{guest['discordId']}>\n{fmt_bans(guest)}", inline=True)
    embed.add_field(name="​", value="​", inline=False)
    embed.add_field(name=f"{host['name']} setups", value=fmt_setups(host), inline=True)
    embed.add_field(name=f"{guest['name']} setups", value=fmt_setups(guest), inline=True)
    return embed


async def _handle_setups_callback(request):
    if request.headers.get("x-setups-secret") != SETUPS_SECRET:
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)

    meta = data.get("meta") or {}
    try:
        channel_id = int(meta.get("channelId") or 0)
    except (TypeError, ValueError):
        channel_id = 0

    if _bot_client is not None and channel_id:
        channel = _bot_client.get_channel(channel_id)
        if channel is not None:
            try:
                await channel.send(embed=_build_setups_embed(data))
            except discord.HTTPException:
                pass

    return web.json_response({"ok": True})


def build_app():
    app = web.Application()
    app.router.add_get("/", _handle_index)
    app.router.add_get("/api/leaderboard", _handle_leaderboard)
    app.router.add_get("/api/active", _handle_active)
    app.router.add_get("/api/matches", _handle_matches)
    if SETUPS_ENABLED:
        app.router.add_post("/setups-callback", _handle_setups_callback)
    return app


async def start_web_server(bot=None):
    """Start the web server on the platform's PORT (Railway sets this)."""
    global _bot_client
    _bot_client = bot
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server listening on 0.0.0.0:{port}")
    return runner

"""Embedded read-only web server: serves the leaderboard site + JSON stats.

Runs inside the bot process (same asyncio loop) and reads the same SQLite
database in READ-ONLY mode, so it can never modify bot data.
"""
import os
import sqlite3

from aiohttp import web

from config import BRACKETS, DB_PATH, GAME_MODES
from db import get_bracket
from ranks import rank_for_points

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


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
            SELECT p.username, COALESCE(SUM(f.games), 0) AS total
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


async def _handle_index(request):
    return web.FileResponse(os.path.join(WEB_DIR, "index.html"))


async def _handle_leaderboard(request):
    bracket = request.query.get("bracket", "medium")
    if bracket not in BRACKETS:
        bracket = "medium"
    return web.json_response(_leaderboard(bracket))


async def _handle_active(request):
    return web.json_response(_most_active())


def build_app():
    app = web.Application()
    app.router.add_get("/", _handle_index)
    app.router.add_get("/api/leaderboard", _handle_leaderboard)
    app.router.add_get("/api/active", _handle_active)
    return app


async def start_web_server():
    """Start the web server on the platform's PORT (Railway sets this)."""
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server listening on 0.0.0.0:{port}")
    return runner

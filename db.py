"""Database access: schema/migration, player data, and the points/streak math."""
import json
import os
import sqlite3

from config import (
    BRACKETS,
    DB_PATH,
    GAME_MODES,
    K_FACTOR,
    LOSS_RATIO,
    MIN_GAIN,
    MIN_LOSS,
    STARTING_POINTS,
    STREAK_BONUS_MAX,
    STREAK_BONUS_PER_WIN,
    STREAK_THRESHOLD,
)

# Make sure the target directory exists (e.g. a mounted volume like /data).
_db_dir = os.path.dirname(DB_PATH)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)

db = sqlite3.connect(DB_PATH)
cursor = db.cursor()


def _init_schema():
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS players (
        discord_id INTEGER PRIMARY KEY,
        username TEXT NOT NULL
    )
    """)

    # One rating row per (player, bracket).
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ratings (
        discord_id INTEGER NOT NULL,
        bracket TEXT NOT NULL,
        points INTEGER NOT NULL DEFAULT 1000,
        PRIMARY KEY (discord_id, bracket)
    )
    """)

    # Win/loss record + current streak per (player, exact format).
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS format_stats (
        discord_id INTEGER NOT NULL,
        mode TEXT NOT NULL,
        games INTEGER NOT NULL DEFAULT 0,
        wins INTEGER NOT NULL DEFAULT 0,
        losses INTEGER NOT NULL DEFAULT 0,
        streak INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (discord_id, mode)
    )
    """)

    # Completed matches, for the web match-log. Rosters are stored as JSON lists of
    # {name, before, after, delta} so history stays readable even if players rename.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        mode TEXT NOT NULL,
        bracket TEXT NOT NULL,
        game_map TEXT,
        winner TEXT NOT NULL,
        team1 TEXT NOT NULL,
        team2 TEXT NOT NULL
    )
    """)

    # Migration: add the streak column if an older format_stats table predates it.
    existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(format_stats)")]
    if "streak" not in existing_columns:
        cursor.execute("ALTER TABLE format_stats ADD COLUMN streak INTEGER NOT NULL DEFAULT 0")

    # Old flat stats table from the previous schema is no longer used.
    cursor.execute("DROP TABLE IF EXISTS stats")

    db.commit()


_init_schema()


def commit():
    """Persist pending changes to disk."""
    db.commit()


def get_bracket(mode):
    """Map a game mode to its rating bracket by team size."""
    team_size = GAME_MODES[mode] // 2
    if team_size <= 3:
        return "small"
    if team_size <= 6:
        return "medium"
    return "large"


# --- Players ---

def is_registered(user_id) -> bool:
    cursor.execute("SELECT 1 FROM players WHERE discord_id=?", (user_id,))
    return cursor.fetchone() is not None


def register_player(user_id, name):
    """Create a player and seed a starting rating in every bracket."""
    cursor.execute(
        "INSERT INTO players (discord_id, username) VALUES (?, ?)",
        (user_id, name),
    )
    for bracket in BRACKETS:
        cursor.execute(
            "INSERT OR IGNORE INTO ratings (discord_id, bracket, points) VALUES (?, ?, ?)",
            (user_id, bracket, STARTING_POINTS),
        )
    db.commit()


def rename_player(user_id, name):
    cursor.execute(
        "UPDATE players SET username=? WHERE discord_id=?",
        (name, user_id),
    )
    db.commit()


def get_player_name(user):
    """Registered name for a discord user, falling back to their display name."""
    cursor.execute("SELECT username FROM players WHERE discord_id=?", (user.id,))
    result = cursor.fetchone()
    if result:
        return result[0]
    return user.display_name


# --- Ratings ---

def get_points(user_id, bracket) -> int:
    """Return a player's rating for a bracket, creating it at STARTING_POINTS if missing."""
    cursor.execute(
        "SELECT points FROM ratings WHERE discord_id=? AND bracket=?",
        (user_id, bracket),
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute(
        "INSERT OR IGNORE INTO ratings (discord_id, bracket, points) VALUES (?, ?, ?)",
        (user_id, bracket, STARTING_POINTS),
    )
    return STARTING_POINTS


def add_points(user_id, bracket, delta) -> int:
    """Apply a point change (clamped so a rating never drops below 0) and return the new total."""
    new_total = max(0, get_points(user_id, bracket) + delta)
    cursor.execute(
        "UPDATE ratings SET points=? WHERE discord_id=? AND bracket=?",
        (new_total, user_id, bracket),
    )
    return new_total


def get_leaderboard(bracket, limit=10):
    """Return [(username, discord_id, points), ...] for a bracket, highest first."""
    cursor.execute(
        """
        SELECT p.username, r.discord_id, r.points
        FROM ratings r
        JOIN players p ON p.discord_id = r.discord_id
        WHERE r.bracket = ?
        ORDER BY r.points DESC
        LIMIT ?
        """,
        (bracket, limit),
    )
    return cursor.fetchall()


# --- Records / streaks ---

def record_game(user_id, mode, outcome):
    """Update a player's per-format record. outcome is 'win', 'loss', or 'draw'.

    A win extends the streak, a loss resets it, a draw leaves it unchanged.
    """
    cursor.execute(
        "INSERT OR IGNORE INTO format_stats (discord_id, mode) VALUES (?, ?)",
        (user_id, mode),
    )
    if outcome == "win":
        cursor.execute(
            "UPDATE format_stats SET games=games+1, wins=wins+1, streak=streak+1 "
            "WHERE discord_id=? AND mode=?",
            (user_id, mode),
        )
    elif outcome == "loss":
        cursor.execute(
            "UPDATE format_stats SET games=games+1, losses=losses+1, streak=0 "
            "WHERE discord_id=? AND mode=?",
            (user_id, mode),
        )
    else:  # draw
        cursor.execute(
            "UPDATE format_stats SET games=games+1 WHERE discord_id=? AND mode=?",
            (user_id, mode),
        )


def record_match(mode, bracket, game_map, winner, team1, team2):
    """Persist a completed match for the web match-log.

    team1/team2 are lists of {name, before, after, delta} dicts (team1 = red,
    team2 = blue). Commit is left to the caller.
    """
    cursor.execute(
        "INSERT INTO matches (mode, bracket, game_map, winner, team1, team2) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (mode, bracket, game_map, winner, json.dumps(team1), json.dumps(team2)),
    )
    return cursor.lastrowid


def get_streak(user_id, mode) -> int:
    cursor.execute(
        "SELECT streak FROM format_stats WHERE discord_id=? AND mode=?",
        (user_id, mode),
    )
    row = cursor.fetchone()
    return row[0] if row else 0


def get_format_stats(user_id):
    """Return [(mode, games, wins, losses, streak), ...] for a player."""
    cursor.execute(
        "SELECT mode, games, wins, losses, streak FROM format_stats WHERE discord_id=?",
        (user_id,),
    )
    return cursor.fetchall()


def get_bracket_record(user_id, bracket):
    """Aggregate a player's wins/losses across every format in a bracket."""
    wins = losses = 0
    for mode, _games, w, l, _streak in get_format_stats(user_id):
        if mode in GAME_MODES and get_bracket(mode) == bracket:
            wins += w
            losses += l
    return wins, losses


# --- Points math ---

def win_rate(wins, losses):
    """Win percentage over decided games (draws excluded)."""
    total = wins + losses
    return round(wins / total * 100, 1) if total else 0.0


def streak_bonus(streak) -> float:
    """Fractional point-gain bonus for a given win streak (0.0 when below threshold)."""
    if streak < STREAK_THRESHOLD:
        return 0.0
    return min(STREAK_BONUS_MAX, STREAK_BONUS_PER_WIN * (streak - STREAK_THRESHOLD + 1))


def calculate_points_change(winner_avg, loser_avg):
    """Return (gain, loss) for a match given each team's average rating."""
    winner_expected = 1 / (1 + 10 ** ((loser_avg - winner_avg) / 400))
    swing = 2 * K_FACTOR * (1 - winner_expected)

    gain = max(MIN_GAIN, round(swing))
    loss = max(MIN_LOSS, round(swing * LOSS_RATIO))
    return gain, loss

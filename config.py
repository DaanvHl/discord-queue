"""Central configuration: secrets, IDs, game data, and tuning constants."""
import os

from dotenv import load_dotenv

load_dotenv()

def _require(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Add it to your .env file.")
    return value


# Secrets and Discord IDs — all loaded from .env
TOKEN = _require("DISCORD_TOKEN")
GUILD_ID = int(_require("GUILD_ID"))
QUEUE_CHANNEL_ID = int(_require("QUEUE_CHANNEL_ID"))

# Database file location. Defaults to a local file. When hosting, point this at a
# persistent volume (e.g. DB_PATH=/data/players.db) so data survives redeploys.
DB_PATH = os.getenv("DB_PATH", "players.db")

# --- Points / rating configuration ---
STARTING_POINTS = 1000
K_FACTOR = 50        # Points a winner gains in a perfectly even match.
LOSS_RATIO = 0.9     # Losers drop a bit less than winners gain -> points inflate over time.
MIN_GAIN = 10        # A win always pays out at least this much.
MIN_LOSS = 5         # A loss always costs at least this much.

# Win-streak bonus (same format). At STREAK_THRESHOLD consecutive wins a bonus
# starts, growing STREAK_BONUS_PER_WIN each further win, capped at STREAK_BONUS_MAX.
STREAK_THRESHOLD = 3
STREAK_BONUS_PER_WIN = 0.05
STREAK_BONUS_MAX = 0.5

# Queue sizes (total players per match).
GAME_MODES = {
    "2v2": 4,
    "3v3": 6,
    "4v4": 8,
    "5v5": 10,
    "6v6": 12,
    "8v8": 16,
    "10v10": 20,
}

# Rating brackets grouped by team size. Each player has a separate rating per bracket.
BRACKETS = ("small", "medium", "large")
BRACKET_LABELS = {
    "small": "Small (2v2–3v3)",
    "medium": "Medium (4v4–6v6)",
    "large": "Large (8v8–10v10)",
}

MAPS = {
    "2v2": [
        "Boombox", "Cross", "Duality", "Garder", "Sandal",
        "Sandbox", "Station", "Valley", "Zone", "Magadan",
    ],
    "3v3": [
        "Boombox", "Cross", "Duality", "Garder", "Sandal",
        "Sandbox", "Station", "Valley", "Zone", "Magadan",
    ],
    "4v4": [
        "Sandbox", "Sandal", "Pass", "Farm", "Boombox", "Magadan",
    ],
    "5v5": [
        "Cross", "Fort Knox", "Garder", "Sandal", "Molotov",
        "Station", "Valley", "Zone", "Pass",
    ],
    "6v6": [
        "Sandal", "Garder", "Zone", "Fort Knox", "Station", "Cross",
    ],
    "8v8": [
        "Noise", "Station", "Molotov", "Red Alert",
        "Future", "Polygon", "Iran",
    ],
    "10v10": [
        "Silence", "Red Alert", "Future", "Iran",
        "Bobruisk", "Molotov", "Industrial Zone",
    ],
}

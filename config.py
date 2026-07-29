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


def _queue_channel_ids():
    """Channel IDs where queue commands are allowed.

    Accepts QUEUE_CHANNEL_ID (single) and/or QUEUE_CHANNEL_IDS (comma-separated),
    merged into one de-duplicated list.
    """
    raw = []
    single = os.getenv("QUEUE_CHANNEL_ID")
    if single:
        raw.append(single)
    raw.extend(os.getenv("QUEUE_CHANNEL_IDS", "").split(","))

    ids, seen = [], set()
    for part in raw:
        part = part.strip()
        if part and int(part) not in seen:
            seen.add(int(part))
            ids.append(int(part))
    if not ids:
        raise RuntimeError(
            "No queue channels set. Add QUEUE_CHANNEL_ID or QUEUE_CHANNEL_IDS to your .env file."
        )
    return ids


# Every channel where queue commands may be used; the first is the "primary"
# channel used for bot-initiated announcements (e.g. inactivity auto-close).
QUEUE_CHANNEL_IDS = _queue_channel_ids()
QUEUE_CHANNEL_ID = QUEUE_CHANNEL_IDS[0]

# Optional: a role that may use admin commands (alongside server administrators).
_organizer = os.getenv("ORGANIZER_ROLE_ID")
ORGANIZER_ROLE_ID = int(_organizer) if _organizer else None

# Database file location. Defaults to a local file. When hosting, point this at a
# persistent volume (e.g. DB_PATH=/data/players.db) so data survives redeploys.
DB_PATH = os.getenv("DB_PATH", "players.db")

# A non-full queue is auto-closed if nobody joins it for this long (seconds).
QUEUE_INACTIVITY_SECONDS = 15 * 60

# Optional: channel where confirmed match results are logged. Unset = no logging.
_results_channel = os.getenv("RESULTS_CHANNEL_ID")
RESULTS_CHANNEL_ID = int(_results_channel) if _results_channel else None

# --- Points / rating configuration ---
STARTING_POINTS = 1000
K_FACTOR = 50        # Points a winner gains in a perfectly even match.
LOSS_RATIO = 0.6     # Losers drop less than winners gain (even match: +50 / -30) -> points inflate over time.
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
    "7v7": 14,
    "8v8": 16,
    "9v9": 18,
    "10v10": 20,
}

# Rating brackets grouped by team size. Each player has a separate rating per bracket.
BRACKETS = ("small", "medium", "large")
BRACKET_LABELS = {
    "small": "Small (2v2–3v3)",
    "medium": "Medium (4v4–6v6)",
    "large": "Large (7v7–10v10)",
}

MAPS = {
    "2v2": [
        "Boombox", "Cross", "Duality", "Garder", "Sandal",
        "Sandbox", "Station", "Valley", "Zone", "Magadan",
        "Short Bridge",
    ],
    "3v3": [
        "Boombox", "Cross", "Duality", "Garder", "Sandal",
        "Sandbox", "Station", "Valley", "Zone", "Magadan",
        "Short Bridge",
    ],
    "4v4": [
        "Sandbox", "Sandal", "Pass", "Farm", "Boombox", "Magadan",
        "Valley", "Short Bridge",
    ],
    "5v5": [
        "Cross", "Fort Knox", "Garder", "Sandal",
        "Station", "Valley", "Zone", "Pass",
    ],
    "6v6": [
        "Sandal", "Garder", "Zone", "Fort Knox", "Iran",
        "Cross", "Forest", "Red Alert", "Courage",
    ],
    "7v7": [
        "Station", "Red Alert", "Fort Knox",
        "Future", "Noise", "Iran", "Siege", "Forest", "Courage",
    ],
    "8v8": [
        "Noise", "Station", "Molotov", "Red Alert",
        "Future", "Polygon", "Iran", "Courage",
    ],
    "9v9": [
        "Silence", "Red Alert", "Future", "Iran",
        "Molotov", "Industrial Zone",
    ],
    "10v10": [
        "Silence", "Red Alert", "Future", "Iran",
        "Bobruisk", "Molotov", "Industrial Zone",
    ],
}

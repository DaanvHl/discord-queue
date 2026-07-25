"""In-memory runtime state shared across features.

None of this is persisted — it only reflects matches currently in progress.
Persistent data (players, ratings, records) lives in the database (see db.py).
"""
from config import GAME_MODES

# Players waiting in each queue: {mode: [discord.User, ...]}
queues = {mode: [] for mode in GAME_MODES}

# Full queues waiting for captains to be chosen, keyed by mode.
# {mode: {"mode": str, "players": [users], "captains": [users]}}
# A lobby exists only during the captain-selection window (after the queue fills,
# before the draft starts). This is the only time /captain is allowed.
lobbies = {}

# Captain drafts in progress, keyed by mode.
drafts = {}

# Matches waiting on a result, keyed by channel id.
active_matches = {}

# Reported-but-unconfirmed results, keyed by channel id.
pending_results = {}

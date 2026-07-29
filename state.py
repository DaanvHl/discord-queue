"""In-memory runtime state shared across features.

None of this is persisted — it only reflects matches currently in progress.
Persistent data (players, ratings, records) lives in the database (see db.py).

Everything is keyed by (channel_id, mode) so each channel runs its own
independent queues and matches.
"""

# Players waiting in each queue: {(channel_id, mode): [discord.User, ...]}
queues = {}

# Monotonic timestamp of the last join per queue, for the inactivity auto-close.
# {(channel_id, mode): float}
queue_last_activity = {}

# Full queues waiting for captains to be chosen, keyed by (channel_id, mode).
lobbies = {}

# Captain drafts in progress, keyed by (channel_id, mode).
drafts = {}

# Matches waiting on a result, keyed by (channel_id, mode).
active_matches = {}

# Reported-but-unconfirmed results, keyed by (channel_id, mode).
pending_results = {}

"""/help command with per-topic explanations."""
import discord
from discord import app_commands

from config import STARTING_POINTS

# Topic value -> (emoji title, list of (field name, field value)).
TOPICS = {
    "overview": (
        "📖 Bot Help — Overview",
        "A pickup-game queue bot with captain drafts, map bans, an Elo-style points "
        "system, and automatic rank roles.\n\n"
        "Use `/help <topic>` for details on any area:",
        [
            ("🎮 queue", "Joining/leaving queues and how matches start"),
            ("👑 captains", "Claiming captain when a queue fills"),
            ("📋 draft", "How captains pick their teams"),
            ("🗺️ maps", "The map-ban phase"),
            ("🏁 results", "Reporting and confirming match results"),
            ("🏅 ranks", "Points, sections, streaks and rank roles"),
            ("🪪 profile", "Registering, stats and the leaderboard"),
        ],
    ),
    "queue": (
        "🎮 Queues",
        "Queues fill up, then turn into a match. You can only be in **one queue at a time**.",
        [
            ("/join `<mode>`", "Join a queue (2v2 … 10v10). Nothing happens until it fills."),
            ("/leave", "Leave your current queue — no mode needed, it finds you automatically."),
            ("/start", "Once the queue is full, any player in it starts the match (captains → map ban → teams → draft). After `/start`, no one can leave."),
            ("/open", "Undo `/start` while captains **aren't locked in yet** — reopens the queue so players can `/leave` or `/expand` again. Any player in the match can use it."),
            ("/close", "Queue won't fill? Close it into the format matching your current **even** player count (e.g. 8 players → 4v4) and start."),
            ("/expand", "Queue full? Expand to the next format up (+2 players) — e.g. 6v6 → 7v7 opens 2 slots."),
            ("/queues", "Show every queue, who's in it, and any match forming."),
            ("/clear `[mode]`", "**(Admin/Organizer)** Clear one queue/match in this channel (pick a mode — works at any stage: waiting, captains, draft, or awaiting result), or everything if no mode given."),
            ("/remove `<player>`", "**(Admin/Organizer)** Remove a specific player from their queue (before it's full)."),
            ("When it fills", "It announces the full roster and waits — you can still `/leave` until any player runs `/start`."),
            ("Auto-close", "If nobody joins a queue for **15 minutes**, it closes and everyone in it is removed. Just `/join` again."),
        ],
    ),
    "captains": (
        "👑 Captains",
        "After the queue is full and someone runs `/start`, a captain panel with buttons appears.",
        [
            ("🙋 Claim Captain", "Volunteer yourself (max 2). Only players in the match can."),
            ("🚪 Step Down", "Withdraw as captain."),
            ("🎲 Roll Captains", "Pick two random captains from the queue — rerollable."),
            ("🔒 Lock In", "Once two captains are set, lock them in to start the map ban."),
            ("Then", "Map ban → the **first** captain picks a side (🔴/🔵) → the **second** "
                     "captain gets first pick in the draft."),
        ],
    ),
    "draft": (
        "📋 Captain Draft",
        "Captains take turns picking players for their teams.",
        [
            ("/pick `<player name>`", "Pick an available player onto your team (use their registered name)."),
            ("Turn order", "The captain with first pick starts (see `/help captains`), then it alternates."),
            ("Snake endgame", "When 3 players remain, the **second-pick** captain picks 2, and the **first-pick** captain is auto-given the last one — balances the first-pick advantage."),
            ("Next step", "The map was already chosen earlier, so once teams are complete the match is ready to play."),
        ],
    ),
    "maps": (
        "🗺️ Map Ban",
        "Each match narrows 3 random maps down to 1 — right after captains are chosen, "
        "before teams are picked.",
        [
            ("How it works", "The bot picks **3 random maps** for the mode. The **first** captain "
                             "bans one, then the **second**; the **remaining map is played**."),
            ("Buttons", "Bans are done by clicking the map buttons — only the captain whose turn it "
                        "is can ban."),
            ("Timeout", "Each captain has **60 seconds**; if they don't act, a random map is banned "
                        "for them."),
        ],
    ),
    "results": (
        "🏁 Match Results",
        "A result only counts once **both captains agree**.",
        [
            ("/result `<winner>`", "A captain reports the outcome: 🔴 Red, 🔵 Blue, or 🤝 Draw."),
            ("Confirm / Cancel", "The **opposing** captain clicks **✅ Confirm** or **✖️ Cancel** on "
                                 "the result message (or types `/confirm`). Only on confirm are points, "
                                 "records and ranks updated. Cancel lets it be re-reported."),
            ("/force-result `<format> <winner>`", "**(Admin/Organizer)** Set a result for the active match "
                                                  "of a format in this channel without being a captain. Shows a "
                                                  "private ✅ Confirm / ✖️ Cancel prompt; overrides any pending result."),
            ("Draws", "A draw counts as a game played but changes no points."),
        ],
    ),
    "ranks": (
        "🏅 Points & Ranks",
        f"Everyone starts at **{STARTING_POINTS}** points. Ratings are tracked **per section**, so "
        "you can be a different rank in each:",
        [
            ("Sections", "🟢 **Small** (2v2–3v3) · 🟡 **Medium** (4v4–6v6) · 🔴 **Large** (7v7–10v10)"),
            ("Winning / losing", "Team-average Elo. Even match ≈ **+50** to win, **−45** to lose. Beating "
                                 "a **stronger** team earns more; a **weaker** team earns less (points "
                                 "grow slowly over time and never drop below 0)."),
            ("🔥 Win streaks", "3+ wins in a row in the **same format** boost your gains — up to **+50%** "
                              "the longer the streak."),
            ("Rank ladder", "**Iron** (<500) → **Bronze** (500) → **Silver** (750, start) → "
                            "**Gold** (1250) → **Platinum** (1500) → **Diamond** (1750) → "
                            "**Emerald** (2000) → **Ruby** (2250). Higher ranks step every 250."),
            ("Rank roles", "You get a role per section plus one **colored** role for your **highest** "
                          "rank — that color shows on your name."),
        ],
    ),
    "profile": (
        "🪪 Profile & Stats",
        "Register once, then track your progress.",
        [
            ("/register `<name>`", f"Sign up with your in-game name. Starts you at {STARTING_POINTS} "
                                   "points in every section and assigns your rank roles."),
            ("/rename `<name>`", "Change your registered name."),
            ("/profile", "Show your registered name."),
            ("/stats", "Your points, rank and W/L for each section and format."),
            ("/leaderboard `<section>`", "Top 10 players in a section, with W/L."),
            ("/punish `<player> <bracket> <amount>`", "**(Admin/Organizer)** Remove points from a player in a bracket (may downgrade their rank)."),
            ("/give `<player> <bracket> <amount>`", "**(Admin/Organizer)** Give points to a player in a bracket (may upgrade their rank)."),
        ],
    ),
}

TOPIC_CHOICES = [
    app_commands.Choice(name="Overview", value="overview"),
    app_commands.Choice(name="Queue", value="queue"),
    app_commands.Choice(name="Captains", value="captains"),
    app_commands.Choice(name="Draft", value="draft"),
    app_commands.Choice(name="Maps", value="maps"),
    app_commands.Choice(name="Results", value="results"),
    app_commands.Choice(name="Ranks", value="ranks"),
    app_commands.Choice(name="Profile", value="profile"),
]


def _build_embed(topic):
    title, description, fields = TOPICS[topic]
    embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)
    if topic == "overview":
        embed.set_footer(text="Example: /help ranks")
    return embed


def setup(bot):
    @bot.tree.command(name="help", description="Explains how the bot works")
    @app_commands.choices(topic=TOPIC_CHOICES)
    async def help_command(
        interaction: discord.Interaction,
        topic: app_commands.Choice[str] = None,
    ):
        key = topic.value if topic else "overview"
        await interaction.response.send_message(embed=_build_embed(key), ephemeral=True)

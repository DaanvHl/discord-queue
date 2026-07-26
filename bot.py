"""Entry point: create the bot, load feature modules, and run.

Logic lives in focused modules:
  config.py           - constants and tuning
  state.py            - in-memory runtime state
  db.py               - database access + points/streak math
  checks.py           - shared command guards
  features/           - one module per feature, each exposing setup(bot)
"""
import discord
from discord.ext import commands

from config import GUILD_ID, TOKEN
from features import draft, help, matches, queue, registration, stats
from ranks import ensure_rank_roles

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Register every feature's commands.
for feature in (registration, queue, draft, matches, stats, help):
    feature.setup(bot)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)

    print(f"Synced {len(synced)} commands")

    real_guild = bot.get_guild(GUILD_ID)
    if real_guild:
        await ensure_rank_roles(real_guild)
        print("Rank roles ensured")


bot.run(TOKEN)

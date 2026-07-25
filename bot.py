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
from features import draft, matches, queue, registration, stats

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Register every feature's commands.
for feature in (registration, queue, draft, matches, stats):
    feature.setup(bot)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)

    print(f"Synced {len(synced)} commands")


bot.run(TOKEN)

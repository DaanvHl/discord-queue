"""Reusable interaction checks/guards."""
import discord

from config import QUEUE_CHANNEL_ID


async def ensure_queue_channel(interaction: discord.Interaction) -> bool:
    """Return True if the command is used in the queue channel, else reply and return False."""
    if interaction.channel.id == QUEUE_CHANNEL_ID:
        return True

    await interaction.response.send_message(
        "❌ Use this command in the queue channel.",
        ephemeral=True,
    )
    return False

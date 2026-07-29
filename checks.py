"""Reusable interaction checks/guards."""
import discord

from config import ORGANIZER_ROLE_ID, QUEUE_CHANNEL_IDS


async def ensure_queue_channel(interaction: discord.Interaction) -> bool:
    """Return True if the command is used in a queue channel, else reply and return False."""
    if interaction.channel.id in QUEUE_CHANNEL_IDS:
        return True

    await interaction.response.send_message(
        "❌ Use this command in a queue channel.",
        ephemeral=True,
    )
    return False


async def ensure_organizer(interaction: discord.Interaction) -> bool:
    """Return True if the user is a server admin or has the organizer role."""
    perms = getattr(interaction.user, "guild_permissions", None)
    if perms is not None and perms.administrator:
        return True

    if ORGANIZER_ROLE_ID is not None:
        role_ids = {r.id for r in getattr(interaction.user, "roles", [])}
        if ORGANIZER_ROLE_ID in role_ids:
            return True

    await interaction.response.send_message(
        "❌ You need administrator permission or the organizer role to use this.",
        ephemeral=True,
    )
    return False

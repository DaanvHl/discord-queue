"""Player identity commands: /profile, /register, /rename."""
import discord

from checks import ensure_queue_channel
from config import STARTING_POINTS
from db import get_player_name, is_registered, register_player, rename_player
from ranks import update_member_ranks


def setup(bot):
    @bot.tree.command(name="profile", description="View your registered name")
    async def profile(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        name = get_player_name(interaction.user)
        await interaction.response.send_message(
            f"🎮 Your registered name is **{name}**"
        )

    @bot.tree.command(name="register", description="Register your in-game name")
    async def register(interaction: discord.Interaction, name: str):
        if not await ensure_queue_channel(interaction):
            return

        if is_registered(interaction.user.id):
            await interaction.response.send_message(
                "❌ You are already registered. Use `/rename` to change your name.",
                ephemeral=True,
            )
            return

        register_player(interaction.user.id, name)
        await interaction.response.send_message(
            f"✅ Successfully registered as **{name}**!\n"
            f"You start with **{STARTING_POINTS}** points in every bracket."
        )
        await update_member_ranks(interaction.guild, interaction.user)

    @bot.tree.command(name="rename", description="Change your registered name")
    async def rename(interaction: discord.Interaction, name: str):
        if not is_registered(interaction.user.id):
            await interaction.response.send_message(
                "❌ You are not registered. Use `/register` first.",
                ephemeral=True,
            )
            return

        rename_player(interaction.user.id, name)
        await interaction.response.send_message(
            f"✅ Your name has been changed to **{name}**!"
        )

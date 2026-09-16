"""Player identity commands: /profile, /register, /rename, /unregister, /sync-roles."""
import discord

from checks import ensure_organizer, ensure_queue_channel
from config import STARTING_POINTS
from db import (
    get_player_name,
    get_registered_ids,
    is_registered,
    register_player,
    rename_player,
    unregister_player,
)
from features.stats import build_profile_embed
from ranks import remove_rank_roles, update_member_ranks


class _UnregisterView(discord.ui.View):
    """Confirm / Cancel on an ephemeral unregister prompt (only the user sees it)."""

    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.user_id = user_id

    @discord.ui.button(label="Confirm", emoji="✅", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        if not is_registered(interaction.user.id):
            await interaction.response.edit_message(
                content="❌ You're not registered.", view=None
            )
            return
        unregister_player(interaction.user.id)
        await remove_rank_roles(interaction.guild, interaction.user)
        await interaction.response.edit_message(
            content="🗑️ You've been unregistered. All your progress has been removed.",
            view=None,
        )

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content="✖️ Cancelled — you're still registered.", view=None
        )


def setup(bot):
    @bot.tree.command(name="profile", description="View your profile card")
    async def profile(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        if not is_registered(interaction.user.id):
            await interaction.response.send_message(
                "❌ You are not registered. Use `/register` first.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(embed=build_profile_embed(interaction.user))

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

    @bot.tree.command(name="unregister", description="Delete your registration and all progress")
    async def unregister(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        if not is_registered(interaction.user.id):
            await interaction.response.send_message(
                "❌ You're not registered.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "⚠️ **Are you sure you want to unregister?**\n"
            "By doing this, all progress will be lost.",
            view=_UnregisterView(interaction.user.id),
            ephemeral=True,
        )

    @bot.tree.command(
        name="sync-roles",
        description="(Admin/Organizer) Re-sync rank roles for every registered player",
    )
    async def sync_roles(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return
        if not await ensure_organizer(interaction):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        synced = not_here = 0
        for uid in get_registered_ids():
            member = interaction.guild.get_member(uid)
            if member is None:
                try:
                    member = await interaction.guild.fetch_member(uid)
                except discord.NotFound:
                    not_here += 1
                    continue
                except discord.HTTPException:
                    continue
            await update_member_ranks(interaction.guild, member)
            synced += 1

        msg = f"✅ Synced roles for {synced} player(s)."
        if not_here:
            msg += f" ({not_here} registered player(s) not in this server.)"
        await interaction.followup.send(msg, ephemeral=True)

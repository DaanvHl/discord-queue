"""Optional /setups command: launches a Tanki pick & ban on the external setups service.

Only registered when SETUPS_API_URL + SETUPS_SECRET are configured. The requesting
captain gets their private draft link immediately; the opposing captain gets theirs
from a button on a public message. When the draft finishes, the setups service calls
back into web.py, which posts the loadouts here.
"""
import aiohttp
import discord

from checks import ensure_queue_channel
from config import SETUPS_API_URL, SETUPS_ENABLED, SETUPS_SECRET
from db import get_player_name
from state import active_matches
from features.matches import _match_key_for_captain


class _SetupLinkView(discord.ui.View):
    """A public message with a button that hands each captain their own private link."""

    def __init__(self, urls_by_id):
        super().__init__(timeout=None)
        self.urls_by_id = urls_by_id  # {discord_id: private_url}

    @discord.ui.button(label="Open my draft", emoji="🎮", style=discord.ButtonStyle.primary)
    async def open_draft(self, interaction: discord.Interaction, button: discord.ui.Button):
        url = self.urls_by_id.get(interaction.user.id)
        if url is None:
            await interaction.response.send_message(
                "❌ This setup draft isn't yours.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"🎮 **Your setup draft link (keep it private):**\n{url}", ephemeral=True
        )


async def _create_draft(host, guest, channel_id, mode):
    """Ask the setups service to create a draft; return (data, error)."""
    payload = {
        "hostId": str(host.id),
        "guestId": str(guest.id),
        "hostName": get_player_name(host),
        "guestName": get_player_name(guest),
        "channelId": str(channel_id),
        "meta": {"channelId": str(channel_id), "mode": mode},
    }
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{SETUPS_API_URL}/api/drafts",
                json=payload,
                headers={"x-setups-secret": SETUPS_SECRET},
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    return None, f"the setups service returned HTTP {resp.status} ({body[:120]})"
                return await resp.json(), None
    except aiohttp.ClientError as exc:
        return None, f"couldn't reach the setups service ({exc})"


def setup(bot):
    if not SETUPS_ENABLED:
        return  # feature off — command not registered, bot behaves exactly as before

    @bot.tree.command(
        name="setups",
        description="Start the Tanki pick & ban with your opposing captain",
    )
    async def setups(interaction: discord.Interaction):
        if not await ensure_queue_channel(interaction):
            return

        key = _match_key_for_captain(interaction.user.id)
        if key is None:
            await interaction.response.send_message(
                "❌ You're not a captain of an active match.", ephemeral=True
            )
            return

        match = active_matches[key]
        cap1, cap2 = match["captain1"], match["captain2"]
        # The captain who runs the command is the Host; the other is the Guest.
        host, guest = (cap1, cap2) if interaction.user.id == cap1.id else (cap2, cap1)

        await interaction.response.defer(ephemeral=True, thinking=True)

        data, error = await _create_draft(host, guest, interaction.channel.id, key[1])
        if error is not None:
            await interaction.followup.send(f"❌ Couldn't start the setup draft — {error}.", ephemeral=True)
            return

        host_url, guest_url = data["hostUrl"], data["guestUrl"]

        # Give the requesting captain their link privately (instant redirect).
        await interaction.followup.send(
            f"🎮 **Your setup draft link (keep it private):**\n{host_url}", ephemeral=True
        )

        # Public message: the opposing captain clicks the button for their own link.
        urls_by_id = {host.id: host_url, guest.id: guest_url}
        await interaction.channel.send(
            f"🎮 **Setup pick & ban started!**\n"
            f"<@{host.id}> and <@{guest.id}>, open your **private** draft with the button below.\n"
            f"When it's finished, the setups will be posted here.",
            view=_SetupLinkView(urls_by_id),
            allowed_mentions=discord.AllowedMentions(users=[host, guest]),
        )

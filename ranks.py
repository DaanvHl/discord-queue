"""Rank roles derived from points.

Two kinds of roles, none hoisted:

  * Section roles (24) - "Small . Platinum", "Medium . Gold", ... one per section
    per rank. These are COLORLESS; they just record a player's rank in each
    section ("different roles for different queue sections").

  * Tier roles (8) - "Iron" ... "Ruby". These are COLORED. A player holds exactly
    one, matching their HIGHEST rank across all three sections, so their name
    color always reflects their best rank. Using a single colored role means the
    color works regardless of role position (no hierarchy ordering required).

The bot creates and maintains all of these automatically.
"""
import discord

from config import BRACKETS
from db import get_points

# Ranks from lowest to highest. Each entry is (minimum_points, name).
# Bands below the 1000 starting point are wider, so new players begin at Silver.
RANKS = [
    (0, "Iron"),
    (500, "Bronze"),
    (750, "Silver"),      # starting rank (1000 points lands here)
    (1250, "Gold"),
    (1500, "Platinum"),
    (1750, "Diamond"),
    (2000, "Emerald"),
    (2250, "Ruby"),
]

RANK_COLORS = {
    "Iron": 0x9E9E9E,
    "Bronze": 0xCD7F32,
    "Silver": 0xC0C0C0,
    "Gold": 0xFFD700,
    "Platinum": 0x4FD1C5,
    "Diamond": 0x4AA8FF,
    "Emerald": 0x2ECC71,
    "Ruby": 0xE0115F,
}

SECTION_NAMES = {
    "small": "Small",
    "medium": "Medium",
    "large": "Large",
}

_RANK_NAMES = [name for _minimum, name in RANKS]


def rank_for_points(points) -> str:
    """Return the rank name for a point total."""
    name = RANKS[0][1]
    for minimum, rank in RANKS:
        if points >= minimum:
            name = rank
        else:
            break
    return name


def section_role_name(section, rank) -> str:
    return f"{SECTION_NAMES[section]} · {rank}"


def tier_role_name(rank) -> str:
    return rank


def all_role_names():
    """Every rank role name the bot manages (24 section + 8 tier)."""
    section = [section_role_name(s, r) for s in BRACKETS for r in _RANK_NAMES]
    return section + list(_RANK_NAMES)


async def _ensure_role(guild, existing, name, colour, reason):
    """Create the role if missing, else fix its colour/hoist. Returns the role or None."""
    role = existing.get(name)
    if role is None:
        try:
            return await guild.create_role(
                name=name,
                colour=colour,
                hoist=False,
                mentionable=False,
                reason=reason,
            )
        except discord.Forbidden:
            print(
                f"[ranks] Missing 'Manage Roles' permission - cannot create '{name}'. "
                "Grant the bot Manage Roles and restart."
            )
            return None

    # Keep existing roles consistent (colour + not hoisted).
    if role.colour != colour or role.hoist:
        try:
            await role.edit(colour=colour, hoist=False, reason=reason)
        except (discord.Forbidden, discord.HTTPException):
            pass
    return role


async def ensure_rank_roles(guild):
    """Create/normalise all rank roles. Returns True on success, None if blocked."""
    existing = {r.name: r for r in guild.roles}
    colourless = discord.Colour.default()

    # Section roles: colourless, one per (section, rank).
    for section in BRACKETS:
        for rank in _RANK_NAMES:
            role = await _ensure_role(
                guild, existing, section_role_name(section, rank),
                colourless, "Section rank role",
            )
            if role is None:
                return None

    # Tier roles: coloured, one per rank; this is what colours the member's name.
    for rank in _RANK_NAMES:
        role = await _ensure_role(
            guild, existing, tier_role_name(rank),
            discord.Colour(RANK_COLORS[rank]), "Coloured rank tier role",
        )
        if role is None:
            return None

    return True


async def update_member_ranks(guild, member):
    """Sync a member's section roles and their single coloured tier role."""
    guild_roles = {r.name: r for r in guild.roles}
    member_role_names = {r.name for r in member.roles}

    to_add, to_remove = [], []
    best_points = 0

    # Per-section (colourless) roles.
    for section in BRACKETS:
        points = get_points(member.id, section)
        best_points = max(best_points, points)

        section_names = {section_role_name(section, r) for r in _RANK_NAMES}
        desired = section_role_name(section, rank_for_points(points))

        for role in member.roles:
            if role.name in section_names and role.name != desired:
                to_remove.append(role)
        if desired not in member_role_names and desired in guild_roles:
            to_add.append(guild_roles[desired])

    # Single coloured tier role = highest rank across all sections.
    tier_names = set(_RANK_NAMES)
    desired_tier = tier_role_name(rank_for_points(best_points))

    for role in member.roles:
        if role.name in tier_names and role.name != desired_tier:
            to_remove.append(role)
    if desired_tier not in member_role_names and desired_tier in guild_roles:
        to_add.append(guild_roles[desired_tier])

    try:
        if to_remove:
            await member.remove_roles(*to_remove, reason="Rank sync")
        if to_add:
            await member.add_roles(*to_add, reason="Rank sync")
    except discord.Forbidden:
        print(
            f"[ranks] Cannot update roles for {member} - need 'Manage Roles' and the bot's "
            "role above the rank roles."
        )
    except discord.HTTPException as exc:
        print(f"[ranks] Failed to update ranks for {member}: {exc}")

"""Staff HQ for the Tropical Tycoon staff server.

Builds Guide / Mod / Admin rooms, a private channel with the owner for every
staff member, and the staff handbook. The handbook follows the public rules in
this bot and the in-game rank ladder (guide < mod < admin < owner): mute limits,
tempban cap, and what admin is not allowed to do.

Only runs on STAFF_GUILD_ID. Player-facing setup (/setupdiscord) is unchanged.
"""

from __future__ import annotations

import os
import re

import discord
from discord import app_commands

# The staff server. Override with STAFF_GUILD_ID if it ever moves.
STAFF_GUILD_ID = int(os.getenv("STAFF_GUILD_ID", "1567210660516073504"))

OWNER_ROLE = "Owner"
ADMIN_ROLE = "Admin"
MOD_ROLE = "Mod"
GUIDE_ROLE = "Guide"
# Lowest → highest. A higher rank can see every room below it.
RANK_ORDER = (GUIDE_ROLE, MOD_ROLE, ADMIN_ROLE, OWNER_ROLE)
# Roles that earn a private channel with the owner. The guild owner is skipped.
TEAM_ROLES = RANK_ORDER

BRAND = 0x2EE6A6
GOLD = 0xFFD166
PINK = 0xFF7EB6
TEAL = 0x7FDBDA

ROLE_SPECS = (
    (OWNER_ROLE, discord.Colour.gold(), True),
    (ADMIN_ROLE, discord.Colour.red(), True),
    (MOD_ROLE, discord.Colour.blue(), True),
    (GUIDE_ROLE, discord.Colour.teal(), True),
)

# (category, (logical name, topic, mode)).
# mode: news | docs | all | guide | mod | admin
STAFF_LAYOUT = (
    ("🌴 STAFF HQ", (
        ("staff-news", "Rank changes, outages, and decisions. Guide+ can read. Admin+ can post.", "news"),
        ("staff-chat", "All staff. Keep case talk short and take private things to your owner channel.", "all"),
    )),
    ("📖 HANDBOOK", (
        ("handbook", "How Tropical Tycoon staff act, in-game and on Discord. Guide+ can read. Admin+ can post.", "docs"),
    )),
    ("🛟 RANKS", (
        ("guide-chat", "Guides and up. Questions, shadowing, and small cases.", "guide"),
        ("mod-chat", "Mods and up. Kicks, tempbans, and cases a guide should hand over.", "mod"),
        ("admin-chat", "Admins and the owner. Permabans, rollbacks, and rank changes.", "admin"),
    )),
)
VENT_CATEGORY = "🫶 WITH THE OWNER"
DOCS_MARKER = "tt-staff-docs=1"
VENT_MARKER = "vent=1"

# Same ladder as the public rules. Keep this the only copy.
PUNISHMENT_LADDER = (
    ("Spam, flooding, caps", "Warning → 10m mute → 30m mute → 1h+ mute"),
    ("Minor insults, toxicity", "Warning → 30m mute → 2h mute → 12h mute"),
    ("Harassment, bodyshaming", "1h mute → 6h mute → 1d mute → 3d+ ban"),
    ("Hate speech, slurs", "1d mute → 3d mute → 7d mute → Permanent ban"),
    ("Threats (DDoS, dox, harm)", "1d ban → 7d ban → Permanent ban"),
    ("Sexual / NSFW content", "1d mute → 3d mute → 7d mute → Permanent ban"),
    ("Advertising other servers", "1d ban → 3d ban → 7d ban → Permanent ban"),
    ("Inappropriate name, skin or build", "Ban until changed → +1d → 7d ban → Permanent ban"),
    ("Impersonation", "1d ban → 7d ban → Permanent ban"),
    ("Personal info / phishing", "Permanent ban"),
    ("Macro, autoclicker, AFK-farming", "1d ban → 3d ban → 7d ban → 30d ban"),
    ("Cheats / hacked client", "7d ban → 30d ban → Permanent ban"),
    ("Bug abuse", "Warning + rollback → 1d ban → 7d ban → Permanent ban"),
    ("Duping / exploiting", "7d ban + rollback → Permanent ban"),
    ("Griefing", "1d ban + restore → 3d ban → 7d ban → Permanent ban"),
    ("Stealing", "Warning + return items → 1d ban → 3d ban → 7d+ ban"),
    ("Scamming", "7d ban → Permanent ban"),
    ("Real-money trading", "7d ban + item removal → Permanent ban"),
    ("Ban evasion / alt to break rules", "Permanent ban"),
    ("Chargeback", "Permanent ban"),
    ("Lying to staff / false reports", "Warning → 1h mute → 6h mute → 1d ban"),
    ("Staff disrespect", "Warning → 1h mute → 6h mute → 1d+ mute"),
)

_MODE_VIEW = {
    "news": GUIDE_ROLE,
    "docs": GUIDE_ROLE,
    "all": GUIDE_ROLE,
    "guide": GUIDE_ROLE,
    "mod": MOD_ROLE,
    "admin": ADMIN_ROLE,
}
_MODE_SEND = {
    "news": ADMIN_ROLE,
    "docs": ADMIN_ROLE,
    "all": GUIDE_ROLE,
    "guide": GUIDE_ROLE,
    "mod": MOD_ROLE,
    "admin": ADMIN_ROLE,
}


def is_staff_guild(guild) -> bool:
    return guild is not None and int(guild.id) == STAFF_GUILD_ID


def rank_at_least(role_name: str, minimum: str) -> bool:
    return RANK_ORDER.index(role_name) >= RANK_ORDER.index(minimum)


def holds_team_role(role_names, user_id: int, guild_owner_id: int) -> bool:
    """True when this person should have a private channel with the owner."""
    if int(user_id) == int(guild_owner_id):
        return False
    return any(name in role_names for name in TEAM_ROLES)


def channel_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", (name or "").lower())
    return re.sub(r"-+", "-", slug).strip("-")


def vent_channel_name(display_name: str) -> str:
    slug = channel_slug(display_name)[:40] or "staff"
    return f"vent-{slug}"


def topic_user_id(topic: str | None) -> int | None:
    for part in (topic or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() == "user" and value.strip().isdigit():
            return int(value.strip())
    return None


def vent_topic(user_id: int, open_channel: bool) -> str:
    state = "1" if open_channel else "0"
    return f"{VENT_MARKER}; user={int(user_id)}; open={state}"


def _footer(embed: discord.Embed, guild_name: str, icon_url: str | None) -> discord.Embed:
    embed.set_footer(text=f"{guild_name} · Tropical Tycoon staff", icon_url=icon_url)
    return embed


def staff_handbook_embeds(guild_name: str, icon_url: str | None = None) -> list[discord.Embed]:
    """How staff act. Text comes from the public rules and the rank ladder."""
    embeds: list[discord.Embed] = []

    intro = discord.Embed(
        title="✦  How Tropical Tycoon staff act",
        description=(
            "This server is staff only. Players never see these channels.\n\n"
            "The public rules (in-game `/rules` and the rules channel) are what players agreed to. "
            "You enforce those rules, including their **spirit**, not a private set of your own.\n"
            "Your rank is the ceiling. Doing more than your rank allows is a staff offence, "
            "the same as a player breaking a rule.\n\n"
            "Guide sees the guide rooms. Mod sees those plus the mod room. "
            "Admin sees those plus the admin room. The owner sees every room, "
            "including your private channel."
        ),
        colour=BRAND,
    )
    _footer(intro, guild_name, icon_url)
    embeds.append(intro)

    conduct = discord.Embed(
        title="Before you punish",
        description="Slow down. A wrong ban costs a player more than a slow one costs you.",
        colour=GOLD,
    )
    conduct.add_field(
        name="1. Proof first",
        value="Clip, screenshot, or the time and IGN. No proof, no punishment, except a threat that is happening right now.",
        inline=False,
    )
    conduct.add_field(
        name="2. Use the ladder",
        value="Start at the first step for that rule. Repeat offences move one step up. Skip steps only for a severe case (threats, doxxing, cheats, duping).",
        inline=False,
    )
    conduct.add_field(
        name="3. Hand it up",
        value="A guide stops at a 1 hour mute. A mod stops at a 7 day tempban. Permaban, rollback, and `/gens give` are admin. If you are unsure, ask in the rank channel or in your owner channel.",
        inline=False,
    )
    conduct.add_field(
        name="4. Stay off your own case",
        value="Friend, enemy, or someone you play with: pass the case to another staff member. Say that you did.",
        inline=False,
    )
    conduct.add_field(
        name="5. Keep it private",
        value="Don't post proof, igns of the punished, or the punishment in public chat or DMs. Players appeal with a ticket. One appeal per punishment.",
        inline=False,
    )
    conduct.add_field(
        name="6. Tools are for cases",
        value="Vanish, teleport, invsee, and jail are for an active case. Not for curiosity, not for your own island, not to impress anyone.",
        inline=False,
    )
    conduct.add_field(
        name="7. No real-life info",
        value="Never ask for, keep, or share someone's real name, address, photos, or account email. Phishing and doxxing are a permanent ban, including if a staff member does it.",
        inline=False,
    )
    conduct.add_field(
        name="8. Your channel with the owner",
        value="Each of you has a channel only you and the owner can see. Use it to vent, ask for help, or flag a staff problem. Other staff cannot read it. Write in whatever language is easiest.",
        inline=False,
    )
    _footer(conduct, guild_name, icon_url)
    embeds.append(conduct)

    ranks = discord.Embed(
        title="What your rank may do in-game",
        description=(
            "LuckPerms track `staff`: **guide < mod < admin < owner**. "
            "A higher rank can do everything the rank below it can do.\n"
            "There is no `/warn` command. A warning is a message to the player, then you record it in staff chat."
        ),
        colour=TEAL,
    )
    ranks.add_field(
        name="Guide",
        value=(
            "Mute up to **1 hour**. `/helpop` (the staff inbox), `/seen`, `/whois`, `/list`.\n"
            "You do **not** kick, ban, vanish, or open inventories."
        ),
        inline=False,
    )
    ranks.add_field(
        name="Mod",
        value=(
            "Kick. Mute of any length. Tempban up to **7 days** (`/tempban`). Vanish, `/tp`, `/tphere`.\n"
            "Look at an inventory (`/invsee`) without changing it. Visit an island. `/togglejail` when you need someone to stay still.\n"
            "CoreProtect lookup only. You do **not** permaban, roll back, or give items."
        ),
        inline=False,
    )
    ranks.add_field(
        name="Admin",
        value=(
            "Permaban and unban. CoreProtect rollback and restore. Island reset, delete, or transfer.\n"
            "`/gens give` and `/gens keys` (always with a reason; the server logs it). `/gens reload`.\n"
            "You may add or remove **Guide** and **Mod** only. You cannot grant Admin or Owner."
        ),
        inline=False,
    )
    ranks.add_field(
        name="Owner",
        value="Everything, including creative, `/op`, and LuckPerms. Nobody else gets those.",
        inline=False,
    )
    _footer(ranks, guild_name, icon_url)
    embeds.append(ranks)

    denied = discord.Embed(
        title="Nobody below owner",
        description="These stay off, even for admin. Don't ask a player to work around them.",
        colour=PINK,
    )
    denied.add_field(
        name="Blocked",
        value=(
            "Creative and other gamemodes. `/op` and `/deop`.\n"
            "LuckPerms beyond adding or removing Guide and Mod.\n"
            "Building on someone else's island with an admin bypass.\n"
            "A guide mute longer than 1 hour, or a mod ban longer than 7 days. Hand those up."
        ),
        inline=False,
    )
    denied.add_field(
        name="First-time AFK-farming",
        value="The public rules allow one lift on appeal if the player is honest. Don't promise it before the appeal is read.",
        inline=False,
    )
    _footer(denied, guild_name, icon_url)
    embeds.append(denied)

    ladder = discord.Embed(
        title="Punishment ladder",
        description=(
            "Same table as the public rules. Go up one step each time it happens again. "
            "Severe cases can start higher. Write the step you used in staff chat: IGN, rule, length, proof."
        ),
        colour=PINK,
    )
    for name, value in PUNISHMENT_LADDER[:12]:
        ladder.add_field(name=name, value=value, inline=False)
    _footer(ladder, guild_name, icon_url)
    embeds.append(ladder)

    ladder2 = discord.Embed(title="Punishment ladder (continued)", colour=PINK)
    for name, value in PUNISHMENT_LADDER[12:]:
        ladder2.add_field(name=name, value=value, inline=False)
    _footer(ladder2, guild_name, icon_url)
    embeds.append(ladder2)

    report = discord.Embed(
        title="Reports, appeals, leaving the team",
        colour=BRAND,
    )
    report.add_field(
        name="Reports",
        value="Players use in-game `/report` or a Player Report ticket. You don't tell them to handle it themselves, and you don't argue the case in public chat.",
        inline=False,
    )
    report.add_field(
        name="Appeals",
        value="One Punishment Appeal ticket per punishment. Lying in an appeal moves them up the ladder. You don't shorten a punishment in DMs.",
        inline=False,
    )
    report.add_field(
        name="If you step down",
        value="Your private channel closes for you and stays for the owner, so the history isn't lost. Rank rooms disappear with the role.",
        inline=False,
    )
    _footer(report, guild_name, icon_url)
    embeds.append(report)
    return embeds


def vent_welcome_embed(guild_name: str, icon_url: str | None) -> discord.Embed:
    embed = discord.Embed(
        title="✦  Your channel with the owner",
        description=(
            "Only you and the owner can see this. The other guides, mods, and admins cannot.\n\n"
            "Use it to get something off your chest, ask for help on a case, "
            "or say something you don't want in staff chat.\n"
            "Write in whatever language is easiest. Nothing you say here is forwarded."
        ),
        colour=BRAND,
    )
    return _footer(embed, guild_name, icon_url)


def _icon_url(guild) -> str | None:
    return guild.icon.url if guild.icon else None


def find_named(guild, logical_name: str):
    """Exact name, then slug match (🌴-staff-chat → staff-chat)."""
    exact = discord.utils.get(guild.text_channels, name=logical_name)
    if exact is not None:
        return exact
    for channel in guild.text_channels:
        slug = channel_slug(channel.name)
        if slug == logical_name or slug.endswith("-" + logical_name):
            return channel
    return None


def find_category(guild, name: str):
    exact = discord.utils.get(guild.categories, name=name)
    if exact is not None:
        return exact
    needle = channel_slug(name)
    for category in guild.categories:
        slug = channel_slug(category.name)
        if slug == needle or needle in slug:
            return category
    return None


def find_vent(guild, user_id: int):
    for channel in guild.text_channels:
        if topic_user_id(channel.topic) == int(user_id) and VENT_MARKER in (channel.topic or ""):
            return channel
    return None


def _role(guild, name: str):
    return discord.utils.get(guild.roles, name=name)


async def ensure_role(guild, name: str, colour: discord.Colour, hoist: bool):
    role = _role(guild, name)
    if role is not None:
        return role, False
    role = await guild.create_role(
        name=name,
        colour=colour,
        hoist=hoist,
        mentionable=True,
        reason="staff discord: create role",
    )
    return role, True


async def ensure_category(guild, name: str):
    category = find_category(guild, name)
    if category is not None:
        return category, False
    category = await guild.create_category(name, reason="staff discord: create category")
    await category.set_permissions(
        guild.default_role,
        view_channel=False,
        reason="staff discord: hide category",
    )
    return category, True


async def apply_rank_mode(channel, guild, mode: str):
    view_min = _MODE_VIEW[mode]
    send_min = _MODE_SEND[mode]
    await channel.set_permissions(
        guild.default_role,
        view_channel=False,
        reason="staff discord: hide from members",
    )
    for name in RANK_ORDER:
        role = _role(guild, name)
        if role is None:
            continue
        if not rank_at_least(name, view_min):
            # No deny: a person who also holds a higher role must not be blocked by the lower one.
            await channel.set_permissions(role, overwrite=None, reason="staff discord: clear lower rank")
            continue
        can_send = rank_at_least(name, send_min)
        await channel.set_permissions(
            role,
            view_channel=True,
            send_messages=can_send,
            read_message_history=True,
            add_reactions=True,
            attach_files=can_send,
            embed_links=can_send,
            manage_messages=name in (ADMIN_ROLE, OWNER_ROLE),
            reason="staff discord: rank access",
        )


async def post_handbook(channel, guild, force: bool) -> bool:
    topic = channel.topic or ""
    if DOCS_MARKER in topic and not force:
        return False
    icon = _icon_url(guild)
    for embed in staff_handbook_embeds(guild.name, icon):
        await channel.send(embed=embed)
    base = topic.replace(DOCS_MARKER, "").strip(" ;")
    new_topic = f"{base}; {DOCS_MARKER}".strip("; ") if base else DOCS_MARKER
    await channel.edit(topic=new_topic[:1024], reason="staff discord: handbook posted")
    return True


async def open_vent(guild, member) -> str:
    """Create or reopen the private owner channel. Returns a short status."""
    if member.bot or not holds_team_role({r.name for r in member.roles}, member.id, guild.owner_id):
        return "skip"
    category, _ = await ensure_category(guild, VENT_CATEGORY)
    owner_role = _role(guild, OWNER_ROLE)
    if owner_role is not None:
        await category.set_permissions(
            owner_role,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,
            reason="staff discord: owner sees every private channel",
        )
    channel = find_vent(guild, member.id)
    created = False
    if channel is None:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        }
        if owner_role is not None:
            overwrites[owner_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            )
        owner_member = guild.get_member(guild.owner_id)
        if owner_member is not None:
            overwrites[owner_member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            )
        name = vent_channel_name(member.display_name)
        if discord.utils.get(guild.text_channels, name=name) is not None:
            name = f"{name}-{str(member.id)[-4:]}"[:100]
        channel = await guild.create_text_channel(
            name,
            category=category,
            topic=vent_topic(member.id, True),
            overwrites=overwrites,
            reason="staff discord: private channel with the owner",
        )
        created = True
    else:
        await channel.edit(
            category=category,
            topic=vent_topic(member.id, True),
            reason="staff discord: reopen private channel",
        )
        await channel.set_permissions(
            member,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
            reason="staff discord: staff member can speak here",
        )
    if created:
        await channel.send(content=member.mention, embed=vent_welcome_embed(guild.name, _icon_url(guild)))
        return "created"
    return "open"


async def close_vent(guild, member) -> str:
    channel = find_vent(guild, member.id)
    if channel is None:
        return "none"
    await channel.set_permissions(member, view_channel=False, reason="staff discord: left the team")
    await channel.edit(topic=vent_topic(member.id, False), reason="staff discord: private channel closed")
    owner = guild.get_member(guild.owner_id)
    who = owner.mention if owner is not None else "owner"
    await channel.send(
        f"{who} — **{member.display_name}** no longer has a staff role. "
        "They can't see this channel anymore. The history stays here."
    )
    return "closed"


async def sync_staff_guild(bot, force_docs: bool = False) -> str | None:
    """Idempotent setup for the staff server. None when that server isn't connected."""
    guild = bot.get_guild(STAFF_GUILD_ID)
    if guild is None:
        print(f"staff discord: bot is not in guild {STAFF_GUILD_ID}", flush=True)
        return None
    me = guild.me
    if me is None or not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
        print("staff discord: need Manage Channels and Manage Roles, with the bot role above Guide/Mod/Admin", flush=True)
        return "missing permissions"
    if not guild.chunked and bot.intents.members:
        try:
            await guild.chunk()
        except discord.HTTPException as exc:
            print(f"staff discord: member list unavailable ({exc})", flush=True)

    for name, colour, hoist in ROLE_SPECS:
        await ensure_role(guild, name, colour, hoist)

    docs_channel = None
    for category_name, channels in STAFF_LAYOUT:
        category, _ = await ensure_category(guild, category_name)
        for logical, topic, mode in channels:
            channel = find_named(guild, logical)
            if channel is None:
                channel = await guild.create_text_channel(
                    logical,
                    category=category,
                    topic=topic,
                    reason="staff discord: create channel",
                )
            else:
                await channel.edit(category=category, topic=channel.topic or topic, reason="staff discord: place channel")
            await apply_rank_mode(channel, guild, mode)
            if logical == "handbook":
                docs_channel = channel
    if docs_channel is not None:
        await post_handbook(docs_channel, guild, force_docs)

    opened = 0
    if bot.intents.members:
        for member in guild.members:
            if holds_team_role({r.name for r in member.roles}, member.id, guild.owner_id):
                status = await open_vent(guild, member)
                if status in ("created", "open"):
                    opened += 1
    else:
        print("staff discord: DISCORD_PRIVILEGED_INTENTS=1 is required for private channels", flush=True)
    print(f"staff discord: ready on {guild.name}, private channels checked: {opened}", flush=True)
    return f"ready ({opened} private channels)"


def setup(bot) -> None:
    if getattr(bot, "_tt_staff_discord_loaded", False):
        return
    bot._tt_staff_discord_loaded = True

    @bot.tree.command(name="setupstaff", description="Build the Tropical staff rooms on the staff server")
    @app_commands.describe(
        confirm="False = preview. True = create roles, rooms, handbook, and private channels.",
        refresh_docs="True = post the handbook again even if it is already there.",
    )
    @app_commands.default_permissions(administrator=True)
    async def setupstaff(interaction: discord.Interaction, confirm: bool = False, refresh_docs: bool = False):
        guild = interaction.guild
        if not is_staff_guild(guild):
            await interaction.response.send_message(
                f"Staff rooms are only built on the staff server (`{STAFF_GUILD_ID}`).",
                ephemeral=True,
            )
            return
        if not confirm:
            lines = ["**Staff server preview** (nothing changed).", ""]
            for category_name, channels in STAFF_LAYOUT:
                bits = []
                for logical, _, mode in channels:
                    found = find_named(guild, logical)
                    bits.append(f"{found.mention if found else '`#' + logical + '` missing'} ({mode})")
                lines.append(f"**{category_name}** — " + ", ".join(bits))
            lines.append("")
            lines.append(f"**{VENT_CATEGORY}** — one private channel per Guide, Mod, Admin, and Owner (not you).")
            lines.append("Run `/setupstaff confirm:True` to apply.")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            result = await sync_staff_guild(interaction.client, force_docs=refresh_docs)
        except discord.Forbidden:
            await interaction.followup.send(
                "I'm missing permission. I need **Manage Channels**, **Manage Roles**, and my role above Guide, Mod, and Admin.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"Staff rooms are ready. {result or 'done'}.\n"
            "Give someone **Guide**, **Mod**, or **Admin** and their private channel with you appears on its own.",
            ephemeral=True,
        )

    async def on_member_update(before: discord.Member, after: discord.Member):
        if not is_staff_guild(after.guild) or after.bot:
            return
        before_names = {role.name for role in before.roles}
        after_names = {role.name for role in after.roles}
        if before_names == after_names:
            return
        was = holds_team_role(before_names, after.id, after.guild.owner_id)
        now = holds_team_role(after_names, after.id, after.guild.owner_id)
        try:
            if not was and now:
                await open_vent(after.guild, after)
            elif was and not now:
                await close_vent(after.guild, after)
        except discord.Forbidden:
            print(f"staff discord: could not update private channel for {after.id}", flush=True)

    bot.add_listener(on_member_update, "on_member_update")

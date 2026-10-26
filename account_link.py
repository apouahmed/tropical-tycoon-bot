"""Link a Discord user to a Minecraft account and keep rank roles in sync.

/link whispers a code with /msg (the player must be online). /unlink clears it.
A background pass re-reads LuckPerms and updates roles. /ranksync does one user now.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import discord
from discord import app_commands

import rank_sync
import rcon_client
import staff_actions
import staff_manage

LINKS_PATH = Path(__file__).with_name("links.json")
_book = rank_sync.LinkDirectory()
_save_lock = asyncio.Lock()

STAFF_COLOURS = {
    "Owner": 0xF1C40F,
    "Admin": 0xE74C3C,
    "Mod": 0x3498DB,
    "Guide": 0x1ABC9C,
}


def load() -> None:
    if not LINKS_PATH.is_file():
        return
    try:
        raw = json.loads(LINKS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"Could not read {LINKS_PATH.name}: {e}", flush=True)
        return
    links = raw.get("links") if isinstance(raw, dict) else None
    pending = raw.get("pending") if isinstance(raw, dict) else None
    if isinstance(links, dict):
        _book.links = {str(k): v for k, v in links.items() if isinstance(v, dict)}
    if isinstance(pending, dict):
        _book.pending = {str(k): v for k, v in pending.items() if isinstance(v, dict)}


def save() -> None:
    payload = {"links": _book.links, "pending": _book.pending}
    tmp = LINKS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(LINKS_PATH)


def sync_minutes() -> int:
    raw = (os.getenv("RANK_SYNC_MINUTES") or "10").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 10


async def _msg(player: str, code: str) -> str:
    command = rank_sync.link_message_command(player, code)
    return await asyncio.to_thread(rcon_client.execute, command)


async def _groups(player: str) -> set[str] | None:
    try:
        text = await asyncio.to_thread(rcon_client.execute, rank_sync.parent_info_command(player))
    except rcon_client.RconError as e:
        print(f"rank lookup failed for {player}: {e}", flush=True)
        return None
    if not rank_sync.groups_response_ok(text):
        print(f"rank lookup not usable for {player}: {text[:180]}", flush=True)
        return None
    return rank_sync.parse_groups(text)


def _role_named(guild: discord.Guild, name: str) -> discord.Role | None:
    return discord.utils.get(guild.roles, name=name)


async def _ensure_role(guild: discord.Guild, name: str) -> discord.Role | None:
    existing = _role_named(guild, name)
    if existing is not None:
        return existing
    colour = STAFF_COLOURS.get(name)
    if colour is None:
        for _key, display, hex_colour in rank_sync.STORE_LADDER:
            if display == name:
                colour = hex_colour
                break
    try:
        return await guild.create_role(
            name=name,
            colour=discord.Colour(colour or 0x99AAB5),
            hoist=name in rank_sync.STORE_ROLE_NAMES or name in rank_sync.STAFF_ROLE_NAMES,
            mentionable=False,
            reason="Tropical Tycoon rank sync",
        )
    except discord.HTTPException as e:
        print(f"Could not create role {name}: {e}", flush=True)
        return None


async def apply_plan(member: discord.Member, groups: set[str]) -> rank_sync.RolePlan:
    guild = member.guild
    row = _book.get(member.id) or {}
    plan = rank_sync.plan_roles(
        {role.name for role in member.roles},
        groups,
        row.get("managed_staff"),
    )
    me = guild.me
    to_add: list[discord.Role] = []
    to_remove: list[discord.Role] = []
    blocked: list[str] = []
    for name in plan.add:
        role = await _ensure_role(guild, name)
        if role is None:
            blocked.append(name)
            continue
        if me is not None and role >= me.top_role:
            blocked.append(name)
            continue
        to_add.append(role)
    for name in plan.remove:
        role = _role_named(guild, name)
        if role is None:
            continue
        if me is not None and role >= me.top_role:
            blocked.append(name)
            continue
        to_remove.append(role)
    if to_add:
        await member.add_roles(*to_add, reason="Tropical Tycoon rank sync")
    if to_remove:
        await member.remove_roles(*to_remove, reason="Tropical Tycoon rank sync")
    if blocked:
        print(
            f"Could not edit roles above the bot for {member}: {', '.join(blocked)}",
            flush=True,
        )
    _book.set_managed_staff(member.id, plan.managed_staff)
    return plan


def _summary(plan: rank_sync.RolePlan) -> str:
    store = plan.store or "no store rank"
    staff = plan.staff or "no staff rank"
    return f"**Store:** {store}\n**Staff:** {staff}"


async def sync_member(member: discord.Member) -> str:
    row = _book.get(member.id)
    if not row:
        return "You are not linked. Run /link while you are on the server."
    groups = await _groups(str(row["name"]))
    if groups is None:
        return (
            f"Linked as `{row['name']}`, but LuckPerms did not answer. "
            "Your Discord roles were left as they are."
        )
    async with _save_lock:
        plan = await apply_plan(member, groups)
        save()
    return f"Linked as `{row['name']}`.\n{_summary(plan)}"


async def sync_name(bot: discord.Client, name: str) -> None:
    discord_id = _book.owner_of(name)
    if not discord_id:
        return
    for guild in bot.guilds:
        member = guild.get_member(int(discord_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(discord_id))
            except discord.HTTPException:
                continue
        try:
            await sync_member(member)
        except discord.HTTPException as e:
            print(f"rank sync for {name} failed: {e}", flush=True)


async def sync_all(bot: discord.Client) -> None:
    ids = list(_book.links)
    if not ids:
        return
    print(f"Rank sync for {len(ids)} linked account(s).", flush=True)
    for discord_id in ids:
        for guild in bot.guilds:
            member = guild.get_member(int(discord_id))
            if member is None:
                continue
            try:
                await sync_member(member)
            except discord.HTTPException as e:
                print(f"rank sync {discord_id} failed: {e}", flush=True)
            await asyncio.sleep(0.4)


class CodeModal(discord.ui.Modal, title="Enter your link code"):
    code = discord.ui.TextInput(
        label="Code from Minecraft chat",
        placeholder="AB12CD",
        min_length=6,
        max_length=8,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await _confirm_and_sync(interaction, str(self.code))


class EnterCodeView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=rank_sync.LINK_TTL_SECONDS)

    @discord.ui.button(label="Enter code", emoji="🔗", style=discord.ButtonStyle.success)
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(CodeModal())


class LinkNameModal(discord.ui.Modal, title="Link your Minecraft account"):
    player = discord.ui.TextInput(
        label="Minecraft name",
        placeholder="Steve or .Steve for Bedrock",
        max_length=16,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        import time

        try:
            name = staff_name(str(self.player))
        except rank_sync.RankError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        code = rank_sync.new_code()
        async with _save_lock:
            sent_code, error = _book.start(str(interaction.user.id), name, code, time.time())
            if error is None:
                save()
        if error:
            await interaction.followup.send(error, ephemeral=True)
            return
        try:
            result = await _msg(name, sent_code)
        except rcon_client.RconError as e:
            await interaction.followup.send(
                f"Could not reach the server: {e}\nJoin play.tropicaltycoon.nl and try again.",
                ephemeral=True,
            )
            return
        if rank_sync.player_offline(result):
            await interaction.followup.send(
                f"`{name}` is not online on skyblock. Join, then run /link again.",
                ephemeral=True,
            )
            return
        if rank_sync.whisper_failed(result):
            await interaction.followup.send(
                "The server did not deliver the code. Check that Essentials `/msg` works from the console.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"I sent a code to `{name}` in Minecraft chat. It expires in 10 minutes.",
            view=EnterCodeView(),
            ephemeral=True,
        )


def staff_name(raw: str) -> str:
    try:
        return staff_actions.minecraft_name(raw)
    except staff_actions.ActionError as e:
        raise rank_sync.RankError(str(e)) from e


def setup(bot: discord.Client) -> None:
    if getattr(bot, "_tt_account_link_loaded", False):
        return
    bot._tt_account_link_loaded = True  # type: ignore[attr-defined]
    load()
    staff_manage.after_store_grant = sync_name

    @bot.tree.command(name="link", description="Link your Minecraft account so your rank becomes a Discord role")
    async def link(interaction: discord.Interaction) -> None:
        row = _book.get(interaction.user.id)
        if row:
            await interaction.response.send_message(
                f"You are linked as `{row['name']}`.\n"
                "Use `/ranksync` to refresh your roles, or `/unlink` to disconnect.",
                ephemeral=True,
            )
            return
        if rcon_client.RconConfig.from_env() is None:
            await interaction.response.send_message(
                "Linking needs RCON. Set `RCON_HOST` and `RCON_PASSWORD` on the bot, then restart it.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(LinkNameModal())

    @bot.tree.command(name="unlink", description="Disconnect your Minecraft account and drop synced rank roles")
    async def unlink(interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use this in the server.", ephemeral=True)
            return
        async with _save_lock:
            row = _book.unlink(str(interaction.user.id))
            save()
        if not row:
            await interaction.response.send_message("You are not linked.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        managed = row.get("managed_staff")
        remove_names = set(rank_sync.STORE_ROLE_NAMES)
        if managed:
            remove_names.add(str(managed))
        roles = [
            role
            for role in interaction.user.roles
            if role.name in remove_names and (interaction.guild.me is None or role < interaction.guild.me.top_role)
        ]
        if roles:
            try:
                await interaction.user.remove_roles(*roles, reason="Tropical Tycoon unlink")
            except discord.HTTPException as e:
                await interaction.followup.send(
                    f"Unlinked `{row['name']}`, but I could not remove roles: {e}",
                    ephemeral=True,
                )
                return
        await interaction.followup.send(
            f"Unlinked `{row['name']}`. Store roles from the sync were removed.",
            ephemeral=True,
        )
        await staff_manage.post_staff_log(
            title="Account unlinked",
            description=f"{interaction.user} unlinked `{row['name']}`",
            actor=interaction.user,
        )

    @bot.tree.command(name="ranksync", description="Refresh your Discord roles from your in-game rank")
    async def ranksync(interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use this in the server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            text = await sync_member(interaction.user)
        except discord.HTTPException as e:
            text = f"Could not update roles: {e}"
        await interaction.followup.send(text, ephemeral=True)

    print("Account link commands loaded: /link /unlink /ranksync", flush=True)


async def ensure_rank_rooms(guild: discord.Guild) -> list[str]:
    """Create store roles and the three rank channels. Safe to run again."""
    made: list[str] = []
    me = guild.me
    if me is None or not me.guild_permissions.manage_roles or not me.guild_permissions.manage_channels:
        print(f"Rank rooms skipped in {guild.name}: need Manage Roles and Manage Channels.", flush=True)
        return made
    for _key, display, colour in rank_sync.STORE_LADDER:
        if _role_named(guild, display) is None:
            await guild.create_role(
                name=display,
                colour=discord.Colour(colour),
                hoist=True,
                mentionable=False,
                reason="Tropical Tycoon store rank",
            )
            made.append(f"role:{display}")
            await asyncio.sleep(0.3)
    category = discord.utils.get(guild.categories, name=rank_sync.RANK_CATEGORY)
    if category is None:
        category = await guild.create_category(
            rank_sync.RANK_CATEGORY, reason="Tropical Tycoon rank channels"
        )
        made.append(f"category:{rank_sync.RANK_CATEGORY}")
        await asyncio.sleep(0.3)
    everyone = guild.default_role
    staff = [
        role
        for name in ("Guide", "Mod", "Admin", "Owner")
        if (role := _role_named(guild, name)) is not None
    ]
    for room in rank_sync.RANK_ROOMS:
        channel = discord.utils.get(guild.text_channels, name=room.name)
        if channel is None:
            channel = await guild.create_text_channel(
                room.name,
                category=category,
                topic=room.topic,
                reason="Tropical Tycoon rank channel",
            )
            made.append(f"#{room.name}")
            await asyncio.sleep(0.3)
        elif channel.category != category:
            await channel.edit(category=category, reason="Tropical Tycoon rank channel")
        await channel.set_permissions(
            everyone, view_channel=False, send_messages=False, reason="rank channel hidden"
        )
        allowed_names = set(room.allow)
        for name in allowed_names:
            role = _role_named(guild, name)
            if role is None:
                continue
            await channel.set_permissions(
                role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
                add_reactions=True,
                reason="rank channel access",
            )
        for name in rank_sync.STORE_ROLE_NAMES - allowed_names:
            role = _role_named(guild, name)
            if role is None:
                continue
            await channel.set_permissions(
                role, view_channel=False, send_messages=False, reason="rank channel excluded"
            )
        for role in staff:
            await channel.set_permissions(
                role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                reason="rank channel staff",
            )
        await asyncio.sleep(0.3)
    if made:
        print(f"Rank rooms in {guild.name}: {', '.join(made)}", flush=True)
    return made


def start_loop(bot: discord.Client) -> None:
    if getattr(bot, "_tt_rank_sync_started", False):
        return
    minutes = sync_minutes()
    if minutes <= 0:
        print("Rank sync loop off (RANK_SYNC_MINUTES=0).", flush=True)
        return
    bot._tt_rank_sync_started = True  # type: ignore[attr-defined]

    async def runner() -> None:
        await bot.wait_until_ready()
        for guild in list(bot.guilds):
            try:
                await ensure_rank_rooms(guild)
            except discord.HTTPException as e:
                print(f"Rank rooms failed in {guild.name}: {e}", flush=True)
        while not bot.is_closed():
            await asyncio.sleep(minutes * 60)
            try:
                await sync_all(bot)
            except Exception as e:
                print(f"rank sync loop failed: {e}", flush=True)

    asyncio.create_task(runner())
    print(f"Rank sync loop every {minutes} min.", flush=True)


# Code confirmation uses wall-clock time, matching LinkDirectory.start.
async def _confirm_and_sync(interaction: discord.Interaction, typed: str) -> None:
    import time

    async with _save_lock:
        name, error = _book.confirm(interaction.user.id, typed, time.time())
        save()
    if error or not name:
        await interaction.followup.send(error or "Link failed.", ephemeral=True)
        return
    if not isinstance(interaction.user, discord.Member):
        await interaction.followup.send(f"Linked as `{name}`. Run /ranksync in the server.", ephemeral=True)
        return
    try:
        text = await sync_member(interaction.user)
    except discord.HTTPException as e:
        text = f"Linked as `{name}`, but roles could not be updated: {e}"
    await interaction.followup.send(text, ephemeral=True)
    await staff_manage.post_staff_log(
        title="Account linked",
        description=f"{interaction.user} linked `{name}`",
        actor=interaction.user,
    )

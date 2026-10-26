"""
Tropical Tycoon staff control center — Discord management hub.

Owner:
- /manage          post the persistent Staff Control Center panel
- /lookup          balance + LuckPerms info via RCON
- /givekeys        grant mystery/monthly keys (reason + tx id)
- /givexp          grant Tycoon XP
- /move            send a player to hub, skyblock or boss
- /kick            kick with a reason
- /announce        broadcast with /say
- /serverstatus    online list + network snapshot
- /acrecent        recent fishing tension AC embeds from the log channel

Anyone:
- /play            join address and store link

Action audits post to STAFF_LOG_WEBHOOK when set (never commit the URL).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import urllib.error
import urllib.request
import discord
from discord import app_commands
from discord.ext import commands

import rcon_client
import staff_actions

BRAND = 0x2EE6A6
GOLD = 0xFFD166
PINK = 0xFF7EB6
TEAL = 0x7FDBDA
RED = 0xEF4444
BLUE = 0x3B82F6
SLATE = 0x64748B

GUIDE_ROLE = "Guide"
MOD_ROLE = "Mod"
ADMIN_ROLE = "Admin"
OWNER_ROLE = "Owner"
STAFF_ROLE_NAMES = (GUIDE_ROLE, MOD_ROLE, ADMIN_ROLE, OWNER_ROLE)
ADMIN_PLUS_NAMES = (ADMIN_ROLE, OWNER_ROLE)

STAFF_LOG_WEBHOOK = (os.getenv("STAFF_LOG_WEBHOOK") or "").strip()
AC_LOG_CHANNEL_ID = (os.getenv("AC_LOG_CHANNEL_ID") or "").strip()
PLAY_ADDRESS = os.getenv("PLAY_ADDRESS", "104.204.217.168:25566")
STORE_URL = os.getenv("STORE_URL", "https://tropicaltycoon.tebex.store/")

# Comma-separated Discord user snowflakes. If set, only these users may use /manage etc.
# If empty: server owner only (guild.owner_id).
_OWNER_IDS_RAW = (os.getenv("DISCORD_OWNER_IDS") or os.getenv("DISCORD_OWNER_ID") or "").strip()
OWNER_IDS: frozenset[int] = frozenset(
    int(part.strip())
    for part in _OWNER_IDS_RAW.split(",")
    if part.strip().isdigit()
)

USER_AGENT = "Mozilla/5.0 (compatible; TropicalTycoonBot/1.0)"


def _role(guild: discord.Guild | None, name: str) -> discord.Role | None:
    if guild is None:
        return None
    return discord.utils.get(guild.roles, name=name)


def _has_any_role(member: discord.Member | discord.User, names: tuple[str, ...]) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    have = {r.name for r in member.roles}
    return any(n in have for n in names)


def is_owner(member: discord.Member | discord.User, guild: discord.Guild | None = None) -> bool:
    """Only the configured owner id(s), or the Discord server owner if none configured."""
    if member is None:
        return False
    if OWNER_IDS:
        return int(member.id) in OWNER_IDS
    g = guild or getattr(member, "guild", None)
    if g is not None and g.owner_id is not None:
        return int(member.id) == int(g.owner_id)
    return False


def is_staff(member: discord.Member | discord.User) -> bool:
    # Control Center is owner-only; keep helper for any future Guide+ tools.
    return is_owner(member) or _has_any_role(member, STAFF_ROLE_NAMES)


def is_admin_plus(member: discord.Member | discord.User) -> bool:
    return is_owner(member) or _has_any_role(member, ADMIN_PLUS_NAMES)


def can_manage(member: discord.Member | discord.User, guild: discord.Guild | None = None) -> bool:
    return is_owner(member, guild)


def footer(embed: discord.Embed, guild: discord.Guild | None) -> None:
    name = guild.name if guild else "Tropical Tycoon"
    if guild and guild.icon:
        embed.set_footer(text=f"{name} · Staff Control", icon_url=guild.icon.url)
    else:
        embed.set_footer(text=f"{name} · Staff Control")


def hub_embed(guild: discord.Guild | None) -> discord.Embed:
    rcon_ok = rcon_client.RconConfig.from_env() is not None
    embed = discord.Embed(
        title="✦  Staff Control Center",
        description=(
            "Manage Tropical Tycoon from Discord — players, moderation, economy grants, "
            "events and live network status.\n\n"
            "**How to use**\n"
            "Pick a module in the menu below. Sensitive actions need **Admin+** and a reason; "
            "every grant is logged to the staff audit channel.\n\n"
            f"**Play:** `{PLAY_ADDRESS}`\n"
            f"**Store:** {STORE_URL}\n"
            f"**RCON bridge:** {'online' if rcon_ok else 'offline — set `RCON_HOST` / `RCON_PASSWORD` in `.env`'}"
        ),
        colour=BRAND,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.add_field(
        name="🎣 Fishing AC",
        value="Recent tension flags · thresholds · what gets logged",
        inline=True,
    )
    embed.add_field(
        name="👤 Players",
        value="Profile · online list · move between servers",
        inline=True,
    )
    embed.add_field(
        name="⛔ Moderation",
        value="Kick · server-wide announcement",
        inline=True,
    )
    embed.add_field(
        name="💰 Economy",
        value="Keys · boosters · XP · pets · store rank",
        inline=True,
    )
    embed.add_field(
        name="🎉 Events",
        value="Start / stop scheduled events via console",
        inline=True,
    )
    embed.add_field(
        name="🌐 Network",
        value="Skyblock / hub / boss snapshot",
        inline=True,
    )
    embed.add_field(
        name="🛠 Tools",
        value="Quick slash commands & webhook health",
        inline=True,
    )
    if guild and guild.icon:
        embed.set_author(name=guild.name, icon_url=guild.icon.url)
        embed.set_thumbnail(url=guild.icon.url)
    footer(embed, guild)
    return embed


async def post_staff_log(
    *,
    title: str,
    description: str,
    colour: int = GOLD,
    fields: list[tuple[str, str, bool]] | None = None,
    actor: discord.abc.User | None = None,
) -> None:
    if not STAFF_LOG_WEBHOOK.startswith("https://"):
        return
    embed: dict = {
        "title": title,
        "description": description[:4000],
        "color": colour,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if fields:
        embed["fields"] = [
            {"name": n[:256], "value": v[:1024], "inline": inline}
            for n, v, inline in fields
        ]
    if actor is not None:
        embed["footer"] = {"text": f"by {actor} ({actor.id})"}
    body = json.dumps({"embeds": [embed]}).encode("utf-8")

    def _send() -> None:
        req = urllib.request.Request(
            STAFF_LOG_WEBHOOK,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            print(f"staff log webhook HTTP {e.code}", flush=True)
        except urllib.error.URLError as e:
            print(f"staff log webhook failed: {e}", flush=True)

    await asyncio.to_thread(_send)


async def run_rcon(command: str) -> str:
    return await asyncio.to_thread(rcon_client.execute, command)


def _clip(text: str, limit: int = 900) -> str:
    text = (text or "").strip() or "(empty response)"
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# ---------- views ----------
class StaffHubView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(StaffModuleSelect())


class StaffModuleSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label="Fishing AC",
                value="ac",
                emoji="🎣",
                description="Tension flags, thresholds, log channel",
            ),
            discord.SelectOption(
                label="Players",
                value="players",
                emoji="👤",
                description="Profile, online list, move server",
            ),
            discord.SelectOption(
                label="Moderation",
                value="moderation",
                emoji="⛔",
                description="Kick and announce",
            ),
            discord.SelectOption(
                label="Economy",
                value="economy",
                emoji="💰",
                description="Keys, boosters, XP, pets, ranks",
            ),
            discord.SelectOption(
                label="Events",
                value="events",
                emoji="🎉",
                description="Start or stop server events",
            ),
            discord.SelectOption(
                label="Network",
                value="network",
                emoji="🌐",
                description="Live network / server list",
            ),
            discord.SelectOption(
                label="Tools",
                value="tools",
                emoji="🛠",
                description="Slash shortcuts and health",
            ),
        ]
        super().__init__(
            placeholder="Open a management module…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="tt:staff:module",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "Server owner only.", ephemeral=True
            )
            return
        choice = self.values[0]
        if choice == "ac":
            await interaction.response.send_message(
                embed=ac_overview_embed(interaction.guild),
                view=AcModuleView(),
                ephemeral=True,
            )
        elif choice == "players":
            await interaction.response.send_message(
                embed=players_overview_embed(interaction.guild),
                view=PlayersModuleView(),
                ephemeral=True,
            )
        elif choice == "moderation":
            await interaction.response.send_message(
                embed=moderation_overview_embed(interaction.guild),
                view=ModerationModuleView(),
                ephemeral=True,
            )
        elif choice == "economy":
            await interaction.response.send_message(
                embed=economy_overview_embed(interaction.guild),
                view=EconomyModuleView(),
                ephemeral=True,
            )
        elif choice == "events":
            await interaction.response.send_message(
                embed=events_overview_embed(interaction.guild),
                view=EventsModuleView(),
                ephemeral=True,
            )
        elif choice == "network":
            await interaction.response.defer(ephemeral=True)
            embed = await network_status_embed(interaction.guild)
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(
                embed=tools_overview_embed(interaction.guild),
                view=ToolsModuleView(),
                ephemeral=True,
            )
        # Reset select so it can be used again on the persistent message.
        if interaction.message is not None:
            try:
                await interaction.message.edit(view=StaffHubView())
            except discord.HTTPException:
                pass


class AcModuleView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=180)

    @discord.ui.button(label="Recent flags", emoji="🚩", style=discord.ButtonStyle.danger)
    async def recent(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        embed = await fetch_ac_recent(interaction.client, interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Thresholds", emoji="📐", style=discord.ButtonStyle.secondary)
    async def thresholds(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = discord.Embed(
            title="🎣  Tension AC thresholds",
            description=(
                "Configured in live `fishing.yml` (not committed):\n\n"
                "```yaml\n"
                "anticheat-webhook: \"<discord webhook>\"\n"
                "anticheat:\n"
                "  window: 40\n"
                "  min-samples: 30\n"
                "  max-stddev: 1.0          # Java\n"
                "  bedrock-max-stddev: 1.5\n"
                "  min-perfect-rate: 0.70\n"
                "  soften-after-flags: 0   # log only\n"
                "```\n"
                "A flag needs **low offset spread + high perfect rate**. "
                "Auto-reel rods are ignored. Soft nerf is off until you raise "
                "`soften-after-flags`."
            ),
            colour=PINK,
        )
        footer(embed, interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class PlayersModuleView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=180)

    @discord.ui.button(label="Lookup player", emoji="🔍", style=discord.ButtonStyle.primary)
    async def lookup(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(LookupModal())

    @discord.ui.button(label="Who is online", emoji="📋", style=discord.ButtonStyle.secondary)
    async def online(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        embed = await online_embed(interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Move server", emoji="🚀", style=discord.ButtonStyle.success)
    async def move(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(MoveModal())


class EconomyModuleView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=180)

    @discord.ui.button(label="Grant keys", emoji="🔑", style=discord.ButtonStyle.success)
    async def keys(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(GiveKeysModal())

    @discord.ui.button(label="Grant booster", emoji="⚡", style=discord.ButtonStyle.primary)
    async def booster(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(GiveBoosterModal())

    @discord.ui.button(label="Store rank", emoji="👑", style=discord.ButtonStyle.secondary)
    async def store(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(StoreRankModal())

    @discord.ui.button(label="Tycoon XP", emoji="✨", style=discord.ButtonStyle.primary, row=1)
    async def xp(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(GiveXpModal())

    @discord.ui.button(label="Credit vote", emoji="🗳️", style=discord.ButtonStyle.secondary, row=1)
    async def vote(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(CreditVoteModal())

    @discord.ui.button(label="Give pet", emoji="🐾", style=discord.ButtonStyle.success, row=1)
    async def pet(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(GivePetModal())


class ModerationModuleView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=180)

    @discord.ui.button(label="Kick", emoji="👢", style=discord.ButtonStyle.danger)
    async def kick(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(KickModal())

    @discord.ui.button(label="Announce", emoji="📣", style=discord.ButtonStyle.primary)
    async def announce(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(AnnounceModal())


class ToolsModuleView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=180)

    @discord.ui.button(label="Announce", emoji="📣", style=discord.ButtonStyle.primary)
    async def announce(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(AnnounceModal())


class EventsModuleView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=180)
        self.add_item(EventSelect())


class EventSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="Gen Overload — 15m", value="start:gen-overload:15"),
            discord.SelectOption(label="Gen Overload — 30m", value="start:gen-overload:30"),
            discord.SelectOption(label="Sell Frenzy — 15m", value="start:sell-frenzy:15"),
            discord.SelectOption(label="Sell Frenzy — 30m", value="start:sell-frenzy:30"),
            discord.SelectOption(label="Lucky Drops — 15m", value="start:lucky-drops:15"),
            discord.SelectOption(label="Lucky Drops — 30m", value="start:lucky-drops:30"),
            discord.SelectOption(label="Stop hand-started event", value="stop"),
        ]
        super().__init__(
            placeholder="Pick an event action…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="tt:staff:event",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        choice = self.values[0]
        try:
            cmd = staff_actions.event_command(choice)
        except staff_actions.ActionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        try:
            result = await run_rcon(cmd)
            ok = True
            detail = _clip(result)
        except rcon_client.RconError as e:
            ok = False
            detail = str(e)
        colour = BRAND if ok else RED
        embed = discord.Embed(
            title="🎉  Event action",
            description=f"```\n{cmd}\n```\n```\n{detail}\n```",
            colour=colour,
        )
        footer(embed, interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await post_staff_log(
            title="Event action",
            description=f"`{cmd}`\n```\n{detail}\n```",
            colour=colour,
            actor=interaction.user,
        )


# ---------- modals ----------
class LookupModal(discord.ui.Modal, title="Player lookup"):
    player = discord.ui.TextInput(
        label="Minecraft name",
        placeholder="Steve",
        min_length=1,
        max_length=32,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            name = staff_actions.minecraft_name(str(self.player))
        except staff_actions.ActionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        embed = await lookup_player_embed(interaction.guild, name)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await post_staff_log(
            title="Player lookup",
            description=f"Looked up `{name}`",
            colour=BLUE,
            actor=interaction.user,
        )


class GiveKeysModal(discord.ui.Modal, title="Grant mystery keys"):
    player = discord.ui.TextInput(label="Minecraft name", max_length=32)
    amount = discord.ui.TextInput(label="Amount", placeholder="1", default="1", max_length=4)
    key_type = discord.ui.TextInput(
        label="Key type",
        placeholder="mystery | monthly",
        default="mystery",
        max_length=16,
    )
    reason = discord.ui.TextInput(
        label="Reason (required, audited)",
        style=discord.TextStyle.paragraph,
        max_length=120,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        reason_raw = str(self.reason)
        try:
            reason = staff_actions.plain_text(reason_raw, min_len=3, max_len=80, label="Reason")
            n = int(str(self.amount).strip())
            tx = f"tx:discord-{interaction.id}"
            cmd = staff_actions.keys_command(str(self.player), n, str(self.key_type), tx)
            name = staff_actions.minecraft_name(str(self.player))
            kind = str(self.key_type).strip().lower() or "mystery"
        except staff_actions.ActionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except ValueError:
            await interaction.followup.send("Amount must be a whole number.", ephemeral=True)
            return
        try:
            result = await run_rcon(cmd)
            ok = True
            detail = _clip(result)
        except rcon_client.RconError as e:
            ok = False
            detail = str(e)
        colour = BRAND if ok else RED
        embed = discord.Embed(
            title="🔑  Keys grant",
            description=f"**Player:** `{name}`\n**Type:** `{kind}`\n**Amount:** `{n}`\n"
                        f"**Reason:** {reason}\n**Tx:** `{tx}`\n\n```\n{detail}\n```",
            colour=colour,
        )
        footer(embed, interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await post_staff_log(
            title="Keys grant",
            description=f"`{cmd}`\nReason: {reason}\n```\n{detail}\n```",
            colour=colour,
            fields=[("Player", name, True), ("Amount", str(n), True), ("Type", kind, True)],
            actor=interaction.user,
        )


class GiveBoosterModal(discord.ui.Modal, title="Grant booster"):
    player = discord.ui.TextInput(label="Minecraft name", max_length=32)
    kind = discord.ui.TextInput(
        label="Type",
        placeholder="sell | speed | xp",
        default="sell",
        max_length=8,
    )
    percent = discord.ui.TextInput(label="Percent", placeholder="50", default="50", max_length=4)
    minutes = discord.ui.TextInput(label="Minutes", placeholder="30", default="30", max_length=4)
    reason = discord.ui.TextInput(
        label="Reason (required)",
        style=discord.TextStyle.paragraph,
        max_length=120,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            reason = staff_actions.plain_text(str(self.reason), min_len=3, max_len=80, label="Reason")
            pct = int(str(self.percent).strip())
            mins = int(str(self.minutes).strip())
            tx = f"tx:discord-{interaction.id}"
            cmd = staff_actions.booster_command(str(self.player), str(self.kind), pct, mins, tx)
            name = staff_actions.minecraft_name(str(self.player))
            booster = str(self.kind).strip().lower()
        except staff_actions.ActionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except ValueError:
            await interaction.followup.send("Percent and minutes must be whole numbers.", ephemeral=True)
            return
        try:
            result = await run_rcon(cmd)
            ok = True
            detail = _clip(result)
        except rcon_client.RconError as e:
            ok = False
            detail = str(e)
        colour = BRAND if ok else RED
        embed = discord.Embed(
            title="⚡  Booster grant",
            description=(
                f"**Player:** `{name}` · **{booster}** +{pct}% for {mins}m\n"
                f"**Reason:** {reason}\n\n```\n{detail}\n```"
            ),
            colour=colour,
        )
        footer(embed, interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await post_staff_log(
            title="Booster grant",
            description=f"`{cmd}`\nReason: {reason}\n```\n{detail}\n```",
            colour=colour,
            actor=interaction.user,
        )


class StoreRankModal(discord.ui.Modal, title="Apply store rank"):
    player = discord.ui.TextInput(label="Minecraft name", max_length=32)
    rank = discord.ui.TextInput(
        label="Rank",
        placeholder="islander | surfer | captain | tycoon | mogul",
        max_length=16,
    )
    reason = discord.ui.TextInput(
        label="Reason / Tebex order id",
        style=discord.TextStyle.paragraph,
        max_length=120,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            reason = staff_actions.plain_text(str(self.reason), min_len=3, max_len=80, label="Reason")
            tx = f"tx:discord-{interaction.id}"
            cmd = staff_actions.store_command(str(self.player), str(self.rank), tx)
            name = staff_actions.minecraft_name(str(self.player))
            rank = str(self.rank).strip().lower()
        except staff_actions.ActionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        try:
            result = await run_rcon(cmd)
            ok = True
            detail = _clip(result)
        except rcon_client.RconError as e:
            ok = False
            detail = str(e)
        colour = GOLD if ok else RED
        embed = discord.Embed(
            title="👑  Store rank",
            description=f"**Player:** `{name}` → **{rank}**\n**Reason:** {reason}\n\n```\n{detail}\n```",
            colour=colour,
        )
        footer(embed, interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await post_staff_log(
            title="Store rank",
            description=f"`{cmd}`\nReason: {reason}\n```\n{detail}\n```",
            colour=colour,
            actor=interaction.user,
        )


class GiveXpModal(discord.ui.Modal, title="Grant Tycoon XP"):
    player = discord.ui.TextInput(label="Minecraft name", max_length=32)
    amount = discord.ui.TextInput(label="XP amount", placeholder="1000", max_length=9)
    reason = discord.ui.TextInput(
        label="Reason (required, audited)",
        style=discord.TextStyle.paragraph,
        max_length=120,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            reason = staff_actions.plain_text(str(self.reason), min_len=3, max_len=80, label="Reason")
            amount = int(str(self.amount).strip())
            cmd = staff_actions.xp_command(str(self.player), amount)
            name = staff_actions.minecraft_name(str(self.player))
        except staff_actions.ActionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except ValueError:
            await interaction.followup.send("XP must be a whole number.", ephemeral=True)
            return
        await finish_command(
            interaction,
            title="✨  Tycoon XP",
            command=cmd,
            summary=f"**Player:** `{name}` · **XP:** `{amount}`\n**Reason:** {reason}",
        )


class CreditVoteModal(discord.ui.Modal, title="Credit a vote"):
    player = discord.ui.TextInput(label="Minecraft name", max_length=32)
    reason = discord.ui.TextInput(
        label="Reason (required, audited)",
        style=discord.TextStyle.paragraph,
        max_length=120,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            reason = staff_actions.plain_text(str(self.reason), min_len=3, max_len=80, label="Reason")
            cmd = staff_actions.vote_command(str(self.player))
            name = staff_actions.minecraft_name(str(self.player))
        except staff_actions.ActionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        await finish_command(
            interaction,
            title="🗳️  Vote credit",
            command=cmd,
            summary=(
                f"**Player:** `{name}`\n**Reason:** {reason}\n"
                "Each credit counts as one vote for today's Daily Shop."
            ),
        )


class GivePetModal(discord.ui.Modal, title="Give a pet"):
    player = discord.ui.TextInput(label="Minecraft name", max_length=32)
    pet = discord.ui.TextInput(
        label="Pet type",
        placeholder="hermit_crab",
        max_length=32,
    )
    level = discord.ui.TextInput(label="Level", placeholder="1", default="1", max_length=2)
    reason = discord.ui.TextInput(
        label="Reason (required, audited)",
        style=discord.TextStyle.paragraph,
        max_length=120,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            lvl = int(str(self.level).strip())
            tx = f"tx:discord-{interaction.id}"
            cmd = staff_actions.pet_command(str(self.player), str(self.pet), lvl, str(self.reason), tx)
            name = staff_actions.minecraft_name(str(self.player))
            reason = staff_actions.plain_text(str(self.reason), min_len=3, max_len=80, label="Reason")
        except staff_actions.ActionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        except ValueError:
            await interaction.followup.send("Level must be a whole number.", ephemeral=True)
            return
        await finish_command(
            interaction,
            title="🐾  Pet grant",
            command=cmd,
            summary=f"**Player:** `{name}` · **Pet:** `{str(self.pet).strip()}` level {lvl}\n**Reason:** {reason}",
            colour_ok=GOLD,
        )


class MoveModal(discord.ui.Modal, title="Move player"):
    player = discord.ui.TextInput(label="Minecraft name", max_length=32)
    server = discord.ui.TextInput(label="Server", placeholder="hub | skyblock | boss", max_length=16)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            cmd = staff_actions.move_command(str(self.player), str(self.server))
            name = staff_actions.minecraft_name(str(self.player))
        except staff_actions.ActionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        await finish_command(
            interaction,
            title="🚀  Move player",
            command=cmd,
            summary=f"**Player:** `{name}` → `{str(self.server).strip().lower()}`",
        )


class KickModal(discord.ui.Modal, title="Kick player"):
    player = discord.ui.TextInput(label="Minecraft name", max_length=32)
    reason = discord.ui.TextInput(label="Reason shown to the player", max_length=80)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            cmd = staff_actions.kick_command(str(self.player), str(self.reason))
            name = staff_actions.minecraft_name(str(self.player))
            reason = staff_actions.plain_text(str(self.reason), min_len=3, max_len=80, label="Kick reason")
        except staff_actions.ActionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        await finish_command(
            interaction,
            title="👢  Kick",
            command=cmd,
            summary=f"**Player:** `{name}`\n**Reason:** {reason}",
            colour_ok=RED,
        )


class AnnounceModal(discord.ui.Modal, title="Server announcement"):
    message = discord.ui.TextInput(
        label="Message",
        style=discord.TextStyle.paragraph,
        max_length=180,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            cmd = staff_actions.announce_command(str(self.message))
        except staff_actions.ActionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        await finish_command(
            interaction,
            title="📣  Announcement",
            command=cmd,
            summary="Sent with `/say` on the skyblock console.",
        )


async def finish_command(
    interaction: discord.Interaction,
    *,
    title: str,
    command: str,
    summary: str,
    colour_ok: int = BRAND,
) -> None:
    try:
        result = await run_rcon(command)
        ok = True
        detail = _clip(result)
    except rcon_client.RconError as e:
        ok = False
        detail = str(e)
    colour = colour_ok if ok else RED
    embed = discord.Embed(
        title=title,
        description=f"{summary}\n\n```\n{command}\n```\n```\n{detail}\n```",
        colour=colour,
    )
    footer(embed, interaction.guild)
    await interaction.followup.send(embed=embed, ephemeral=True)
    await post_staff_log(
        title=title,
        description=f"{summary}\n`{command}`\n```\n{detail}\n```",
        colour=colour,
        actor=interaction.user,
    )


# ---------- embeds / data ----------
def ac_overview_embed(guild: discord.Guild | None) -> discord.Embed:
    ch = f"<#{AC_LOG_CHANNEL_ID}>" if AC_LOG_CHANNEL_ID.isdigit() else "`AC_LOG_CHANNEL_ID` unset"
    embed = discord.Embed(
        title="🎣  Fishing tension AC",
        description=(
            "Soft detector for click bots on the tension bar. Detections post to the "
            f"log channel ({ch}) with samples, perfect-rate, offset stddev, ping and client.\n\n"
            "No automatic bans — staff review the log, then act in-game or via Economy tools."
        ),
        colour=PINK,
    )
    embed.add_field(name="Signal", value="Low stddev **and** high perfect rate", inline=False)
    embed.add_field(name="Ignored", value="Auto-reel rods · AFK timeouts", inline=True)
    embed.add_field(name="Bedrock", value="Wider stddev tolerance", inline=True)
    footer(embed, guild)
    return embed


def players_overview_embed(guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title="👤  Players",
        description=(
            "Profile runs `/balance` and LuckPerms `lp user <name> info` over RCON. "
            "Balance only answers for players who are online right now."
        ),
        colour=BLUE,
    )
    footer(embed, guild)
    return embed


def economy_overview_embed(guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title="💰  Economy grants",
        description=(
            "Server owner only. Keys, boosters, pets and store ranks use a Discord transaction id "
            "(`tx:discord-<interaction>`) so the same click cannot pay out twice.\n\n"
            "Tycoon XP and vote credits are not idempotent: each confirm applies once."
        ),
        colour=GOLD,
    )
    footer(embed, guild)
    return embed


def events_overview_embed(guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title="🎉  Events",
        description=(
            "Hand-start a rotation event on skyblock: Gen Overload, Sell Frenzy or Lucky Drops. "
            "Stop only ends the hand-started one; the daily rotation continues."
        ),
        colour=TEAL,
    )
    footer(embed, guild)
    return embed


def tools_overview_embed(guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title="🛠  Staff tools",
        description=(
            "**Slash commands**\n"
            "• `/manage` — post this Control Center\n"
            "• `/lookup` `/move` `/kick` `/announce`\n"
            "• `/givekeys` `/givexp`\n"
            "• `/serverstatus` `/acrecent`\n"
            "• `/play` — public join info\n\n"
            f"**Staff audit webhook:** {'configured' if STAFF_LOG_WEBHOOK.startswith('https://') else 'missing `STAFF_LOG_WEBHOOK`'}"
        ),
        colour=SLATE,
    )
    footer(embed, guild)
    return embed


def moderation_overview_embed(guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title="⛔  Moderation",
        description=(
            "Kick uses the vanilla kick (the player must be online on this backend). "
            "Announce sends `/say` to everyone on the skyblock server."
        ),
        colour=RED,
    )
    footer(embed, guild)
    return embed


def play_embed(guild: discord.Guild | None) -> discord.Embed:
    embed = discord.Embed(
        title="🌴  Play Tropical Tycoon",
        description=(
            f"**Java & Bedrock:** `{PLAY_ADDRESS}`\n"
            f"**Store:** {STORE_URL}\n\n"
            "Bedrock players join the same address. Pick **Java** or **Bedrock** in Discord "
            "to get the right role."
        ),
        colour=BRAND,
    )
    footer(embed, guild)
    return embed


async def lookup_player_embed(guild: discord.Guild | None, name: str) -> discord.Embed:
    balance_cmd, perms_cmd = staff_actions.profile_commands(name)
    lines: list[str] = []
    colour = BRAND
    for cmd in (balance_cmd, perms_cmd):
        try:
            result = await run_rcon(cmd)
            lines.append(f"$ {cmd}\n{_clip(result, 700)}")
        except rcon_client.RconError as e:
            lines.append(f"$ {cmd}\n{e}")
            colour = GOLD
    embed = discord.Embed(
        title=f"👤  Lookup · {name}",
        description="```\n" + "\n\n".join(lines) + "\n```",
        colour=colour,
    )
    embed.add_field(
        name="Note",
        value="`/balance` only works while the player is online on this server.",
        inline=False,
    )
    footer(embed, guild)
    return embed


async def online_embed(guild: discord.Guild | None) -> discord.Embed:
    try:
        result = await run_rcon("list")
        body = _clip(result, 1200)
        colour = BRAND
    except rcon_client.RconError as e:
        body = str(e)
        colour = RED
    embed = discord.Embed(title="📋  Online players", description=f"```\n{body}\n```", colour=colour)
    footer(embed, guild)
    return embed


async def network_status_embed(guild: discord.Guild | None) -> discord.Embed:
    lines: list[str] = []
    colour = BRAND
    for cmd in ("list", "gens network"):
        try:
            result = await run_rcon(cmd)
            lines.append(f"$ {cmd}\n{_clip(result, 500)}")
        except rcon_client.RconError as e:
            lines.append(f"$ {cmd}\n{e}")
            colour = GOLD
    embed = discord.Embed(
        title="🌐  Network",
        description="```\n" + "\n\n".join(lines) + "\n```",
        colour=colour,
    )
    footer(embed, guild)
    return embed


async def fetch_ac_recent(
    client: discord.Client, guild: discord.Guild | None
) -> discord.Embed:
    if not AC_LOG_CHANNEL_ID.isdigit():
        return discord.Embed(
            title="🚩  Recent AC flags",
            description=(
                "Set `AC_LOG_CHANNEL_ID` in `server/discord/.env` to the fishing AC "
                "log channel snowflake so I can read recent embeds."
            ),
            colour=GOLD,
        )
    channel = client.get_channel(int(AC_LOG_CHANNEL_ID))
    if channel is None and guild is not None:
        channel = guild.get_channel(int(AC_LOG_CHANNEL_ID))
    if not isinstance(channel, discord.TextChannel):
        return discord.Embed(
            title="🚩  Recent AC flags",
            description="AC log channel not found (check id + bot access).",
            colour=RED,
        )
    lines: list[str] = []
    async for message in channel.history(limit=30):
        for emb in message.embeds:
            title = emb.title or "embed"
            if "TENSION" not in title.upper() and "FISH" not in title.upper() and "AC" not in title.upper():
                if emb.colour is None:
                    continue
            when = message.created_at.strftime("%Y-%m-%d %H:%M")
            desc = (emb.description or "").replace("\n", " · ")
            lines.append(f"**{when} UTC** — {title}\n{desc[:220]}")
            if len(lines) >= 8:
                break
        if len(lines) >= 8:
            break
    if not lines:
        desc = "No recent tension AC embeds in that channel yet."
    else:
        desc = "\n\n".join(lines)
    embed = discord.Embed(title="🚩  Recent fishing AC flags", description=desc[:4000], colour=RED)
    embed.add_field(name="Channel", value=channel.mention, inline=False)
    footer(embed, guild)
    return embed


# ---------- registration ----------
def setup(bot: commands.Bot) -> None:
    if getattr(bot, "_tt_staff_manage_loaded", False):
        return
    bot._tt_staff_manage_loaded = True  # type: ignore[attr-defined]

    # No default_permissions: Discord Admin-only hides the slash from Owner/Guide in the picker.
    # Role checks below enforce Guide+ at runtime.
    @bot.tree.command(name="manage", description="Post the Staff Control Center (server owner only)")
    async def manage(interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        if interaction.channel is None or not hasattr(interaction.channel, "send"):
            await interaction.response.send_message(
                "Use this in a text channel.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Posting Staff Control Center…", ephemeral=True
        )
        await interaction.channel.send(embed=hub_embed(interaction.guild), view=StaffHubView())
        await post_staff_log(
            title="Staff Control Center posted",
            description=f"Panel posted in {interaction.channel.mention}",
            colour=BRAND,
            actor=interaction.user,
        )

    @bot.tree.command(name="lookup", description="Look up a Minecraft player (owner only)")
    @app_commands.describe(player="Minecraft name")
    async def lookup(interaction: discord.Interaction, player: str) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            name = staff_actions.minecraft_name(player)
        except staff_actions.ActionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        embed = await lookup_player_embed(interaction.guild, name)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="play", description="How to join Tropical Tycoon")
    async def play(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=play_embed(interaction.guild))

    @bot.tree.command(name="givexp", description="Grant Tycoon XP (owner only)")
    async def givexp(interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(GiveXpModal())

    @bot.tree.command(name="move", description="Send a player to hub, skyblock or boss (owner only)")
    async def move(interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(MoveModal())

    @bot.tree.command(name="kick", description="Kick an online player (owner only)")
    async def kick(interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(KickModal())

    @bot.tree.command(name="announce", description="Broadcast a /say message (owner only)")
    async def announce(interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(AnnounceModal())

    @bot.tree.command(name="givekeys", description="Grant mystery/monthly keys (owner only)")
    async def givekeys(interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.send_modal(GiveKeysModal())

    @bot.tree.command(name="serverstatus", description="Online players and RCON health (owner only)")
    async def serverstatus(interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        embed = await network_status_embed(interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name="acrecent", description="Recent fishing tension AC embeds (owner only)")
    async def acrecent(interaction: discord.Interaction) -> None:
        if not can_manage(interaction.user, interaction.guild):
            await interaction.response.send_message("Server owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        embed = await fetch_ac_recent(interaction.client, interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # Persist the hub select across bot restarts.
    bot.add_view(StaffHubView())
    print(
        "Staff Control Center commands loaded: "
        "/manage /lookup /play /givekeys /givexp /move /kick /announce /serverstatus /acrecent",
        flush=True,
    )


async def notify_connected(synced_names: list[str] | None = None) -> None:
    """One-shot audit ping when the bot comes online (called from ticket_bot.on_ready)."""
    names = ", ".join(f"`/{n}`" for n in (synced_names or [])) or "*(sync listed none — pull/restart?)*"
    owner_note = (
        f"Owner allowlist: {', '.join(str(i) for i in sorted(OWNER_IDS))}"
        if OWNER_IDS
        else "Owner allowlist: Discord **server owner** only"
    )
    await post_staff_log(
        title="Staff management log connected",
        description=(
            "Audits from `/manage`, economy grants, events and lookups post here.\n"
            f"{owner_note}\n\n"
            f"**Synced slash commands:** {names}\n\n"
            "If `/manage` is missing above, the bot did not load `staff_manage.py` — "
            "pull `main` on Wispbyte and restart."
        ),
        colour=BRAND,
    )

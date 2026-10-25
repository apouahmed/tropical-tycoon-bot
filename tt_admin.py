"""
Tropical Tycoon Discord bot: info extension (read-only, no actions on the server).

Adds to ticket_bot.py:
  - Account linking:      /link <code>, /unlink
  - Store rank roles:     Islander, Surfer, Captain, Tycoon, Mogul (auto-synced)
  - Supporter channels:   #supporter-lounge (Islander+), #vip-lounge (Tycoon+)  -> /setupsupporters
  - /manage player <ign>  detailed player info (Owner/Admin, only in the management channel)
  - /manage linked <member>  which Minecraft account a Discord member is linked to
  - Live status panel:    /panelstatus (edited every 30 s, pings Admin on problems)

Load it from ticket_bot.py inside setup_hook():
    await bot.load_extension("tt_admin")

HOW BOT AND SERVER SHARE DATA
The bot only READS from the shared MariaDB (plus writing its own link rows).
The plugin writes:
  - discord_link_codes   codes from in-game /link
  - player_store_ranks   current store rank per player
  - player_overview      one row per player with a JSON map of info fields
  - server_status        live stats per server (every 15 s)
The schema is in SCHEMA below. The bot creates the tables if they don't exist;
the plugin must use exactly the same definitions.

server_status.extra (JSON) on the main server may contain:
  money_supply, money_in_today, money_out_today, peak_today,
  heavy_chunks: [{world, x, z, entities, tile_entities, owner}]   (top 5)
  top_players:  [{ign, value}]                                   (top 5 by island value)

.env (never commit real values):
  DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
  MANAGEMENT_CHANNEL=managmentchannel
  STATUS_SERVERS=proxy,hub,main
  GUILD_ID=            (optional, else the first guild)
"""

import os
import json
import time
import asyncio
import datetime

import aiomysql
import discord
from discord import app_commands
from discord.ext import commands, tasks

# ---------- config ----------
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "")
MANAGEMENT_CHANNEL = os.getenv("MANAGEMENT_CHANNEL", "managmentchannel").lower()
STATUS_SERVERS = [s.strip() for s in os.getenv("STATUS_SERVERS", "proxy,hub,main").split(",") if s.strip()]
GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)

_HERE = os.path.dirname(os.path.abspath(__file__))
PANEL_FILE = os.path.join(_HERE, "status_panel.json")

OWNER_ROLE = "Owner"
ADMIN_ROLE = "Admin"
STAFF_ROLES = ("Guide", "Mod", ADMIN_ROLE, OWNER_ROLE)

# Store ranks, lowest -> highest (name, colour)
STORE_RANKS = (
    ("Islander", 0xE9D58A),
    ("Surfer", 0x4FC3F7),
    ("Captain", 0x1E88E5),
    ("Tycoon", 0xFFB300),
    ("Mogul", 0xFF6D00),
)
RANK_NAMES = [n for n, _ in STORE_RANKS]
SUPPORTER_CATEGORY = "SUPPORTERS"
SUPPORTER_CHANNEL = "supporter-lounge"
VIP_CHANNEL = "vip-lounge"
SUPPORTER_ACCESS = RANK_NAMES                 # Islander .. Mogul
VIP_ACCESS = ("Tycoon", "Mogul")

STALE_AFTER = 60             # status row older than this = offline
ALERT_COOLDOWN = 600         # 10 min between pings per server

GREEN, ORANGE, RED = 0x22C55E, 0xF59E0B, 0xEF4444
BRAND = 0x2EE6A6

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS discord_link_codes (
        code VARCHAR(6) PRIMARY KEY,
        uuid CHAR(36) NOT NULL,
        ign VARCHAR(32) NOT NULL,
        expires_at DATETIME NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS discord_links (
        discord_id BIGINT PRIMARY KEY,
        uuid CHAR(36) NOT NULL UNIQUE,
        ign VARCHAR(32) NOT NULL,
        linked_at DATETIME NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS player_store_ranks (
        uuid CHAR(36) PRIMARY KEY,
        store_rank VARCHAR(16) NULL,
        updated_at DATETIME NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS player_overview (
        uuid CHAR(36) PRIMARY KEY,
        ign VARCHAR(32) NOT NULL,
        fields LONGTEXT NOT NULL,
        updated_at DATETIME NOT NULL,
        INDEX idx_ign (ign)
    )""",
    """CREATE TABLE IF NOT EXISTS server_status (
        server_name VARCHAR(16) PRIMARY KEY,
        tps_1m DOUBLE, tps_5m DOUBLE, mspt DOUBLE,
        players_online INT, players_java INT, players_bedrock INT,
        ram_used_mb INT, ram_max_mb INT, cpu_percent DOUBLE,
        loaded_chunks INT, entities INT, tile_entities INT,
        uptime_seconds BIGINT,
        geyser_ok TINYINT NULL, gme_link_ok TINYINT NULL, pack_ok TINYINT NULL,
        db_latency_ms INT NULL,
        last_error TEXT NULL,
        extra LONGTEXT NULL,
        updated_at DATETIME NOT NULL
    )""",
)


# ---------- helpers ----------
def is_admin(member):
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    return any(r.name in (OWNER_ROLE, ADMIN_ROLE) for r in member.roles)


def in_management_channel(channel):
    return MANAGEMENT_CHANNEL in (getattr(channel, "name", "") or "").lower()


def fmt_num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "–"
    for unit, s in ((1e15, "Q"), (1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= unit:
            return f"{x / unit:.2f}{s}"
    return f"{x:.0f}"


def fmt_uptime(seconds):
    if not seconds:
        return "–"
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    return f"{d}d {h}h {m}m" if d else f"{h}h {m}m"


def check_mark(v):
    if v is None:
        return "–"
    return "✅" if int(v) == 1 else "❌"


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


class RefreshView(discord.ui.View):
    """Persistent refresh button under the status panel."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary,
                       custom_id="tt:status:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("Owner/Admin only.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.cog.update_panel()


# ---------- cog ----------
class TTAdmin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool = None
        self.last_alert = {}
        self.refresh_view = RefreshView(self)

    # ----- lifecycle -----
    async def cog_load(self):
        if not (DB_USER and DB_NAME):
            print("[tt_admin] DB_USER / DB_NAME not set: linking, info and panel are disabled.", flush=True)
            return
        self.pool = await aiomysql.create_pool(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
                                               db=DB_NAME, autocommit=True, charset="utf8mb4", maxsize=5)
        for stmt in SCHEMA:
            await self.execute(stmt)
        self.bot.add_view(self.refresh_view)
        self.panel_loop.start()
        self.rank_loop.start()
        print("[tt_admin] loaded (DB connected).", flush=True)

    async def cog_unload(self):
        self.panel_loop.cancel()
        self.rank_loop.cancel()
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    # ----- db -----
    async def fetchall(self, sql, args=None):
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, args)
                return await cur.fetchall()

    async def fetchone(self, sql, args=None):
        rows = await self.fetchall(sql, args)
        return rows[0] if rows else None

    async def execute(self, sql, args=None):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, args)

    def guild(self):
        if GUILD_ID:
            return self.bot.get_guild(GUILD_ID)
        return self.bot.guilds[0] if self.bot.guilds else None

    async def guard(self, interaction, admin=True):
        if not self.pool:
            await interaction.response.send_message("Database not configured.", ephemeral=True)
            return False
        if admin and not is_admin(interaction.user):
            await interaction.response.send_message("Owner/Admin only.", ephemeral=True)
            return False
        if admin and not in_management_channel(interaction.channel):
            await interaction.response.send_message(f"Only in #{MANAGEMENT_CHANNEL}.", ephemeral=True)
            return False
        return True

    # ----- linking -----
    @app_commands.command(name="link", description="Link your Discord to your Minecraft account (use /link in-game first)")
    @app_commands.describe(code="The 6-digit code from /link in-game")
    async def link(self, interaction: discord.Interaction, code: str):
        if not await self.guard(interaction, admin=False):
            return
        code = code.strip()
        if await self.fetchone("SELECT 1 FROM discord_links WHERE discord_id=%s", (interaction.user.id,)):
            await interaction.response.send_message("Your Discord is already linked. Use `/unlink` first.",
                                                    ephemeral=True)
            return
        row = await self.fetchone(
            "SELECT uuid, ign FROM discord_link_codes WHERE code=%s AND expires_at > UTC_TIMESTAMP()", (code,))
        if not row:
            await interaction.response.send_message("Invalid or expired code. Run `/link` in-game again.",
                                                    ephemeral=True)
            return
        if await self.fetchone("SELECT 1 FROM discord_links WHERE uuid=%s", (row["uuid"],)):
            await interaction.response.send_message("That Minecraft account is already linked to another Discord.",
                                                    ephemeral=True)
            return
        await self.execute("INSERT INTO discord_links (discord_id, uuid, ign, linked_at) "
                           "VALUES (%s, %s, %s, UTC_TIMESTAMP())", (interaction.user.id, row["uuid"], row["ign"]))
        await self.execute("DELETE FROM discord_link_codes WHERE code=%s", (code,))
        await self.sync_member(interaction.user.id)
        await interaction.response.send_message(f"✅ Linked to **{row['ign']}**. Your rank role is synced.",
                                                ephemeral=True)

    @app_commands.command(name="unlink", description="Unlink your Discord from your Minecraft account")
    async def unlink(self, interaction: discord.Interaction):
        if not await self.guard(interaction, admin=False):
            return
        await self.execute("DELETE FROM discord_links WHERE discord_id=%s", (interaction.user.id,))
        await self.apply_rank_role(interaction.user.id, None)
        await interaction.response.send_message("Unlinked. Rank roles removed.", ephemeral=True)

    # ----- rank roles -----
    async def apply_rank_role(self, discord_id, rank):
        guild = self.guild()
        if not guild:
            return
        member = guild.get_member(discord_id)
        if member is None:
            try:
                member = await guild.fetch_member(discord_id)
            except discord.HTTPException:
                return
        wanted = discord.utils.get(guild.roles, name=rank) if rank in RANK_NAMES else None
        remove = [r for r in member.roles if r.name in RANK_NAMES and r != wanted]
        try:
            if remove:
                await member.remove_roles(*remove, reason="store rank sync")
            if wanted and wanted not in member.roles:
                await member.add_roles(wanted, reason="store rank sync")
        except discord.Forbidden:
            print("[tt_admin] Missing permission to manage rank roles (move the bot role higher).", flush=True)

    async def sync_member(self, discord_id):
        row = await self.fetchone(
            "SELECT r.store_rank FROM discord_links l LEFT JOIN player_store_ranks r ON r.uuid=l.uuid "
            "WHERE l.discord_id=%s", (discord_id,))
        await self.apply_rank_role(discord_id, row["store_rank"] if row else None)

    @tasks.loop(minutes=2)
    async def rank_loop(self):
        try:
            rows = await self.fetchall(
                "SELECT l.discord_id, r.store_rank FROM discord_links l "
                "LEFT JOIN player_store_ranks r ON r.uuid=l.uuid")
            for row in rows:
                await self.apply_rank_role(int(row["discord_id"]), row["store_rank"])
                await asyncio.sleep(0.2)
        except Exception as e:  # keep the loop alive
            print(f"[tt_admin] rank sync failed: {e}", flush=True)

    @rank_loop.before_loop
    async def _before_rank(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="setupsupporters", description="Create store rank roles + supporter channels")
    @app_commands.default_permissions(administrator=True)
    async def setupsupporters(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not is_admin(interaction.user):
            await interaction.response.send_message("Owner/Admin only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        created = []
        roles = {}
        for name, colour in STORE_RANKS:
            role = discord.utils.get(guild.roles, name=name)
            if role is None:
                role = await guild.create_role(name=name, colour=discord.Colour(colour), hoist=True,
                                               reason="store rank role")
                created.append(name)
            roles[name] = role
        staff = [r for r in guild.roles if r.name in STAFF_ROLES]
        category = discord.utils.get(guild.categories, name=SUPPORTER_CATEGORY) or \
            await guild.create_category(SUPPORTER_CATEGORY, reason="supporter channels")

        def overwrites(access):
            ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
            for name in access:
                ow[roles[name]] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                              read_message_history=True)
            for r in staff:
                ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
            return ow

        for ch_name, access, topic in (
                (SUPPORTER_CHANNEL, SUPPORTER_ACCESS, "For Islander, Surfer, Captain and up. Thanks for supporting!"),
                (VIP_CHANNEL, VIP_ACCESS, "Tycoon and Mogul lounge.")):
            ch = discord.utils.find(lambda c: ch_name in c.name.lower(), guild.text_channels)
            if ch is None:
                await guild.create_text_channel(ch_name, category=category, topic=topic,
                                                overwrites=overwrites(access))
                created.append(f"#{ch_name}")
            else:
                await ch.edit(overwrites=overwrites(access), category=category)
        await interaction.followup.send(
            "Done. Created: " + (", ".join(created) if created else "nothing new (permissions updated)") +
            "\nMake sure the bot role is **above** the rank roles.", ephemeral=True)

    # ----- /manage (info only) -----
    manage = app_commands.Group(name="manage", description="Owner/Admin player info (read-only)",
                                default_permissions=discord.Permissions(administrator=True))

    @manage.command(name="player", description="Detailed info about a player")
    async def manage_player(self, interaction: discord.Interaction, ign: str):
        if not await self.guard(interaction):
            return
        await interaction.response.defer(thinking=True)
        row = await self.fetchone(
            "SELECT o.uuid, o.ign, o.fields, o.updated_at, r.store_rank, l.discord_id "
            "FROM player_overview o "
            "LEFT JOIN player_store_ranks r ON r.uuid=o.uuid "
            "LEFT JOIN discord_links l ON l.uuid=o.uuid "
            "WHERE o.ign=%s ORDER BY o.updated_at DESC LIMIT 1", (ign,))
        if not row:
            await interaction.followup.send(f"No data for **{ign}** (never joined, or name changed).")
            return
        try:
            fields = json.loads(row["fields"] or "{}")
        except json.JSONDecodeError:
            fields = {}
        embed = discord.Embed(title=f"Player · {row['ign']}", colour=BRAND, timestamp=utcnow())
        embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{row['uuid']}/64")
        embed.add_field(name="Store rank", value=row["store_rank"] or "–", inline=True)
        embed.add_field(name="Discord", value=f"<@{row['discord_id']}>" if row["discord_id"] else "not linked",
                        inline=True)
        embed.add_field(name="UUID", value=f"`{row['uuid']}`", inline=False)
        for label, value in list(fields.items())[:21]:
            embed.add_field(name=str(label)[:256], value=str(value)[:1024] or "–", inline=True)
        embed.set_footer(text=f"Data from {row['updated_at']:%d-%m-%Y %H:%M} UTC")
        await interaction.followup.send(embed=embed)

    @manage.command(name="linked", description="Which Minecraft account a Discord member is linked to")
    async def manage_linked(self, interaction: discord.Interaction, member: discord.Member):
        if not await self.guard(interaction):
            return
        row = await self.fetchone("SELECT ign, uuid, linked_at FROM discord_links WHERE discord_id=%s", (member.id,))
        if not row:
            await interaction.response.send_message(f"{member.mention} is not linked.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"{member.mention} → **{row['ign']}** (`{row['uuid']}`), linked {row['linked_at']:%d-%m-%Y}.",
            ephemeral=True)

    # ----- status panel -----
    @app_commands.command(name="panelstatus", description="Post the live server status panel here")
    @app_commands.default_permissions(administrator=True)
    async def panelstatus(self, interaction: discord.Interaction):
        if not await self.guard(interaction):
            return
        msg = await interaction.channel.send(embeds=await self.status_embeds(), view=self.refresh_view)
        with open(PANEL_FILE, "w") as f:
            json.dump({"channel_id": msg.channel.id, "message_id": msg.id}, f)
        await interaction.response.send_message("Status panel posted. It updates every 30 seconds.", ephemeral=True)

    async def status_embeds(self):
        rows = {r["server_name"]: r for r in await self.fetchall(
            "SELECT *, TIMESTAMPDIFF(SECOND, updated_at, UTC_TIMESTAMP()) AS age FROM server_status")}
        embeds = []
        total_players = 0
        for name in STATUS_SERVERS:
            r = rows.get(name)
            if not r or (r.get("age") or 0) > STALE_AFTER:
                embeds.append(discord.Embed(title=f"🔴 {name.capitalize()} · OFFLINE", colour=RED,
                                            description="No status update in the last minute."))
                continue
            tps = r.get("tps_1m") or 0
            colour = GREEN if tps >= 19.5 else ORANGE if tps >= 18 else RED
            icon = "🟢" if colour == GREEN else "🟠" if colour == ORANGE else "🔴"
            total_players += r.get("players_online") or 0
            e = discord.Embed(title=f"{icon} {name.capitalize()}", colour=colour)
            e.add_field(name="TPS (1m / 5m)", value=f"{tps:.2f} / {(r.get('tps_5m') or 0):.2f}", inline=True)
            e.add_field(name="MSPT", value=f"{(r.get('mspt') or 0):.1f} ms", inline=True)
            e.add_field(name="Players",
                        value=f"{r.get('players_online') or 0} "
                              f"(☕ {r.get('players_java') or 0} · 📱 {r.get('players_bedrock') or 0})", inline=True)
            e.add_field(name="RAM", value=f"{fmt_num(r.get('ram_used_mb'))} / {fmt_num(r.get('ram_max_mb'))} MB",
                        inline=True)
            e.add_field(name="CPU", value=f"{(r.get('cpu_percent') or 0):.0f}%", inline=True)
            e.add_field(name="Uptime", value=fmt_uptime(r.get("uptime_seconds")), inline=True)
            e.add_field(name="Chunks / entities / tiles",
                        value=f"{fmt_num(r.get('loaded_chunks'))} / {fmt_num(r.get('entities'))} / "
                              f"{fmt_num(r.get('tile_entities'))}", inline=False)
            checks = []
            if r.get("geyser_ok") is not None:
                checks.append(f"Geyser {check_mark(r.get('geyser_ok'))}")
            if r.get("gme_link_ok") is not None:
                checks.append(f"GME link {check_mark(r.get('gme_link_ok'))}")
            if r.get("pack_ok") is not None:
                checks.append(f"Pack {check_mark(r.get('pack_ok'))}")
            if r.get("db_latency_ms") is not None:
                checks.append(f"DB {r.get('db_latency_ms')} ms")
            if checks:
                e.add_field(name="Health", value=" · ".join(checks), inline=False)
            if r.get("last_error"):
                e.add_field(name="Last error", value=f"```{str(r['last_error'])[:900]}```", inline=False)
            embeds.append(e)

        main = rows.get("main")
        extra = {}
        if main and main.get("extra"):
            try:
                extra = json.loads(main["extra"])
            except json.JSONDecodeError:
                extra = {}
        eco = discord.Embed(title="📈 Network & economy", colour=BRAND, timestamp=utcnow())
        eco.add_field(name="Players online", value=str(total_players), inline=True)
        eco.add_field(name="Peak today", value=str(extra.get("peak_today", "–")), inline=True)
        eco.add_field(name="​", value="​", inline=True)
        eco.add_field(name="Money supply", value=fmt_num(extra.get("money_supply")), inline=True)
        eco.add_field(name="Money in today", value=fmt_num(extra.get("money_in_today")), inline=True)
        eco.add_field(name="Money out today", value=fmt_num(extra.get("money_out_today")), inline=True)
        heavy = extra.get("heavy_chunks") or []
        if heavy:
            eco.add_field(name="Heaviest chunks (lag)", value="\n".join(
                f"`{c.get('world')} {c.get('x')},{c.get('z')}` · ents **{c.get('entities')}** · "
                f"tiles **{c.get('tile_entities')}** · {c.get('owner') or '–'}" for c in heavy[:5])[:1024],
                inline=False)
        top = extra.get("top_players") or []
        if top:
            eco.add_field(name="Top islands", value="\n".join(
                f"**{i + 1}.** {p.get('ign')} · {fmt_num(p.get('value'))}" for i, p in enumerate(top[:5])),
                inline=False)
        eco.set_footer(text="Updates every 30 s")
        embeds.append(eco)
        return embeds[:10]

    async def update_panel(self):
        if not self.pool or not os.path.exists(PANEL_FILE):
            return
        try:
            with open(PANEL_FILE) as f:
                ref = json.load(f)
            channel = self.bot.get_channel(ref["channel_id"]) or await self.bot.fetch_channel(ref["channel_id"])
            msg = await channel.fetch_message(ref["message_id"])
            await msg.edit(embeds=await self.status_embeds(), view=self.refresh_view)
            await self.check_alerts(channel)
        except discord.NotFound:
            os.remove(PANEL_FILE)
        except Exception as e:
            print(f"[tt_admin] panel update failed: {e}", flush=True)

    async def check_alerts(self, channel):
        rows = {r["server_name"]: r for r in await self.fetchall(
            "SELECT server_name, tps_1m, TIMESTAMPDIFF(SECOND, updated_at, UTC_TIMESTAMP()) AS age "
            "FROM server_status")}
        admin_role = discord.utils.get(channel.guild.roles, name=ADMIN_ROLE)
        now = time.monotonic()
        for name in STATUS_SERVERS:
            r = rows.get(name)
            problem = None
            if not r or (r.get("age") or 0) > STALE_AFTER:
                problem = "is **offline** (no status update)"
            elif (r.get("tps_1m") or 0) < 18:
                problem = f"has low TPS (**{r['tps_1m']:.1f}**)"
            if problem and now - self.last_alert.get(name, 0) > ALERT_COOLDOWN:
                self.last_alert[name] = now
                mention = admin_role.mention if admin_role else "@Admin"
                await channel.send(f"{mention} ⚠️ **{name.capitalize()}** {problem}.")

    @tasks.loop(seconds=30)
    async def panel_loop(self):
        await self.update_panel()

    @panel_loop.before_loop
    async def _before_panel(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(TTAdmin(bot))

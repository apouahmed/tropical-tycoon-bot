"""
Tropical Tycoon Discord bot — tickets, welcome, rules and staff tools (English).

Admin:
- /setupdiscord  reuse existing channels + apply permissions (confirm=True).
                 create_missing=True only if you want new channels created.
- /setupperms    lock existing info channels (read-only for members, Staff can post)
- /panel         ticket panel
- /manage        Staff Control Center (owner only)
- /postrules /postfaq  post content in the current channel

Owner: /lookup /givekeys /givexp /move /kick /announce /serverstatus /acrecent
Anyone: /rules /play /link /unlink /ranksync
Staff (in a ticket): /add /remove

Privileged intent: Server Members + Message Content in the Developer Portal,
then DISCORD_PRIVILEGED_INTENTS=1.

Start: DISCORD_TOKEN=... python3 ticket_bot.py
"""

import os
import io
import re
import json
import asyncio
import datetime
import certifi
import discord
from discord import app_commands
from discord.ext import commands

import account_link
import staff_manage

def load_env():
    """Load KEY=value from .env / info.inv (fills empty panel vars; non-empty env wins)."""
    here = os.path.dirname(os.path.abspath(__file__))
    roots = {here, os.getcwd()}
    for root in roots:
        for name in (".env", "info.env", "info.inv"):
            path = os.path.join(root, name)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8-sig") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if not key:
                        continue
                    # Empty panel variables must not block the file.
                    if not (os.environ.get(key) or "").strip():
                        os.environ[key] = value


load_env()
TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()
if not TOKEN:
    raise SystemExit(
        "DISCORD_TOKEN is not set. Create a file named .env next to ticket_bot.py with:\n"
        "DISCORD_TOKEN=your_token_here\n"
        "DISCORD_PRIVILEGED_INTENTS=1\n"
        "Or set DISCORD_TOKEN under Startup → Variables. Do not commit the token to Git."
    )
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

# Team roles (highest → lowest). Tickets: Guide+. Info posts: Mod+.
OWNER_ROLE = "Owner"
ADMIN_ROLE = "Admin"
MOD_ROLE = "Mod"
GUIDE_ROLE = "Guide"
MEMBER_ROLE = "Member"
JAVA_ROLE = "Java"
BEDROCK_ROLE = "Bedrock"
STAFF_ROLE_NAMES = (GUIDE_ROLE, MOD_ROLE, ADMIN_ROLE, OWNER_ROLE)
MOD_PLUS_NAMES = (MOD_ROLE, ADMIN_ROLE, OWNER_ROLE)
# Colours for created roles (name, colour, hoist).
ROLE_SPECS = (
    (OWNER_ROLE, discord.Colour.gold(), True),
    (ADMIN_ROLE, discord.Colour.red(), True),
    (MOD_ROLE, discord.Colour.blue(), True),
    (GUIDE_ROLE, discord.Colour.teal(), True),
    ("Mogul", discord.Colour(0xFF6F00), True),
    ("Tycoon", discord.Colour(0x00838F), True),
    ("Captain", discord.Colour(0x1565C0), True),
    ("Surfer", discord.Colour(0x29B6F6), True),
    ("Islander", discord.Colour(0xC9A227), True),
    (MEMBER_ROLE, discord.Colour.dark_grey(), False),
    (JAVA_ROLE, discord.Colour.green(), False),
    (BEDROCK_ROLE, discord.Colour.blurple(), False),
)

TRANSCRIPT_CHANNEL = "ticket-transcripts"
WELCOME_CHANNEL = "welcome"
RULES_CHANNEL = "rules"
FAQ_CHANNEL = "faq"
SUPPORT_CHANNEL = "support"
STORE_CHANNEL = "store"
ANNOUNCEMENTS_CHANNEL = "announcements"
CHANGELOG_CHANNEL = "changelog"
GENERAL_CHANNEL = "general"
MEDIA_CHANNEL = "media"
SUGGESTIONS_CHANNEL = "suggestions"
PLATFORM_CHANNEL = "choose-platform"
STAFF_CHAT_CHANNEL = "staff-chat"

PLAY_ADDRESS = os.getenv("PLAY_ADDRESS", "play.tropicaltycoon.nl")
STORE_URL = os.getenv("STORE_URL", "https://tropicaltycoon.tebex.store/")

# Read-only for @everyone (name substring match, case-insensitive).
LOCK_CHANNEL_NAMES = (
    "announc",
    "rules",
    "faq",
    "welcome",
    "changelog",
    "news",
    "updates",
    "patch",
    "store",
    "support",
    "choose-platform",
)

# Logical name -> Discord name slugs to match (emoji prefixes stripped, e.g. 📜-rules → rules).
CHANNEL_ALIASES = {
    WELCOME_CHANNEL: ("welcome",),
    ANNOUNCEMENTS_CHANNEL: ("announcements",),
    RULES_CHANNEL: ("rules",),
    FAQ_CHANNEL: ("faq",),
    CHANGELOG_CHANNEL: ("changelog",),
    PLATFORM_CHANNEL: ("choose-platform", "platform"),
    GENERAL_CHANNEL: ("general",),
    MEDIA_CHANNEL: ("media", "showcase"),
    SUGGESTIONS_CHANNEL: ("suggestions", "feedback"),
    SUPPORT_CHANNEL: ("support", "tickets", "help"),
    TRANSCRIPT_CHANNEL: ("ticket-transcripts", "transcripts", "ticket-logs"),
    STORE_CHANNEL: ("store", "shop", "tebex"),
    STAFF_CHAT_CHANNEL: ("staff-chat", "staff"),
}

# /setupdiscord: (category label, [(logical_channel, topic, mode), ...])
# mode: readonly | chat | staff | transcripts | platform
# By default only matches existing channels (emoji names OK). Does not create new ones.
DISCORD_LAYOUT = (
    ("INFO", (
        (WELCOME_CHANNEL, "Welcome to Tropical Tycoon — read the rules before you play.", "readonly"),
        (ANNOUNCEMENTS_CHANNEL, "Official server news. Mod+ only.", "readonly"),
        (RULES_CHANNEL, "Official rules. Mod+ only.", "readonly"),
        (FAQ_CHANNEL, "How the server works. Mod+ only.", "readonly"),
        (CHANGELOG_CHANNEL, "Patch notes and season updates. Mod+ only.", "readonly"),
        (PLATFORM_CHANNEL, "Pick Java or Bedrock so we know how you play.", "platform"),
    )),
    ("COMMUNITY", (
        (GENERAL_CHANNEL, "Public chat — keep it friendly and follow the rules.", "chat"),
        (MEDIA_CHANNEL, "Builds, islands, clips and screenshots.", "chat"),
        (SUGGESTIONS_CHANNEL, "Ideas for the server. Be constructive.", "chat"),
    )),
    ("SUPPORT", (
        (SUPPORT_CHANNEL, "Open a ticket below. Do not chat here — use the menu.", "readonly"),
        (TRANSCRIPT_CHANNEL, "Closed ticket logs. Staff only.", "transcripts"),
    )),
    ("STORE", (
        (STORE_CHANNEL, "Ranks, crates and Tebex store info. Mod+ only.", "readonly"),
    )),
    ("STAFF", (
        (STAFF_CHAT_CHANNEL, "Internal staff chat (Guide+).", "staff"),
    )),
)
_HERE = os.path.dirname(os.path.abspath(__file__))
COUNTER_FILE = os.path.join(_HERE, "ticket_counter.json")
BANNER_FILE = os.path.join(_HERE, "ticket_banner.png")

BRAND = 0x2EE6A6
GOLD = 0xFFD166
PINK = 0xFF7EB6
TEAL = 0x7FDBDA

CATEGORIES = {
    "player": ("PLAYER REPORT", "Player Report", "🚨", "Report a player", 0xEF4444),
    "general": ("GENERAL SUPPORT", "General Support", "💬", "General questions and help", 0x3B82F6),
    "bug": ("BUG REPORT SUPPORT", "Bug Report", "🐛", "Report a bug or issue", 0xF59E0B),
    "store": ("STORE SUPPORT", "Store Support", "🛒", "Help with purchases and payments", 0x22C55E),
    "appeal": ("PUNISHMENT APPEAL", "Punishment Appeal", "⚖️", "Appeal a mute or ban", GOLD),
}

intents = discord.Intents.default()
# Welcome needs members; ticket transcripts need message_content.
# Enable both under Privileged Gateway Intents in the Discord Developer Portal,
# then set DISCORD_PRIVILEGED_INTENTS=1 in .env.
if os.getenv("DISCORD_PRIVILEGED_INTENTS", "0") == "1":
    intents.message_content = True
    intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


def next_ticket_number():
    try:
        with open(COUNTER_FILE, "r") as f:
            n = json.load(f).get("count", 0)
    except (FileNotFoundError, json.JSONDecodeError):
        n = 0
    n += 1
    with open(COUNTER_FILE, "w") as f:
        json.dump({"count": n}, f)
    return n


def read_topic(channel):
    data = {}
    for part in (channel.topic or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def write_topic(data):
    return "; ".join(f"{k}={v}" for k, v in data.items())


def role_by_name(guild, name):
    return discord.utils.get(guild.roles, name=name)


def roles_named(guild, names):
    return [r for n in names if (r := role_by_name(guild, n)) is not None]


def is_staff(member):
    """Guide, Mod, Admin, Owner, or Discord administrator."""
    if member.guild_permissions.administrator:
        return True
    names = {r.name for r in member.roles}
    return bool(names & set(STAFF_ROLE_NAMES))


def is_mod_plus(member):
    if member.guild_permissions.administrator:
        return True
    names = {r.name for r in member.roles}
    return bool(names & set(MOD_PLUS_NAMES))


def is_ticket(channel):
    return isinstance(channel, discord.TextChannel) and "owner=" in (channel.topic or "")


def banner_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), BANNER_FILE)


def channel_slug(name: str) -> str:
    """Strip emoji/punctuation so 📜-rules and 📢--announcements → rules / announcements."""
    s = re.sub(r"[^a-z0-9-]+", "-", name.lower())
    return re.sub(r"-+", "-", s).strip("-")


def find_text_channel(guild, contains):
    needle = contains.lower()
    return discord.utils.find(
        lambda c: needle in c.name.lower() or needle in channel_slug(c.name),
        guild.text_channels,
    )


def find_exact_channel(guild, name):
    return discord.utils.get(guild.text_channels, name=name)


def find_layout_channel(guild, logical_name):
    """Find an existing channel for a layout key (exact name, then alias slug match)."""
    exact = find_exact_channel(guild, logical_name)
    if exact is not None:
        return exact
    aliases = CHANNEL_ALIASES.get(logical_name, (logical_name,))
    best = None
    best_score = -1
    for ch in guild.text_channels:
        slug = channel_slug(ch.name)
        for i, alias in enumerate(aliases):
            if slug == alias or slug.endswith("-" + alias) or alias in slug.split("-"):
                # Prefer exact slug / earlier alias / shorter channel name (less noise).
                score = (100 - i) * 10 - len(slug)
                if score > best_score:
                    best = ch
                    best_score = score
    return best


def footer(embed, guild):
    embed.set_footer(text=f"{guild.name} · Tropical Tycoon", icon_url=guild.icon.url if guild.icon else None)
    return embed


def store_embed(guild):
    embed = discord.Embed(
        title="✦  Store",
        description=(
            "Support Tropical Tycoon on Tebex. Ranks, cosmetics, boosters and Monthly Crates.\n"
            "**Money, Gen Cores, gear and Boss Relics are never sold.**\n\n"
            f"[Open the store]({STORE_URL})\n\n"
            f"**Play:** `{PLAY_ADDRESS}` (Java + Bedrock via Geyser)\n"
            f"Pick **Java** or **Bedrock** in #{PLATFORM_CHANNEL} after you join."
        ),
        colour=GOLD,
    )
    return footer(embed, guild)


def platform_embed(guild):
    embed = discord.Embed(
        title="✦  How do you play?",
        description=(
            "Choose **Java** or **Bedrock** so staff know which client you use.\n"
            "You can change this later by clicking again.\n\n"
            f"**Server IP:** `{PLAY_ADDRESS}`"
        ),
        colour=TEAL,
    )
    return footer(embed, guild)


async def ensure_role(guild, name, colour, hoist):
    role = role_by_name(guild, name)
    if role is not None:
        return role, False
    role = await guild.create_role(
        name=name,
        colour=colour,
        hoist=hoist,
        mentionable=name in STAFF_ROLE_NAMES,
        reason="setupdiscord: create role",
    )
    return role, True


async def ensure_category(guild, name, create_missing=False):
    cat = discord.utils.get(guild.categories, name=name)
    if cat is not None:
        return cat, False
    # Fuzzy: "COMMUNITY" matches "💬 | COMMUNITY"
    cat = discord.utils.find(
        lambda c: name.lower() in channel_slug(c.name) or name.lower() in c.name.lower(),
        guild.categories,
    )
    if cat is not None:
        return cat, False
    if not create_missing:
        return None, False
    cat = await guild.create_category(name, reason="setupdiscord: create category")
    return cat, True


async def ensure_text_channel(guild, name, category, topic, create_missing=False):
    ch = find_layout_channel(guild, name)
    if ch is not None:
        return ch, False
    if not create_missing:
        return None, False
    if category is None:
        category, _ = await ensure_category(guild, "INFO", create_missing=True)
    ch = await guild.create_text_channel(
        name, category=category, topic=topic, reason="setupdiscord: create channel")
    return ch, True


async def apply_channel_mode(channel, mode, everyone, staff_roles, mod_roles):
    """Apply permission overwrites for a layout mode."""
    if mode in ("readonly", "platform"):
        await channel.set_permissions(
            everyone,
            view_channel=True,
            send_messages=False,
            send_messages_in_threads=False,
            create_public_threads=False,
            create_private_threads=False,
            add_reactions=True,
            reason="setupdiscord: read-only",
        )
        for role in mod_roles:
            await channel.set_permissions(
                role,
                view_channel=True,
                send_messages=True,
                send_messages_in_threads=True,
                embed_links=True,
                attach_files=True,
                manage_messages=True,
                mention_everyone=True,
                reason="setupdiscord: Mod+ can post",
            )
    elif mode == "chat":
        await channel.set_permissions(
            everyone,
            view_channel=True,
            send_messages=True,
            reason="setupdiscord: member chat",
        )
        for role in staff_roles:
            await channel.set_permissions(
                role,
                view_channel=True,
                send_messages=True,
                manage_messages=True,
                reason="setupdiscord: staff chat powers",
            )
    elif mode == "staff":
        await channel.set_permissions(everyone, view_channel=False, reason="setupdiscord: staff-only")
        for role in staff_roles:
            await channel.set_permissions(
                role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                reason="setupdiscord: Guide+ staff chat",
            )
    elif mode == "transcripts":
        await channel.set_permissions(everyone, view_channel=False, reason="setupdiscord: transcripts hidden")
        for role in mod_roles:
            await channel.set_permissions(
                role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                reason="setupdiscord: Mod+ transcripts",
            )
        guide = role_by_name(channel.guild, GUIDE_ROLE)
        if guide is not None:
            await channel.set_permissions(
                guide, view_channel=True, send_messages=False, read_message_history=True,
                reason="setupdiscord: Guide can read transcripts")


# ---------- official rules (PDF, 2026-10-11) ----------
def rules_embeds(guild):
    icon = guild.icon.url if guild.icon else None
    embeds = []

    intro = discord.Embed(
        title="✦  Tropical Tycoon — Server Rules",
        description=(
            "These rules apply to everyone on Tropical Tycoon, **in-game and on Discord**. "
            "By playing or joining, you agree to them.\n\n"
            "Staff may act on behaviour that breaks the **spirit** of these rules, even if it is not listed "
            "word for word.\n"
            "Rules can change between seasons. **The latest version on Discord always counts.**\n"
            "Not knowing a rule is not an excuse. Unsure? Ask staff before you do it."
        ),
        colour=BRAND,
    )
    if icon:
        intro.set_author(name=guild.name, icon_url=icon)
    footer(intro, guild)
    embeds.append(intro)

    conduct = discord.Embed(
        title="General conduct & chat",
        description="Treat every player and staff member with respect. Chat is shared by everyone, so keep it friendly.",
        colour=GOLD,
    )
    conduct.add_field(name="1. No harassment or toxicity",
                      value="No insults, targeted harassment, bullying or bodyshaming.", inline=False)
    conduct.add_field(name="2. No hate speech",
                      value="No slurs, discrimination or extremist symbols or content.", inline=False)
    conduct.add_field(name="3. No threats",
                      value="This includes threats to hack, DDoS, dox or harm anyone.", inline=False)
    conduct.add_field(name="4. No sexual or NSFW content",
                      value="In chat, names, skins, builds or links.", inline=False)
    conduct.add_field(name="5. No spam or flooding",
                      value="No repeated messages, caps spam or excessive formatting.", inline=False)
    conduct.add_field(name="6. No advertising",
                      value="No links or names of other servers, and no self-promotion without permission.",
                      inline=False)
    conduct.add_field(name="7. No personal information",
                      value="Never share someone's real name, address, photos or other private info.", inline=False)
    conduct.add_field(name="8. No impersonation",
                      value="Don't pretend to be staff, a content creator or another player.", inline=False)
    conduct.add_field(name="9. No malicious links",
                      value="No phishing, IP grabbers or download scams.", inline=False)
    conduct.add_field(name="10. English in public chat",
                      value="Other languages are fine in private messages and island chat.", inline=False)
    conduct.add_field(name="11. Respect staff decisions",
                      value="Disagree? Open a ticket here instead of arguing in chat.", inline=False)
    footer(conduct, guild)
    embeds.append(conduct)

    fair = discord.Embed(
        title="Fair play",
        description="Everyone progresses through the same gens, eras and bosses. Anything that skips that unfairly is not allowed.",
        colour=PINK,
    )
    fair.add_field(name="1. No cheats or hacked clients",
                   value="Fly, killaura, x-ray, reach, ESP, auto-pathing mods (e.g. Baritone) and similar.",
                   inline=False)
    fair.add_field(name="2. No macros or autoclickers",
                   value="No recorded inputs (e.g. TinyTask), auto-farming, auto-fishing, hold-to-click mice or scripts that play for you.",
                   inline=False)
    fair.add_field(name="3. No duping or exploiting",
                   value="Using or attempting to dupe items, money, keys or pets is a serious offence.",
                   inline=False)
    fair.add_field(name="4. Report bugs, don't abuse them",
                   value="Found a bug that gives an advantage? Open a **Bug Report**. Reporters can get a reward; abusers get punished.",
                   inline=False)
    fair.add_field(name="5. Allowed client mods",
                   value="Performance and visual mods such as Sodium, Iris, OptiFine, minimaps **without entity radar**, and resource packs that don't give an advantage. Unsure? Ask staff first.",
                   inline=False)
    fair.add_field(name="6. Alts",
                   value="Alts are allowed, for example as an AFK island member to keep your gens running. An alt may **never** be used to break rules, dodge a punishment or farm rewards that are meant once per player (starter gens, votes, missions).",
                   inline=False)
    fair.add_field(name="7. No ban evasion",
                   value="Joining on another account while punished leads to a permanent ban on all accounts.",
                   inline=False)
    fair.add_field(name="8. No VPN abuse",
                   value="Using a VPN or proxy to dodge bans or limits is ban evasion.", inline=False)
    footer(fair, guild)
    embeds.append(fair)

    island = discord.Embed(
        title="Islands, trading & economy",
        description="Your island and your gens are yours. These rules keep co-op and trading fair.",
        colour=TEAL,
    )
    island.add_field(name="Islands & co-op",
                     value=(
                         "**1. Invite at your own risk.** Who you let on your island is your responsibility. Use roles (Member, Visitor) to limit permissions.\n"
                         "**2. Kicking is allowed, stealing is not.** Owners may kick members. Gens, collectors and catalysts return to their owner automatically; taking or destroying someone else's items is stealing or griefing.\n"
                         "**3. No griefing.** Don't break, move or ruin builds or items of islands you visit or share.\n"
                         "**4. No luring or trapping.** Don't trick players into traps or into giving up items."
                     ),
                     inline=False)
    island.add_field(name="Trading & scams",
                     value=(
                         "**5. Use `/ah` or `/trade`.** Both are logged. Trades outside these systems are at your own risk.\n"
                         "**6. No scamming.** Lying about a deal, not paying or switching items is a bannable offence. Staff can't always refund scams.\n"
                         "**7. No real-money trading (RMT).** Selling or buying items, money, pets or accounts for real money or items on other servers/games is not allowed.\n"
                         "**8. No account sharing or selling.** You are responsible for everything done on your account."
                     ),
                     inline=False)
    island.add_field(name="AFK & gens",
                     value=(
                         "**9. AFK is allowed, AFK-farming is not.** Standing AFK on your island to keep gens running is fine. Using macros, auto-fishing or auto-farming while AFK is not.\n"
                         "**10. No lag machines.** Don't build anything meant to lag the server, such as large redstone or item-drop setups."
                     ),
                     inline=False)
    island.add_field(name="Store & refunds",
                     value=(
                         "**11. Store issues go via a Store Support ticket** with your Tebex Order ID. Never chargeback: chargebacks lead to a permanent ban and removal of the bought items, wherever they ended up.\n"
                         "**12. Refunds for lost items** (crash, rollback, bug) need proof: a screenshot, clip or the time it happened. Fake claims count as lying to staff."
                     ),
                     inline=False)
    footer(island, guild)
    embeds.append(island)

    extra = discord.Embed(
        title="Names, skins, builds & Discord",
        colour=GOLD,
    )
    extra.add_field(name="What others see of you",
                    value=(
                        "**1.** No inappropriate usernames, nicknames or island names.\n"
                        "**2.** No inappropriate skins or capes (nudity, sexual content, gore, hate or extremist/political symbols).\n"
                        "**3.** No inappropriate builds, signs, item names, pet names or holograms.\n"
                        "**4. Asked to change it? Do it.** You'll be banned until you change it."
                    ),
                    inline=False)
    extra.add_field(name="Discord",
                    value=(
                        "All chat rules above also apply here, plus:\n"
                        "**1.** Use the right channels (questions, bugs, suggestions).\n"
                        "**2.** Tickets are for support. One ticket per issue, include your IGN.\n"
                        "**3.** Be patient. Don't ping staff for a faster reply.\n"
                        "**4.** No drama about punishments in public. Use a **Punishment Appeal** ticket.\n"
                        "**5.** No DM advertising or scams to members.\n"
                        "**6.** Voice: no earrape, soundboards or music bots without permission; don't record others without consent.\n"
                        "**7.** Follow Discord's Terms of Service. You must meet Discord's minimum age."
                    ),
                    inline=False)
    footer(extra, guild)
    embeds.append(extra)

    punish = discord.Embed(
        title="Punishments",
        description=(
            "Punishments follow this table and go up with each repeat. Severe cases can skip straight "
            "to a higher step. Staff consider intent, context and history.\n"
            "A first-time AFK-farming ban can be lifted on appeal if the player is honest about it."
        ),
        colour=PINK,
    )
    rows = [
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
    ]
    for name, value in rows[:12]:
        punish.add_field(name=name, value=value, inline=False)
    footer(punish, guild)
    embeds.append(punish)

    punish2 = discord.Embed(title="Punishments (continued)", colour=PINK)
    for name, value in rows[12:]:
        punish2.add_field(name=name, value=value, inline=False)
    footer(punish2, guild)
    embeds.append(punish2)

    report = discord.Embed(
        title="Reporting & appeals",
        description="See someone break a rule? Report it with proof; don't take matters into your own hands.",
        colour=BRAND,
    )
    report.add_field(name="1. Report",
                     value="In-game `/report`, or open a **Player Report** ticket with a clip or screenshot.",
                     inline=False)
    report.add_field(name="2. Appeal",
                     value="Open a **Punishment Appeal** ticket. Be honest: lying in an appeal makes it worse.",
                     inline=False)
    report.add_field(name="3. One appeal per punishment",
                     value="Opening repeated appeals for the same punishment can extend it.", inline=False)
    report.add_field(name="4. Punishment details stay private",
                     value="Staff don't share proof or punishments of other players.", inline=False)
    report.add_field(name="5. Staff have the final say",
                     value="In situations these rules don't cover, staff decide what is fair.", inline=False)
    footer(report, guild)
    embeds.append(report)
    return embeds


def _faq(guild, title, description, fields, colour):
    embed = discord.Embed(title=title, description=description, colour=colour)
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)
    if len(embed) > 6000:
        raise ValueError(f"FAQ embed too long: {title} ({len(embed)})")
    return footer(embed, guild)


def faq_embeds(guild):
    """How the server works. One embed per topic, same card style as the rules."""
    icon = guild.icon.url if guild.icon else None
    questions = "<#1558424678454927494>"
    tickets = "<#1558424676907225093>"
    rules = "<#1558795724899090442>"
    colours = (BRAND, GOLD, TEAL, PINK)

    intro = discord.Embed(
        title="✦  Tropical Tycoon — FAQ",
        description=(
            "New to Tropical Tycoon? This channel explains how the server works, "
            "from your first gen to prestige.\n\n"
            "Each message below is one topic. Still stuck? Ask in "
            f"{questions} or open a ticket in {tickets}."
        ),
        colour=BRAND,
    )
    if icon:
        intro.set_author(name=guild.name, icon_url=icon)
    footer(intro, guild)

    sections = [
        ("Getting started", None, [
            ("What is Tropical Tycoon?",
             "A Skyblock gens server on Java and Bedrock. You place generators (gens) on your island, "
             "sell what they drop, upgrade them and work your way up through eras, bosses and dungeons."),
            ("How do I start?",
             "1. Create your island with `/is create`.\n"
             "2. You get **5 free Wool Gens** (tier 1). Place them on your island.\n"
             "3. Pick up the drops and sell them (right-click a drop, or sneak + right-click to sell all).\n"
             "4. Use the money to upgrade your gens or buy new ones in the gen shop.\n"
             "5. Keep upgrading, rank up and unlock the next era."),
            ("Do my gens work when I'm offline?",
             "Gens only run while at least one island member is on the island. Some ranks and research "
             "unlock **offline income**: a share of your income, paid out when you come back."),
            ("Can I play on Bedrock?",
             "Yes. Bedrock players join with the same IP. Your name gets a prefix (for example a dot) "
             "and some menus look a bit different, but everything works."),
        ]),
        ("Gens, drops & selling", None, [
            ("How do gens work?",
             "Every gen drops **1 item every 5 seconds**. Higher tiers drop more valuable items, not more items."),
            ("How do I upgrade a gen?",
             "Open the gen shop or right-click your gen to upgrade it with money. Each tier costs more but earns more. "
             "There are **80 tiers** in total."),
            ("How do I sell?",
             "• Right-click a drop to sell that stack.\n"
             "• Sneak + right-click to sell all your drops.\n"
             "• Use a sell wand on a chest or Gen Collector for a multiplier."),
            ("Why did my gens stop dropping?",
             "Without a collector, drops land on the ground. Each chunk has a limit on ground stacks to prevent lag. "
             "When it's full, gens in that chunk pause until you pick up or sell the items. A **Gen Collector** fixes this."),
            ("Can I pick up someone else's gens?",
             "No. Gens, collectors and catalysts can only be picked up and upgraded by the player who placed them. "
             "Drops are shared with your island."),
            ("How many gens can I place?",
             "You start with **10 gen slots**. You get more from ranks, crates, the skill tree and island upgrades."),
        ]),
        ("Eras, ranks & Gen Cores",
         "The 80 gen tiers are split into **8 eras of 10 tiers**. Inside an era you upgrade with money. "
         "To enter the next era you need a **Gen Core**.", [
            ("1 · Wool  ·  tiers 1–10", "Next: Rank C + Basic Gen Core (tutorial dungeon)"),
            ("2 · Terracotta  ·  tiers 11–20", "Next: Dungeon I — Abandoned Mine"),
            ("3 · Concrete  ·  tiers 21–30", "Next: World boss — Stone Golem"),
            ("4 · Ore  ·  tiers 31–40", "Next: Dungeon II — Glowing Caves"),
            ("5 · Nether  ·  tiers 41–50", "Next: Dungeon III — Ashen Citadel"),
            ("6 · End  ·  tiers 51–60", "Next: World boss — Void Wyrm"),
            ("7 · Deep Dark  ·  tiers 61–70", "Next: Dungeon IV — Warden's Crypt"),
            ("8 · Celestial  ·  tiers 71–80", "Endgame: rebirth"),
            ("What is a Gen Core?",
             "The key to the next era. You get one from dungeons, bosses, or from the rank right before each era gate."),
            ("How do ranks work?",
             "There are **26 in-game ranks, A to Z**, bought with in-game money via `/rankup`. "
             "Every rank gives **+2 gen slots** and a Mystery Key. Some ranks also give a Gen Core or a title. "
             "These are separate from store ranks."),
        ]),
        ("Collectors, sell wands & catalysts", None, [
            ("What is a Gen Collector?",
             "Place **one per chunk**. It collects all drops in that chunk into virtual storage, so nothing lands on the ground. "
             "Sizes: **10K**, **100K** or **Unlimited**. When it's full, drops land on the ground again."),
            ("What is a sell wand?",
             "Right-click a chest or Gen Collector on your own island to sell everything inside at a multiplier. "
             "The free **×1.5** wand drops from the first boss (100 uses). The **×2** wand is unlimited."),
            ("What is a Gen Catalyst?",
             "A block that gives gens around it **+10% gen speed**. The 3×3 covers 8 gens, the 5×5 covers 24. "
             "Catalysts don't stack: a gen uses the strongest one in range. Hold it to see its area."),
            ("What is offline income?",
             "While nobody is on your island, your gens don't run. With offline income unlocked (research or a store rank), "
             "you get a share of your income when you return, up to a time limit."),
        ]),
        ("Prestige & Tycoon Level", None, [
            ("What is prestige?",
             "From **rank P** you can prestige. It resets your money, gens, rank and era, and you restart with 5 starter gens. "
             "In return you get **Prestige Shards** for permanent upgrades. Prestige is optional."),
            ("What can I buy with Prestige Shards?",
             "Perks in the skill tree: **+3% sell** per level, **+3% gen speed** per level, **+1 gen slot** per level, and auto-sell. "
             "Level *n* costs *n* shards."),
            ("Is there a limit?",
             "From prestige 25 you also need **Boss Relics** from bosses and dungeons. Prestige 100 is **Ascension**, "
             "with a title, aura and a Hall of Fame spot. After that comes rebirth."),
            ("What is the Tycoon Level?",
             "Your player level, shown in chat and on the scoreboard. It **never resets**, not even between seasons. "
             "You earn XP by playing actively: upgrading, ranking up, prestiging, bosses, missions and voting. "
             "Levels give small rewards and crate keys, and also level up your active pet."),
        ]),
        ("Islands & co-op", None, [
            ("Can I play with friends?",
             "Yes. An island team has up to **4 members**, upgradable to **8**. Roles are Owner, Co-owner, Member and Visitor, "
             "each with their own permissions."),
            ("Do we share gens?",
             "No. Everyone has their own gens and progression. Drops and island upgrades are shared."),
            ("What happens to my gens if I leave or get kicked?",
             "They return to you automatically, in your inventory or Gen Vault (`/gens claim`). Collector contents are paid out first."),
            ("Can I keep my island running with an alt?",
             "Yes. An alt added as a member keeps the island running. It may not be used to break rules or farm once-per-player rewards."),
            ("What are island upgrades?",
             "Shared upgrades paid with money and Essence: island size, max gens per member, an island-wide sell multiplier, "
             "hopper/chest limit and spawner slots."),
            ("What are island missions?",
             "Daily and weekly tasks the whole team works on together, like selling 10,000 concrete or defeating the Stone Golem. "
             "The island with the highest level each week wins rewards."),
        ]),
        ("Bosses & dungeons", None, [
            ("Why should I fight bosses?",
             "Bosses and dungeons drop Gen Cores (needed for the next era), gear, Essence and pets. "
             "Without them you can't get past each era gate."),
            ("How do dungeons work?",
             "Dungeons are instanced runs for **1–4 players** and take 10–20 minutes. You need a key, made from gen drops and Essence. "
             "Each dungeon has Normal, Heroic and Mythic difficulty, and weekly modifiers keep runs different."),
            ("When do world bosses spawn?",
             "Every **2 hours** in the arena near spawn, announced 5 minutes before. Loot is split by damage dealt, "
             "and the top 3 get a bonus chest."),
            ("Will I lose my items in a boss fight?",
             "No. Your inventory is saved before the fight and you fight with a boss kit. You get your exact inventory back afterwards, "
             "whether you win, die, disconnect or the server crashes. Rewards arrive on the main server."),
            ("What does gear do?",
             "Every gear piece has a combat stat and a gen stat. For example, the Smelter's Helm gives **+8% defence** "
             "and **+5% sell price** for ores."),
        ]),
        ("Pets", None, [
            ("What do pets do?",
             "Each pet gives one passive bonus, like more gen speed, a higher sell price or more Essence from bosses. "
             "Pets level **1–50** along with your Tycoon XP."),
            ("How do I use a pet?",
             "Open your Pet Bag with `/pets`. Click a pet to make it active, click again to put it away, "
             "and sneak-click to take it out as an item. Active pets float around you. Use `/pets hide` to hide them."),
            ("How many pets can I have out?",
             "You start with **1 pet slot** and can reach up to **12**, from prestige, collecting different pets, boss shards, "
             "events, store ranks and the Monthly Crate."),
            ("Can I use the same pet more than once?",
             "Yes, but each extra copy counts for less: **100%**, then **75%**, **50%**, **35%**, **25%**, and so on."),
            ("Where do I get pets?",
             "Common, Rare and Epic pets come from crates, dungeons, bosses and events. Legendary and Mythic pets come from "
             "the store and the Monthly Crate, with about one per season obtainable in-game. Duplicates give XP to the pet you already have."),
            ("Can I trade pets?",
             "Yes, pets are tradeable. **Pet slots** are bound to your account and can't be traded."),
        ]),
        ("Crates, keys & voting", None, [
            ("Where are my keys?",
             "Keys are stored on your account, not as items, so they can't be lost or duped. Check them with `/keys`, "
             "or look at the hologram above the crates at spawn."),
            ("How do I get keys?",
             "From ranking up, levelling your Tycoon Level, voting, missions, events, bosses and the store."),
            ("What's in a Mystery Crate?",
             "Rewards scaled to your own progress: money (15–60 minutes of your income, or a 3-hour jackpot), "
             "gens of your highest tiers, gen slots, cosmetics and a small chance on a Monthly Crate. "
             "All odds are shown in the crate preview."),
            ("What's in a Monthly Crate?",
             "A store crate with a new theme each month. Every crate gives **4 Common** rewards and **1 Legendary** reward, "
             "including a Legendary pet of the month."),
            ("How do I open crates?",
             "Right-click the crate at spawn and choose Open or Open 10. Sneak-click opens 10 at once without the animation."),
            ("Why should I vote?",
             "Voting with `/vote` gives keys and unlocks the **Daily Shop** for the rest of the day: "
             "3 gen offers at 1–5% off, reset at midnight (Amsterdam time)."),
        ]),
        ("Trading & currencies",
         "Use `/trade` (both players confirm, and it's logged) or the auction house. Trades outside these are at your own risk.", [
            ("Money ($)", "From selling gen drops. For gen upgrades, ranks, dungeon keys and island upgrades. **Tradeable.**"),
            ("Essence", "From dungeons and bosses. For upgrading gear, crafting Gen Cores and levelling pets. **Tradeable as an item.**"),
            ("Prestige Shards", "From prestiging. For skill tree perks. **Not tradeable.**"),
            ("Gems", "From voting, playtime and events. For cosmetics and an extra research slot. **Not tradeable.**"),
            ("How does the auction house work?",
             "List up to **10 items** for 48 hours. A **5% tax** is taken from each sale."),
            ("What are buy orders?",
             "Place an order for materials like Essence or ores at your price. When someone sells at that price, it matches instantly."),
            ("What can't I trade?",
             "Boss Relics, Gen Cores, starter gens, boss kit items, keys and pet slots are bound to your account."),
        ]),
        ("Store, seasons & help", None, [
            ("What can I buy in the store?",
             "Store ranks (Islander, Surfer, Captain, Tycoon, Mogul), cosmetics, server-wide boosters, bundles and Monthly Crates. "
             "Everything is paid through Tebex, never in-game. **Money, Gen Cores, gear and Boss Relics are never sold.**"),
            ("What is a server-wide booster?",
             "A boost for everyone online (for example 1 hour of +50% sell price). The buyer is shown in chat and on the bossbar."),
            ("My purchase didn't arrive. What now?",
             "Wait a few minutes and rejoin. Still missing? Open a **Store Support** ticket with your Tebex Order ID."),
            ("What happens at the end of a season?",
             "A season lasts about **6 months**. At the reset, money, gens and islands are wiped. "
             "Your Tycoon Level, titles and cosmetics stay. Each season has a new theme, starting with **Coral Coast**."),
            ("Where do I get help?",
             f"• Questions: {questions}\n"
             f"• Bugs: a Bug Report ticket in {tickets}, with a screenshot or clip\n"
             f"• Rule breakers: `/report` in-game, or a Player Report ticket\n"
             f"• Punishments: a Punishment Appeal ticket\n"
             f"• Rules: {rules}"),
        ]),
    ]
    embeds = [intro]
    for index, (title, description, fields) in enumerate(sections):
        embeds.append(_faq(guild, title, description, fields, colours[index % len(colours)]))
    return embeds


def welcome_embed(member):
    guild = member.guild
    rules = find_text_channel(guild, RULES_CHANNEL)
    faq = find_text_channel(guild, FAQ_CHANNEL)
    platform = find_exact_channel(guild, PLATFORM_CHANNEL) or find_text_channel(guild, "choose-platform")
    support = find_exact_channel(guild, SUPPORT_CHANNEL) or find_text_channel(guild, SUPPORT_CHANNEL)
    rules_line = f"Read the rules in {rules.mention}" if rules else "Read the rules with `/rules`"
    faq_line = f"\nNew here? {faq.mention} explains how the server works." if faq else ""
    platform_line = (
        f"\nChoose **Java** or **Bedrock** in {platform.mention}."
        if platform else f"\nChoose **Java** or **Bedrock** in #{PLATFORM_CHANNEL}."
    )
    support_line = (
        f"\nNeed help? Open a ticket in {support.mention}."
        if support else "\nNeed help? Open a ticket in the support channel."
    )
    embed = discord.Embed(
        title="✦  Welcome to Tropical Tycoon",
        description=(
            f"Hey {member.mention} — glad you made it.\n\n"
            f"{rules_line} before you play. By joining the Discord or the Minecraft server you agree to them."
            f"{faq_line}{platform_line}{support_line}\n\n"
            f"**Play:** `{PLAY_ADDRESS}`\n\n"
            "Have fun, and see you on the islands."
        ),
        colour=BRAND,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if guild.icon:
        embed.set_author(name=guild.name, icon_url=guild.icon.url)
    footer(embed, guild)
    return embed


class PlatformView(discord.ui.View):
    """Persistent Java / Bedrock role picker."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _pick(self, interaction: discord.Interaction, chosen: str):
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message("Only usable in the server.", ephemeral=True)
            return
        java = role_by_name(guild, JAVA_ROLE)
        bedrock = role_by_name(guild, BEDROCK_ROLE)
        target = java if chosen == JAVA_ROLE else bedrock
        other = bedrock if chosen == JAVA_ROLE else java
        if target is None:
            await interaction.response.send_message(
                f"Role `{chosen}` is missing. An admin should run `/setupdiscord confirm:True`.",
                ephemeral=True,
            )
            return
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            await interaction.response.send_message("I need **Manage Roles**.", ephemeral=True)
            return
        try:
            if other is not None and other in member.roles:
                await member.remove_roles(other, reason="platform switch")
            if target not in member.roles:
                await member.add_roles(target, reason="platform pick")
        except discord.Forbidden:
            await interaction.response.send_message(
                "I can't assign that role (move my role above Java/Bedrock in Server Settings → Roles).",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"You're marked as **{chosen}**. IP: `{PLAY_ADDRESS}`", ephemeral=True)

    @discord.ui.button(label="Java", style=discord.ButtonStyle.success, custom_id="tt:platform:java", emoji="☕")
    async def java_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, JAVA_ROLE)

    @discord.ui.button(label="Bedrock", style=discord.ButtonStyle.primary, custom_id="tt:platform:bedrock", emoji="📱")
    async def bedrock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, BEDROCK_ROLE)


# ---------- tickets ----------
async def create_ticket(interaction, key, reason, extra=None):
    guild = interaction.guild
    user = interaction.user
    cat_name, label, emoji, _, colour = CATEGORIES[key]
    staff_list = roles_named(guild, STAFF_ROLE_NAMES)
    ping_role = role_by_name(guild, MOD_ROLE) or role_by_name(guild, GUIDE_ROLE) or (
        staff_list[0] if staff_list else None)

    for ch in guild.text_channels:
        if is_ticket(ch) and read_topic(ch).get("owner") == str(user.id):
            await interaction.followup.send(embed=discord.Embed(
                description=f"You already have an open ticket: {ch.mention}", colour=GOLD), ephemeral=True)
            return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                          read_message_history=True, attach_files=True, embed_links=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                              manage_channels=True, read_message_history=True),
    }
    for staff in staff_list:
        overwrites[staff] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True)

    category = discord.utils.get(guild.categories, name=cat_name)
    if category is None:
        cat_overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
        for staff in staff_list:
            cat_overwrites[staff] = discord.PermissionOverwrite(view_channel=True)
        category = await guild.create_category(cat_name, overwrites=cat_overwrites)

    number = next_ticket_number()
    topic = write_topic({"owner": user.id, "claimed": 0, "type": key})
    channel = await guild.create_text_channel(f"ticket-{number}", category=category,
                                              overwrites=overwrites, topic=topic)

    embed = discord.Embed(
        title=f"{emoji}  {label}  ·  Ticket #{number}",
        description=(f"Hey {user.mention}, thanks for opening a ticket.\n"
                     f"A staff member will be with you as soon as possible.\n"
                     f"Share as many details as you can — screenshots and clips help."),
        colour=colour,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    for name, value in (extra or []):
        embed.add_field(name=name, value=f"```{value}```", inline=False)
    embed.add_field(name="Your question", value=f">>> {reason}", inline=False)
    embed.add_field(name="Opened by", value=user.mention, inline=True)
    embed.add_field(name="Category", value=label, inline=True)
    embed.add_field(name="Status", value="Waiting for staff", inline=True)
    embed.set_thumbnail(url=user.display_avatar.url)
    footer(embed, guild)
    ping = f"{user.mention} {ping_role.mention}" if ping_role else user.mention
    await channel.send(content=ping, embed=embed, view=TicketControls())

    await interaction.followup.send(embed=discord.Embed(
        description=f"Your ticket is ready: {channel.mention}", colour=colour), ephemeral=True)


async def send_transcript(channel, closed_by, data):
    guild = channel.guild
    lines = []
    async for m in channel.history(limit=None, oldest_first=True):
        t = m.created_at.astimezone().strftime("%d-%m-%Y %H:%M")
        content = m.content or ""
        for e in m.embeds:
            if e.title or e.description:
                content += f" [embed] {e.title or ''} {e.description or ''}"
        for a in m.attachments:
            content += f" [attachment] {a.url}"
        lines.append(f"[{t}] {m.author.display_name}: {content}")
    text = f"Transcript of #{channel.name}\n\n" + "\n".join(lines)

    _, type_label, type_emoji, _, colour = CATEGORIES.get(data.get("type", ""), ("", "Unknown", "📄", "", 0x64748B))
    claimed = data.get("claimed", "0")
    embed = discord.Embed(title=f"Transcript · {channel.name}", colour=colour,
                          timestamp=datetime.datetime.now(datetime.timezone.utc))
    embed.add_field(name="Category", value=f"{type_emoji} {type_label}", inline=True)
    embed.add_field(name="Opened by", value=f"<@{data.get('owner')}>", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="Claimed by", value=f"<@{claimed}>" if claimed != "0" else "Nobody", inline=True)
    embed.add_field(name="Closed by", value=closed_by.mention, inline=True)
    embed.add_field(name="Messages", value=str(len(lines)), inline=True)
    embed.set_footer(text="The full conversation is in the file below.")

    log = find_text_channel(guild, TRANSCRIPT_CHANNEL)
    if log:
        await log.send(embed=embed, file=discord.File(io.BytesIO(text.encode("utf-8")), filename=f"{channel.name}.txt"))

    try:
        owner = await bot.fetch_user(int(data.get("owner")))
        await owner.send(embed=embed, file=discord.File(io.BytesIO(text.encode("utf-8")), filename=f"{channel.name}.txt"))
    except Exception:
        pass


class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=label, value=key, emoji=emoji, description=desc)
                   for key, (_, label, emoji, desc, _) in CATEGORIES.items()]
        super().__init__(placeholder="Select a category to open a ticket...",
                         options=options, custom_id="ticket_select", min_values=1, max_values=1)

    async def callback(self, interaction):
        await interaction.response.send_modal(TicketModal(self.values[0]))
        try:
            await interaction.message.edit(view=PanelView())
        except discord.HTTPException:
            pass


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


EXTRA_FIELDS = {
    "store": [("Order ID", "Order ID", "From your Tebex confirmation e-mail", True, False),
              ("Username", "Your in-game username", "Your exact in-game name", True, False)],
    "player": [("Reported player", "Username of the player", "Exact username", True, False)],
    "bug": [("Username", "Your in-game username", "Your exact in-game name", True, False),
            ("Platform", "Platform / device", "e.g. Java, Bedrock, phone", True, False),
            ("Steps to reproduce", "How can we reproduce the bug?", "1. Go to... 2. Click... 3. The bug happens",
             False, True)],
    "appeal": [("Username", "Your in-game username", "Your exact in-game name", True, False),
               ("Punishment", "What was the punishment?", "e.g. 1d ban for macros", True, False)],
}

MAIN_QUESTION = {
    "bug": ("What went wrong?", "Describe the bug and what you expected to happen..."),
    "appeal": ("Why should this be lifted?", "Be honest. Lying in an appeal makes it worse."),
    "player": ("What happened?", "Describe it and attach a clip or screenshot in the ticket."),
}


class TicketModal(discord.ui.Modal):
    def __init__(self, key):
        super().__init__(title=f"{CATEGORIES[key][2]} {CATEGORIES[key][1]}")
        self.key = key
        self.extra_inputs = []
        fields = EXTRA_FIELDS.get(key, [])
        q_label, q_placeholder = MAIN_QUESTION.get(
            key, ("What is your ticket about?", "Describe your issue as clearly as possible..."))
        self.reden = discord.ui.TextInput(label=q_label, placeholder=q_placeholder,
                                          style=discord.TextStyle.paragraph, min_length=5, max_length=1000)
        for embed_name, label, placeholder, required, long in [f for f in fields if not f[4]]:
            self._add_extra(embed_name, label, placeholder, required, long)
        self.add_item(self.reden)
        for embed_name, label, placeholder, required, long in [f for f in fields if f[4]]:
            self._add_extra(embed_name, label, placeholder, required, long)

    def _add_extra(self, embed_name, label, placeholder, required, long):
        field = discord.ui.TextInput(label=label, placeholder=placeholder, required=required,
                                     style=discord.TextStyle.paragraph if long else discord.TextStyle.short,
                                     max_length=1000 if long else 100)
        self.add_item(field)
        self.extra_inputs.append((embed_name, field))

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        extra = [(name, field.value.strip()) for name, field in self.extra_inputs if field.value.strip()]
        await create_ticket(interaction, self.key, self.reden.value, extra)


class TicketControls(discord.ui.View):
    def __init__(self, claimed_name=None):
        super().__init__(timeout=None)
        if claimed_name:
            self.claim.disabled = True
            self.claim.label = f"Claimed by {claimed_name}"[:80]

    @discord.ui.button(label="Claim", emoji="🙋", style=discord.ButtonStyle.success, custom_id="ticket_claim")
    async def claim(self, interaction, button):
        member = interaction.user
        if not is_staff(member):
            await interaction.response.send_message("Only Guide/Mod/Admin/Owner can claim tickets.", ephemeral=True)
            return
        data = read_topic(interaction.channel)
        if data.get("claimed", "0") != "0":
            await interaction.response.send_message(
                f"This ticket has already been claimed by <@{data['claimed']}>.", ephemeral=True)
            return
        data["claimed"] = str(member.id)
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed:
            for i, field in enumerate(embed.fields):
                if "Status" in field.name:
                    embed.set_field_at(i, name=field.name, value=f"Claimed by {member.mention}", inline=True)
        await interaction.response.edit_message(embed=embed, view=TicketControls(member.display_name))
        await interaction.channel.send(embed=discord.Embed(
            description=f"**{member.display_name}** has claimed this ticket and will help you.",
            colour=0x22C55E))
        await interaction.channel.edit(topic=write_topic(data))

    @discord.ui.button(label="Close", emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="ticket_close")
    async def close(self, interaction, button):
        member = interaction.user
        channel = interaction.channel
        data = read_topic(channel)
        if not (is_staff(member) or data.get("owner") == str(member.id)):
            await interaction.response.send_message("You are not allowed to close this ticket.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=discord.Embed(description="Close this ticket?", colour=0xEF4444),
            view=ConfirmClose(), ephemeral=True)


class ConfirmClose(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Yes, close it", emoji="🔒", style=discord.ButtonStyle.danger)
    async def yes(self, interaction, button):
        channel = interaction.channel
        member = interaction.user
        data = read_topic(channel)
        await interaction.response.edit_message(
            embed=discord.Embed(description="Closing ticket...", colour=0x64748B), view=None)
        await channel.send(embed=discord.Embed(
            description=f"Ticket closed by {member.mention}. This channel will be deleted in 5 seconds.",
            colour=0xEF4444))
        await send_transcript(channel, member, data)
        await asyncio.sleep(5)
        await channel.delete(reason=f"Ticket closed by {member}")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def no(self, interaction, button):
        await interaction.response.edit_message(
            embed=discord.Embed(description="Okay, the ticket stays open.", colour=0x64748B), view=None)


# ---------- slash commands ----------
@bot.tree.command(name="panel", description="Post the ticket panel in this channel")
@app_commands.default_permissions(administrator=True)
async def panel(interaction: discord.Interaction):
    guild = interaction.guild
    uitleg = "\n".join(f"> {e} **{l}** · {d}" for _, l, e, d, _ in CATEGORIES.values())
    embed = discord.Embed(
        title="✦  Support Center",
        description=(
            "Got a question, want to report a player, found a bug or need to appeal?\n"
            "Open a ticket below and the team will help you.\n\n"
            f"{uitleg}\n\n"
            "**Before you open a ticket**\n"
            "• Read the rules (`/rules`) and check the questions channel\n"
            "• One ticket per issue, include your IGN and as many details as possible\n"
            "• Be patient and don't ping staff"
        ),
        colour=BRAND,
    )
    if guild.icon:
        embed.set_author(name=guild.name, icon_url=guild.icon.url)
    embed.set_footer(text="Select a category from the menu below")
    kwargs = {}
    if os.path.exists(banner_path()):
        kwargs["file"] = discord.File(banner_path(), filename="banner.png")
        embed.set_image(url="attachment://banner.png")
    await interaction.channel.send(embed=embed, view=PanelView(), **kwargs)
    await interaction.response.send_message("Panel posted.", ephemeral=True)


@bot.tree.command(name="postrules", description="Post the official Tropical Tycoon rules in this channel")
@app_commands.default_permissions(administrator=True)
async def postrules(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    for embed in rules_embeds(interaction.guild):
        await interaction.channel.send(embed=embed)
    await interaction.followup.send("Rules posted. Pin the first message in this channel.", ephemeral=True)


@bot.tree.command(name="postfaq", description="Post the Tropical Tycoon FAQ in this channel")
@app_commands.default_permissions(administrator=True)
async def postfaq(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    for embed in faq_embeds(interaction.guild):
        await interaction.channel.send(embed=embed)
    await interaction.followup.send("FAQ posted. Pin the first message in this channel.", ephemeral=True)


@bot.tree.command(name="rules", description="Where to read the Tropical Tycoon rules")
async def rules(interaction: discord.Interaction):
    channel = find_text_channel(interaction.guild, RULES_CHANNEL)
    where = channel.mention if channel else "the rules channel (ask staff to run `/postrules` there)"
    embed = discord.Embed(
        title="✦  Server Rules",
        description=(
            f"The full official rules live in {where}.\n"
            "By playing or joining Discord you agree to them.\n\n"
            "In-game you can also use `/rules`.\n"
            "To report someone or appeal a punishment, open a ticket."
        ),
        colour=BRAND,
    )
    footer(embed, interaction.guild)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="setupperms",
    description="Lock info channels: members read-only, Mod+ can post",
)
@app_commands.default_permissions(administrator=True)
async def setupperms(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("Only usable in a server.", ephemeral=True)
        return
    me = guild.me
    if me is None or not me.guild_permissions.manage_channels:
        await interaction.followup.send(
            "I need **Manage Channels**. Fix bot role permissions, then retry.",
            ephemeral=True,
        )
        return

    everyone = guild.default_role
    mod_roles = roles_named(guild, MOD_PLUS_NAMES)
    locked = []
    skipped = []

    for channel in guild.text_channels:
        name = channel.name.lower()
        if not any(part in name for part in LOCK_CHANNEL_NAMES):
            continue
        try:
            await apply_channel_mode(channel, "readonly", everyone, roles_named(guild, STAFF_ROLE_NAMES), mod_roles)
            locked.append(channel.mention)
        except discord.Forbidden:
            skipped.append(f"#{channel.name} (forbidden)")
        except discord.HTTPException as e:
            skipped.append(f"#{channel.name} ({e})")

    lines = [
        f"**Locked ({len(locked)}):** " + (", ".join(locked) if locked else "none matched"),
    ]
    if skipped:
        lines.append("**Skipped:** " + ", ".join(skipped))
    if not mod_roles:
        lines.append(f"Create roles `{MOD_ROLE}` / `{ADMIN_ROLE}` / `{OWNER_ROLE}` (or run `/setupdiscord`).")
    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.command(
    name="setupdiscord",
    description="Apply roles/permissions on existing Tropical Tycoon channels (no duplicates by default)",
)
@app_commands.describe(
    confirm="False = preview matching. True = apply roles + permissions.",
    create_missing="True = also create missing plain channels (default False = reuse yours only).",
)
@app_commands.default_permissions(administrator=True)
async def setupdiscord(
    interaction: discord.Interaction,
    confirm: bool = False,
    create_missing: bool = False,
):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("Only usable in a server.", ephemeral=True)
        return
    me = guild.me
    if me is None:
        await interaction.followup.send("Bot member not found.", ephemeral=True)
        return
    if not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
        await interaction.followup.send(
            "I need **Manage Channels** and **Manage Roles**. "
            "Put my role near the top (above Member / Java / Bedrock).",
            ephemeral=True,
        )
        return

    plan_lines = [
        "**Roles:** " + ", ".join(n for n, _, _ in ROLE_SPECS),
        "**Matched against your existing channels** (emoji names OK):",
    ]
    missing_preview = []
    for cat_name, channels in DISCORD_LAYOUT:
        bits = []
        for ch_name, _, _ in channels:
            found = find_layout_channel(guild, ch_name)
            if found is not None:
                bits.append(f"{found.mention}")
            else:
                bits.append(f"`#{ch_name}` ❌")
                missing_preview.append(ch_name)
        plan_lines.append(f"• **{cat_name}** — " + ", ".join(bits))
    plan_lines.append(
        "\n**Aliases:** media↔showcase, suggestions↔feedback, etc.\n"
        "**Rank rooms:** #below-captain (Islander, Surfer), #captain, #above-captain (Tycoon, Mogul)\n"
        "**On join:** Member role + welcome in #welcome\n"
        f"**create_missing:** `{create_missing}` "
        "(keep False so nothing new is created)"
    )
    if missing_preview:
        plan_lines.append(
            "\n**Not found** (skipped unless create_missing=True): `"
            + "`, `".join(missing_preview) + "`"
        )

    if not confirm:
        plan_lines.append(
            "\nThis was a **preview**. Run `/setupdiscord confirm:True` to apply "
            "(roles + permissions on matched channels only)."
        )
        await interaction.followup.send("\n".join(plan_lines), ephemeral=True)
        return

    created_roles = []
    for name, colour, hoist in ROLE_SPECS:
        _, made = await ensure_role(guild, name, colour, hoist)
        if made:
            created_roles.append(name)
        await asyncio.sleep(0.3)

    everyone = guild.default_role
    staff_roles = roles_named(guild, STAFF_ROLE_NAMES)
    mod_roles = roles_named(guild, MOD_PLUS_NAMES)
    created_channels = []
    used = []
    missing = []
    failed = []

    for cat_name, channels in DISCORD_LAYOUT:
        category = None
        if create_missing:
            category, cat_new = await ensure_category(guild, cat_name, create_missing=True)
            if cat_new:
                created_channels.append(f"category:{cat_name}")
            await asyncio.sleep(0.3)
        for ch_name, topic, mode in channels:
            channel, ch_new = await ensure_text_channel(
                guild, ch_name, category, topic, create_missing=create_missing)
            if channel is None:
                missing.append(ch_name)
                continue
            if ch_new:
                created_channels.append(f"#{ch_name}")
            else:
                used.append(channel.mention)
            try:
                await apply_channel_mode(channel, mode, everyone, staff_roles, mod_roles)
            except discord.Forbidden:
                failed.append(f"#{channel.name} (perms)")
            await asyncio.sleep(0.35)

            if mode == "platform" and ch_new:
                try:
                    await channel.send(embed=platform_embed(guild), view=PlatformView())
                except discord.HTTPException:
                    pass
            if ch_name == STORE_CHANNEL and ch_new:
                try:
                    await channel.send(embed=store_embed(guild))
                except discord.HTTPException:
                    pass

    try:
        rank_made = await account_link.ensure_rank_rooms(guild)
    except discord.HTTPException as e:
        rank_made = [f"rank rooms failed ({e})"]
    rules_ch = find_layout_channel(guild, RULES_CHANNEL)
    faq_ch = find_layout_channel(guild, FAQ_CHANNEL)
    support_ch = find_layout_channel(guild, SUPPORT_CHANNEL)
    summary = [
        "**Discord setup applied** (existing channels reused).",
        f"**Roles created:** {', '.join(created_roles) if created_roles else 'none (already existed)'}",
        f"**Channels used:** {', '.join(used) if used else 'none'}",
        f"**Created:** {', '.join(created_channels) if created_channels else 'none'}",
        f"**Rank rooms:** {', '.join(rank_made) if rank_made else 'already in place'}",
    ]
    if missing:
        summary.append("**Skipped (not found):** `" + "`, `".join(missing) + "`")
    if failed:
        summary.append("**Perms failed:** " + ", ".join(failed))
    summary.extend([
        "",
        "**Next (run in those channels):**",
        f"1. `/postrules` in {rules_ch.mention if rules_ch else '#rules'}",
        f"2. `/postfaq` in {faq_ch.mention if faq_ch else '#faq'}",
        f"3. `/panel` in {support_ch.mention if support_ch else '#support'}",
        "4. Delete the plain duplicate channels the bot made earlier (#rules, #faq, …) if you still have them",
        "5. Bot role **above** Member / Java / Bedrock; assign Owner/Admin/Mod/Guide manually",
    ])
    await interaction.followup.send("\n".join(summary), ephemeral=True)


@bot.tree.command(name="add", description="Add someone to this ticket")
async def add(interaction: discord.Interaction, user: discord.Member):
    if not is_staff(interaction.user) or not is_ticket(interaction.channel):
        await interaction.response.send_message("Only staff can do this, inside a ticket.", ephemeral=True)
        return
    await interaction.channel.set_permissions(user, view_channel=True, send_messages=True,
                                              read_message_history=True, attach_files=True)
    await interaction.response.send_message(f"{user.mention} has been added to this ticket.")


@bot.tree.command(name="remove", description="Remove someone from this ticket")
async def remove(interaction: discord.Interaction, user: discord.Member):
    if not is_staff(interaction.user) or not is_ticket(interaction.channel):
        await interaction.response.send_message("Only staff can do this, inside a ticket.", ephemeral=True)
        return
    await interaction.channel.set_permissions(user, overwrite=None)
    await interaction.response.send_message(f"{user.mention} has been removed from this ticket.")


@bot.event
async def on_member_join(member):
    if member.bot:
        return
    guild = member.guild
    member_role = role_by_name(guild, MEMBER_ROLE)
    if member_role is not None and member_role not in member.roles:
        try:
            await member.add_roles(member_role, reason="auto Member on join")
        except discord.Forbidden:
            pass
    channel = find_exact_channel(guild, WELCOME_CHANNEL) or find_text_channel(guild, WELCOME_CHANNEL)
    if channel is None:
        return
    await channel.send(content=member.mention, embed=welcome_embed(member))


# Register /manage at import time (before setup_hook) so Wispbyte always loads it.
staff_manage.setup(bot)
account_link.setup(bot)


@bot.event
async def setup_hook():
    bot.add_view(PanelView())
    bot.add_view(TicketControls())
    bot.add_view(PlatformView())
    staff_manage.setup(bot)
    account_link.setup(bot)


@bot.event
async def on_ready():
    print(f"Tropical Tycoon bot online as {bot.user} ({len(bot.guilds)} servers).", flush=True)
    names = sorted({c.name for c in bot.tree.get_commands()})
    print(f"  slash commands in tree: {', '.join(names) if names else '(none)'}", flush=True)
    synced_names: list[str] = []
    for guild in bot.guilds:
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        synced_names = sorted({c.name for c in synced})
        print(
            f"  synced {len(synced)} commands on {guild.name}: "
            + ", ".join(synced_names),
            flush=True,
        )
    if not getattr(bot, "_tt_staff_log_pinged", False):
        bot._tt_staff_log_pinged = True  # type: ignore[attr-defined]
        await staff_manage.notify_connected(synced_names or names)
    account_link.start_loop(bot)


if __name__ == "__main__":
    bot.run(TOKEN)

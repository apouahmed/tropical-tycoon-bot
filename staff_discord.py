"""Staff HQ for the Tropical Tycoon staff server.

Builds Guide / Mod / Admin rooms, a private channel with the owner for every
staff member, and the staff handbook. The handbook follows the public rules in
this bot and the in-game rank ladder (guide < mod < admin < owner): a guide
stops at 1 day, a mod at 7 days, and duty is required.

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

# (category, (logical name, topic, mode, kind)).
# mode: news | docs | all | guide | mod | admin | board | audit | punishments
# kind: text | voice. A higher rank sees every room below it. No explicit deny on a
# lower role, or someone who also holds the higher role would be locked out.
STAFF_LAYOUT = (
    ("🌴 START", (
        ("start-here", "Read this first. What this server is, and which room is for what.", "docs", "text"),
        ("onboarding", "The checklist for your first week. Do this before you punish anyone.", "docs", "text"),
    )),
    ("📖 HANDBOOK", (
        ("handbook", "Index of the staff handbook. The public rules are still the rules.", "docs", "text"),
        ("conduct", "How staff behave. Proof, tone, conflicts, and your private channel.", "docs", "text"),
        ("ranks", "Guide, Mod, Admin, Owner. Store ranks are not staff ranks.", "docs", "text"),
        ("ladder", "The same punishment table as the public rules, and how to apply it.", "docs", "text"),
        ("cases", "How to write a case, and what to do in the situations that actually happen.", "docs", "text"),
        ("appeals", "Reports, appeals, refunds, and when you stay off your own case.", "docs", "text"),
        ("desk", "Tickets, public chat, voice, and which staff room a message belongs in.", "docs", "text"),
    )),
    ("📣 FLOOR", (
        ("staff-news", "Decisions the whole team follows. Guide+ read. Admin+ post.", "news", "text"),
        ("staff-chat", "All staff. Short updates. Private things go in your owner channel.", "all", "text"),
        ("staff-voice", "All staff. No recording without everyone in the call agreeing.", "guide", "voice"),
    )),
    ("⏱️ DUTY", (
        ("on-duty", "Who is on duty right now. One message, kept by the bot.", "board", "text"),
        ("duty-log", "Clock in, clock out, and how long that shift was. Admin and Owner.", "audit", "text"),
        ("punishments", "Warns, mutes, bans, kicks, unmutes, and unbans. Guide and up can read.", "punishments", "text"),
        ("economy", "Refunds and item fixes. Admin and Owner.", "audit", "text"),
    )),
    ("🛟 RANKS", (
        ("guide-chat", "Guides and up. Questions, shadowing, and cases inside a 1 hour mute.", "guide", "text"),
        ("mod-chat", "Mods and up. Kicks, bans up to 7 days, and proof you are handing up.", "mod", "text"),
        ("admin-chat", "Admins and the owner. Permabans, item corrections, and rank changes.", "admin", "text"),
    )),
)
VENT_CATEGORY = "🫶 WITH THE OWNER"
# Bumped when the handbook is rewritten, so an older post does not block the new one.
DOC_VERSION = "v7"
VENT_MARKER = "vent=1"
ROOM_FOR_RANK = {
    GUIDE_ROLE: "guide-chat",
    MOD_ROLE: "mod-chat",
    ADMIN_ROLE: "admin-chat",
    OWNER_ROLE: "admin-chat",
}

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
    ("Bug abuse", "Warning, items removed → 1d ban → 7d ban → Permanent ban"),
    ("Duping / exploiting", "7d ban, items removed → Permanent ban"),
    ("Griefing", "1d ban → 3d ban → 7d ban → Permanent ban"),
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
    "board": GUIDE_ROLE,
    "mod": MOD_ROLE,
    "admin": ADMIN_ROLE,
    "audit": ADMIN_ROLE,
    "punishments": GUIDE_ROLE,
}
_MODE_SEND = {
    "news": ADMIN_ROLE,
    "docs": ADMIN_ROLE,
    "all": GUIDE_ROLE,
    "guide": GUIDE_ROLE,
    "board": OWNER_ROLE,
    "mod": MOD_ROLE,
    "admin": ADMIN_ROLE,
    "audit": OWNER_ROLE,
    "punishments": OWNER_ROLE,
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


def channel_docs_marker(logical: str) -> str:
    return f"tt-staff-docs={DOC_VERSION}:{logical}"


def docs_are_current(topic: str | None, logical: str) -> bool:
    return channel_docs_marker(logical) in (topic or "")


def highest_rank(role_names) -> str | None:
    found = None
    for name in RANK_ORDER:
        if name in role_names:
            found = name
    return found


def _room(mentions: dict | None, logical: str) -> str:
    if mentions and mentions.get(logical):
        return str(mentions[logical])
    return f"#{logical}"


def _embed(guild_name, icon_url, title, description, fields, colour) -> discord.Embed:
    embed = discord.Embed(title=title, description=description or None, colour=colour)
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)
    return _footer(embed, guild_name, icon_url)


def handbook_sections(guild_name: str, icon_url: str | None = None, mentions: dict | None = None) -> dict:
    """One list of embeds per handbook channel. Public rules and the rank ladder are the source."""
    start = _room(mentions, "start-here")
    boarding = _room(mentions, "onboarding")
    conduct = _room(mentions, "conduct")
    ranks = _room(mentions, "ranks")
    ladder = _room(mentions, "ladder")
    cases = _room(mentions, "cases")
    appeals = _room(mentions, "appeals")
    desk = _room(mentions, "desk")
    news = _room(mentions, "staff-news")
    chat = _room(mentions, "staff-chat")
    voice = _room(mentions, "staff-voice")
    guide = _room(mentions, "guide-chat")
    mod = _room(mentions, "mod-chat")
    admin = _room(mentions, "admin-chat")
    on_duty = _room(mentions, "on-duty")
    duty_log = _room(mentions, "duty-log")
    punishments = _room(mentions, "punishments")
    economy = _room(mentions, "economy")

    sections = {
        "start-here": [
            _embed(
                guild_name, icon_url,
                "✦  Tropical Tycoon staff",
                "This server is the staff workplace. Players are not in here, and nothing from here is copied into public chat.\n\n"
                "The public rules, in-game `/rules` and the rules channel, are what players agreed to. "
                "You enforce those rules, including their spirit. Your rank is the ceiling. "
                "Going past it is a staff offence.",
                [
                    ("How the rooms work",
                     f"{start} is this page. {boarding} is your first week.\n"
                     f"The handbook is {conduct}, {ranks}, {ladder}, {cases}, {appeals}, and {desk}.\n"
                     f"{news} is decisions. {chat} is the floor. {voice} is the call.\n"
                     f"{on_duty} shows who is working. {duty_log} is the shift record.\n"
                     f"{punishments} is every warn, mute, ban, kick, unmute, and unban.\n"
                     f"{economy} is refunds and item fixes. Admin and Owner only.\n"
                     f"{guide}, {mod}, and {admin} are the rank rooms. A higher rank can see the rooms below. "
                     "A lower rank cannot see the rooms above."),
                    ("Your channel with the owner",
                     "Every Guide, Mod, and Admin gets one channel that only they and the owner can see. "
                     "Use it to speak freely, to ask before you punish, or to flag another staff member. "
                     "The rest of the team cannot read it. Write in whatever language is easiest."),
                    ("Read this order once",
                     f"1. {boarding}\n2. {conduct}\n3. {ranks}\n4. {ladder}\n5. {cases}\n6. {appeals}\n7. {desk}\n"
                     "Then say hello in the floor channel. Don't take a case before that."),
                ],
                BRAND,
            ),
        ],
        "onboarding": [
            _embed(
                guild_name, icon_url,
                "✦  Your first week",
                "Do these before you mute, kick, or ban anyone. Watching is part of the job.",
                [
                    ("1. Read the handbook",
                     f"In order: {conduct}, {ranks}, {ladder}, {cases}, {appeals}, {desk}. "
                     "The ladder in here is the same table players see. Don't invent a shorter one."),
                    ("2. Learn your ceiling",
                     "Your private channel has the rank you were given and where it stops. "
                     "Go on duty with `/duty` before any `/staff` action. "
                     "A guide stops at a **1 day** mute or ban. A mod stops at **7 days**. "
                     "Permanent bans, refunds, and `/staff item` are admin."),
                    ("3. Say hello, then watch",
                     f"Post in {chat} with your rank and the hours you are usually around. "
                     f"Read {guide} for a few real cases before you take one. "
                     "Ask how a decision was made. Don't undo it in public."),
                    ("4. Two ranks that are easy to mix up",
                     "Islander, Surfer, Captain, Tycoon, and Mogul are **store** ranks. They are not staff. "
                     "A Captain cannot mute. A Guide is not a store rank and does not get store perks from the staff role."),
                    ("5. When you are unsure",
                     "Write it in your owner channel before you act. That is the point of the channel. "
                     "Guessing a ban is worse than waiting an hour."),
                ],
                GOLD,
            ),
        ],
        "handbook": [
            _embed(
                guild_name, icon_url,
                "✦  Handbook",
                "These channels are the staff copy of the public rules, plus how we work. "
                "If a page and the public rules ever disagree, the public rules win and an admin fixes the page.",
                [
                    ("Conduct", f"{conduct} — proof, tone, conflicts, privacy, tools."),
                    ("Ranks", f"{ranks} — what Guide, Mod, Admin, and Owner may do, and what stays off."),
                    ("Ladder", f"{ladder} — every step, how a repeat is counted, and when you may skip."),
                    ("Cases", f"{cases} — the note you write, and the situations that actually show up."),
                    ("Appeals", f"{appeals} — reports, one appeal, refunds, and staying off your own case."),
                    ("Desk", f"{desk} — tickets, public chat, voice, and which room a message belongs in."),
                ],
                BRAND,
            ),
        ],
        "conduct": [
            _embed(
                guild_name, icon_url,
                "✦  How staff act",
                "A wrong punishment costs a player more than a slow one costs you. Slow down.",
                [
                    ("Proof first",
                     "A clip, a screenshot, or the time and the IGN. A picture of the result, with no act and no time, is weak. "
                     "No proof, no punishment, except a threat that is happening right now. Write the proof into the case note."),
                    ("The ladder, not a mood",
                     "Start at the first step of that rule. A repeat of the **same** rule moves one step. "
                     "A different rule starts at its own first step. Skip ahead only for a severe case: threats, doxxing, cheats, duping."),
                    ("Hand it up before you stretch",
                     "A guide does not 'just this once' kick. A mod does not 'just this once' permaban. "
                     f"The next rank is {guide}, then {mod}, then {admin}. Say what you already did and what you need."),
                    ("Stay off your own case",
                     "A friend, someone you play with, or someone you dislike: pass it on and say that you did. "
                     "You can gather the clip. You don't choose the punishment."),
                    ("Disagree in the rank room",
                     f"If two of you read a case differently, the higher rank decides and writes it in that rank room. "
                     f"Don't keep the argument in public chat, in a ticket, or in {chat}. "
                     "The owner has the last word."),
                    ("Privacy",
                     "Don't post proof, the punished IGN, or the length in public chat or in DMs to players. "
                     "Players appeal with a ticket. One appeal per punishment. "
                     "Never ask for or keep a real name, address, photo, or email. Doing that is the permanent-ban rule, including for staff."),
                    ("Tools are for the case in front of you",
                     "`/staff tp`, `/staff tphere`, vanish, and invsee are for an open case. "
                     "Not for curiosity, not for your own island, not to show off. "
                     "Look, write down what you needed, and leave. You have to be on duty."),
                    ("Tone",
                     "Short, calm, and specific. No sarcasm at a player, no pile-on in a ticket, no public argument with another staff member. "
                     "If you need to vent, that is what your channel with the owner is for."),
                ],
                GOLD,
            ),
        ],
        "ranks": [
            _embed(
                guild_name, icon_url,
                "✦  What your rank may do",
                "In-game track `staff`: **guide < mod < admin < owner**. A higher rank can do everything below it.\n"
                "`/staff warn` is the warning. It needs a reason, and you have to be on duty.\n"
                "Store ranks (Islander, Surfer, Captain, Tycoon, Mogul) are not on this track and are not staff.",
                [
                    ("Guide",
                     "`/duty` first. Mute and ban up to **1 day**, only with `/staff mute` and `/staff ban`.\n"
                     "`/staff tp`, `/staff tphere`, `/staff warn`, `/staff note`, `/staff history`, `/staff lookup`.\n"
                     "`/helpop`, `/seen`, `/whois`, `/list`.\n"
                     "You do **not** kick, vanish, open an inventory, unmute, unban, or give items. "
                     "A step longer than 1 day goes to a mod."),
                    ("Mod",
                     "Kick. Mute and ban up to **7 days**, still only with `/staff mute` and `/staff ban`.\n"
                     "`/staff vanish` and `/staff invsee` (look, don't take). "
                     "`/island admin show` and `/island admin teleport` when nobody is on the island.\n"
                     "A permanent ban, unmute, unban, a refund, or `/staff item` goes to admin."),
                    ("Admin",
                     "Permanent mute and ban. `/staff unmute` and `/staff unban`.\n"
                     "`/staff refund` and `/staff item`, with a reason. "
                     "`/gens give`, `/gens keys`, `/gens xp`, `/gens booster`, and `/pets give` are logged.\n"
                     "Move an island leader. Add or remove **Guide** and **Mod** only. "
                     "You cannot grant Admin or Owner, and you still have no creative and no `/op`."),
                    ("Owner",
                     "Creative, `/op`, LuckPerms, `/gens wipe`, the store and expedition tools, Tebex, `/hub set`, and `/warp set`.\n"
                     "Disbanding an island, purging it, or resetting the world stays here."),
                    ("Owner only",
                     "Creative and other gamemodes, `/op`, and adding or removing Admin or Owner."),
                    ("Discord rooms follow the same ceiling",
                     f"Everyone reads {news}. Everyone talks in {chat} and joins {voice}.\n"
                     f"{guide} is the guide floor. {mod} is hidden from guides. {admin} is hidden from guides and mods.\n"
                     "Your private channel is not a rank room. Other staff never see it."),
                ],
                TEAL,
            ),
        ],
        "ladder": [
            _embed(
                guild_name, icon_url,
                "✦  Punishment ladder",
                "Same table as the public rules. One step up each time the **same** rule happens again. "
                "Severe cases can start higher: threats, doxxing, cheats, duping. "
                "A first-time AFK-farming ban can be lifted on appeal if the player is honest. Don't promise that before the appeal is read.",
                list(PUNISHMENT_LADDER[:11]),
                PINK,
            ),
            _embed(
                guild_name, icon_url,
                "✦  Punishment ladder, continued",
                "Write the step in the case note before you tell the player. IGN, rule, step, length, proof.",
                list(PUNISHMENT_LADDER[11:]),
                PINK,
            ),
        ],
        "cases": [
            _embed(
                guild_name, icon_url,
                "✦  How to write a case",
                "If it is not written down, the next person will punish it again or undo it.\n\n"
                "```\n"
                "IGN:\n"
                "Java or Bedrock:\n"
                "Rule:\n"
                "Ladder step:\n"
                "Repeat of the same rule:\n"
                "Length:\n"
                "Proof:\n"
                "Done so far:\n"
                "Handed to:\n"
                "```\n"
                "Put that note in the rank room that matches who has to act, not in public chat.",
                [
                    ("Proof that holds",
                     "A clip of the act, or a screenshot plus the time. Coords help for grief and dupes. "
                     "A Bedrock name from Floodgate often starts with a dot. That dot alone is not impersonation."),
                    ("Alts",
                     "An alt used as an AFK island member is allowed. An alt used to dodge a punishment, or to take a reward twice, is ban evasion. "
                     "Check `/seen` before you call it an alt."),
                ],
                BRAND,
            ),
            _embed(
                guild_name, icon_url,
                "✦  Situations",
                "Handle the step your rank is allowed to finish. Hand the rest up with the note already filled in.",
                [
                    ("Spam, insults, staff disrespect",
                     "A guide can do the warning and the mutes and bans that stay inside 1 day. "
                     "Anything longer is a mod. Don't stretch a chat warning because the player argued."),
                    ("Harassment or hate",
                     "Start the ladder. A guide can mute or ban up to 1 day. A longer step is a mod. "
                     "Threats, doxxing, and slurs can start higher."),
                    ("Cheats or a hacked client",
                     "First step is 7 days, which a mod may apply once the clip is real. 30 days and permanent are admin. "
                     "Vanish is for watching them. The clip is the proof. Then stop."),
                    ("Duping or exploiting",
                     "A guide or mod saves the clip, the coords, and the time, and posts the note in admin chat. "
                     "Admin takes the items off."),
                    ("Scam, theft, grief",
                     "A mod can do the 7 day step where the ladder starts there. A longer ban is admin. "
                     "Tell the player staff cannot always return a scam or a grief. Don't promise the items back."),
                    ("Real-money trading or a chargeback",
                     "Both go to admin. A chargeback is a permanent ban and the bought items come off, wherever they ended up. "
                     "Don't negotiate it in a ticket."),
                    ("Lost items, a bug, a store purchase",
                     "This is not a punishment. Bug Report or Store Support, with the time or the Tebex order id. "
                     "Guides and mods do not `/gens give`. Admin does, with a reason, and only when the proof is there."),
                ],
                GOLD,
            ),
        ],
        "appeals": [
            _embed(
                guild_name, icon_url,
                "✦  Reports and appeals",
                "Players report. Staff decide. Nobody gets to punish a player from a public argument.",
                [
                    ("Reports",
                     "Tell the player to use `/report`. That sends them to the main Discord to open a Player Report ticket, with a clip.\n"
                     "You handle that ticket. Don't take the report in game chat, and don't discuss the punishment in the ticket beyond what they need to appeal."),
                    ("One appeal",
                     "One Punishment Appeal ticket per punishment. The person who issued it does not decide the appeal. "
                     "A higher rank, or someone who was not involved, reads it. Lying in the appeal moves them up the ladder."),
                    ("What you may undo",
                     "A first AFK-farming ban can be lifted if they are honest. Say that only after you have read the appeal. "
                     "You don't shorten a ban in DMs, and you don't trade a shorter ban for anything."),
                    ("Refunds are not appeals",
                     "A crash or a bug needs the time and a screenshot, in a Bug Report. "
                     "A store problem needs the Tebex order id in Store Support. "
                     "A chargeback is not a refund request. It is a permanent ban."),
                    ("A problem with staff",
                     "Don't put it in the floor channel and don't take it to a player. "
                     "Write it in your channel with the owner. If you are the one being accused, step off the case."),
                    ("Leaving the team",
                     "When the staff role comes off, the private channel closes for you and stays for the owner. "
                     "The history is kept. The rank rooms disappear with the role."),
                ],
                BRAND,
            ),
        ],
        "desk": [
            _embed(
                guild_name, icon_url,
                "✦  The desk",
                "Public Discord stays in English. This staff server, and your channel with the owner, can be whatever language is easiest.",
                [
                    ("Tickets",
                     "A player report starts with `/report` in-game. That opens a ticket on the main Discord.\n"
                     "Player Report, General Support, Bug Report, Store Support, Punishment Appeal. "
                     "One ticket per issue, with the IGN. Claim puts your name on the channel. "
                     "`/close request` asks the player before a timed close. The Close button still closes it immediately. "
                     "Don't ping them to hurry, and don't punish them for opening the ticket."),
                    ("Which room",
                     f"{news} — a decision the whole team must follow. Admin writes it.\n"
                     f"{chat} — a short update: who has a case, who is around.\n"
                     f"{voice} — talk it through. No recording unless everyone in the call agrees.\n"
                     f"{guide} {mod} {admin} — the case note, in the lowest room whose rank can finish it.\n"
                     "Your owner channel — doubt, a hard shift, or another staff member."),
                    ("Public chat",
                     "The public rules on Discord still apply to you. No drama about a punishment. "
                     "No proof posted for the audience. If a player argues, point them at a Punishment Appeal and stop."),
                    ("In-game inbox",
                     "`/helpop` is how players reach staff in game. Answer it, or say in the floor channel that you have it. "
                     "Don't leave it sitting because it wasn't a Discord ticket."),
                    ("Duty",
                     f"`/duty` starts and ends the shift. Every `/staff` action refuses while you are off duty.\n"
                     f"{on_duty} shows who is working right now. {duty_log} records the clock-in, the clock-out, and how long the shift was."),
                ],
                TEAL,
            ),
        ],
    }
    return sections


def staff_handbook_embeds(guild_name: str, icon_url: str | None = None, mentions: dict | None = None) -> list[discord.Embed]:
    """Every handbook embed, in room order. Used by tests and by a full refresh."""
    sections = handbook_sections(guild_name, icon_url, mentions)
    ordered = []
    for _, channels in STAFF_LAYOUT:
        for logical, _topic, mode, kind in channels:
            if mode == "docs" and kind == "text":
                ordered.extend(sections.get(logical, []))
    return ordered


def rank_brief_embed(guild_name: str, icon_url: str | None, rank: str) -> discord.Embed:
    briefs = {
        GUIDE_ROLE: (
            "You are a Guide.",
            "Go on duty with `/duty` first. You can mute and ban up to **1 day** with `/staff mute` and `/staff ban`, "
            "and you can use `/staff tp`, `/staff tphere`, `/staff warn`, `/helpop`, `/seen`, `/whois`, and `/list`.\n"
            "You cannot kick, vanish, open an inventory, or give items. "
            "If a case needs more than 1 day, write the note and hand it to a mod.\n"
            "Read the handbook before your first punishment.",
        ),
        MOD_ROLE: (
            "You are a Mod.",
            "You can kick, and mute or ban up to **7 days** with `/staff mute` and `/staff ban`. "
            "`/staff vanish`, `/staff tp`, `/staff tphere`, and read-only `/staff invsee` are yours. "
            "Proof is a clip and the time.\n"
            "You cannot permaban, unmute, unban, or give items. Those go to admin with the case note already written.",
        ),
        ADMIN_ROLE: (
            "You are an Admin.",
            "You can permaban, unmute, unban, refund, and `/staff item`. "
            "`/gens give`, `/gens keys`, `/gens xp`, and `/gens booster` need a reason. The server logs them.\n"
            "You may add or remove Guide and Mod only. You cannot grant Admin or Owner, and you still have no creative and no `/op`.",
        ),
        OWNER_ROLE: (
            "You have the Owner role.",
            "The owner rank is the only one with creative, `/op`, and full LuckPerms. "
            "Use the rank rooms for decisions the team must see, and leave people their private channel.",
        ),
    }
    title, body = briefs.get(rank, ("Your rank", "Read the ranks channel before you act."))
    return _embed(
        guild_name, icon_url,
        f"✦  {title}",
        body + "\n\nThis channel stays between you and the owner. Other staff cannot read it.",
        [],
        BRAND,
    )


def vent_welcome_embed(guild_name: str, icon_url: str | None) -> discord.Embed:
    embed = discord.Embed(
        title="✦  Your channel with the owner",
        description=(
            "Only you and the owner can see this. Guides, mods, and admins cannot.\n\n"
            "Use it to get something off your chest, to ask before you punish, "
            "or to flag another staff member. Don't use it to skip the ladder or to ask for a punishment you could hand to the right rank.\n"
            "Write in whatever language is easiest. Nothing here is copied to the team."
        ),
        colour=BRAND,
    )
    return _footer(embed, guild_name, icon_url)


def _icon_url(guild) -> str | None:
    return guild.icon.url if guild.icon else None


def channel_matches(name: str, logical: str) -> bool:
    slug = channel_slug(name)
    return slug == logical or slug.endswith("-" + logical)


def keep_index(rows: list[tuple[int, bool]]) -> int:
    """Pick the channel to keep. Prefer one that already holds the handbook, else the oldest id."""
    if not rows:
        raise ValueError("rows")
    best = 0
    for index, (channel_id, has_docs) in enumerate(rows):
        best_id, best_docs = rows[best]
        if has_docs and not best_docs:
            best = index
        elif has_docs == best_docs and channel_id < best_id:
            best = index
    return best


_DUTY_ON = re.compile(r"^\*\*(.+?)\*\* went on duty \(([^)]+)\)\.$")
_DUTY_OFF = re.compile(r"^\*\*(.+?)\*\* went off duty \(([^)]+)\)")


def duty_roster(lines: list[str]) -> dict[str, str]:
    """Replay clock-in and clock-out lines. The same name on two servers keeps the latest server."""
    roster: dict[str, str] = {}
    for line in lines:
        text = (line or "").strip()
        started = _DUTY_ON.match(text)
        if started:
            roster[started.group(1)] = started.group(2)
            continue
        stopped = _DUTY_OFF.match(text)
        if stopped:
            roster.pop(stopped.group(1), None)
    return roster


def roster_text(roster: dict[str, str]) -> str:
    if not roster:
        return "Nobody is on duty."
    lines = [f"**{name}** — {server}" for name, server in sorted(roster.items(), key=lambda item: item[0].lower())]
    return "On duty now:\n" + "\n".join(lines)


def find_named(guild, logical_name: str, kind: str = "text"):
    """Exact name, then slug match (🌴-staff-chat → staff-chat)."""
    pool = guild.voice_channels if kind == "voice" else guild.text_channels
    exact = discord.utils.get(pool, name=logical_name)
    if exact is not None:
        return exact
    for channel in pool:
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


def _bot_overwrite() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        manage_channels=True,
        attach_files=True,
        embed_links=True,
    )


async def _keep_bot_access(channel) -> None:
    """Grant the bot before @everyone is denied, or the next edit is Missing Access."""
    me = channel.guild.me
    if me is None:
        return
    await channel.set_permissions(me, overwrite=_bot_overwrite(), reason="staff discord: bot keeps access")


async def collapse_duplicates(guild, logical: str, kind: str):
    """Keep one channel for this room and delete the extras."""
    pool = guild.voice_channels if kind == "voice" else guild.text_channels
    matches = [channel for channel in pool if channel_matches(channel.name, logical)]
    if len(matches) <= 1:
        return matches[0] if matches else None
    rows = [
        (channel.id, kind == "text" and docs_are_current(channel.topic, logical))
        for channel in matches
    ]
    chosen = keep_index(rows)
    keep = matches[chosen]
    for index, channel in enumerate(matches):
        if index == chosen:
            continue
        try:
            await channel.delete(reason="staff discord: remove duplicate channel")
        except discord.HTTPException as exc:
            print(f"staff discord: could not remove duplicate #{channel.name} ({exc})", flush=True)
    return keep


async def collapse_categories(guild, name: str):
    """Keep one category of this name. Move rooms out of the extras, then delete those."""
    wanted = channel_slug(name)
    matches = [category for category in guild.categories if channel_slug(category.name) == wanted]
    if len(matches) <= 1:
        return matches[0] if matches else None
    keep = min(matches, key=lambda category: category.id)
    for extra in matches:
        if extra.id == keep.id:
            continue
        for child in list(extra.channels):
            try:
                await child.edit(category=keep, reason="staff discord: merge duplicate category")
            except discord.HTTPException as exc:
                print(f"staff discord: could not move #{child.name} ({exc})", flush=True)
        try:
            await extra.delete(reason="staff discord: remove duplicate category")
        except discord.HTTPException as exc:
            print(f"staff discord: could not remove duplicate category {extra.name} ({exc})", flush=True)
    return keep


async def ensure_category(guild, name: str):
    category = await collapse_categories(guild, name)
    if category is None:
        category = find_category(guild, name)
    if category is not None:
        await _keep_bot_access(category)
        await category.set_permissions(
            guild.default_role,
            view_channel=False,
            reason="staff discord: hide category",
        )
        return category, False
    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    if guild.me is not None:
        overwrites[guild.me] = _bot_overwrite()
    category = await guild.create_category(
        name, overwrites=overwrites, reason="staff discord: create category"
    )
    return category, True


async def apply_rank_mode(channel, guild, mode: str, kind: str = "text"):
    view_min = _MODE_VIEW[mode]
    send_min = _MODE_SEND[mode]
    await _keep_bot_access(channel)
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
        if kind == "voice":
            await channel.set_permissions(
                role,
                view_channel=True,
                connect=can_send,
                speak=can_send,
                stream=can_send,
                reason="staff discord: voice access",
            )
            continue
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


async def _clear_own_messages(channel) -> None:
    me = channel.guild.me
    if me is None:
        return
    async for message in channel.history(limit=50):
        if message.author.id != me.id:
            continue
        try:
            await message.delete()
        except discord.HTTPException:
            pass


async def post_channel_docs(channel, guild, logical: str, sections: dict, base_topic: str, force: bool) -> bool:
    embeds = sections.get(logical) or []
    if not embeds:
        return False
    if docs_are_current(channel.topic, logical) and not force:
        return False
    await _clear_own_messages(channel)
    for embed in embeds:
        await channel.send(embed=embed)
    marker = channel_docs_marker(logical)
    await channel.edit(topic=f"{base_topic}; {marker}"[:1024], reason="staff discord: handbook posted")
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
        if guild.me is not None:
            overwrites[guild.me] = _bot_overwrite()
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
        icon = _icon_url(guild)
        await channel.send(content=member.mention, embed=vent_welcome_embed(guild.name, icon))
        rank = highest_rank({role.name for role in member.roles})
        if rank is not None:
            await channel.send(embed=rank_brief_embed(guild.name, icon, rank))
        return "created"
    return "open"


async def announce_rank(guild, member, rank: str, include_brief: bool) -> None:
    """Tell the rank room. The private channel gets the ceiling when it is a new rank."""
    if include_brief and rank is not None:
        private = find_vent(guild, member.id)
        if private is not None:
            await private.send(embed=rank_brief_embed(guild.name, _icon_url(guild), rank))
    room_name = ROOM_FOR_RANK.get(rank)
    room = find_named(guild, room_name) if room_name else None
    if room is not None:
        await room.send(
            f"{member.mention} is now **{rank}**. The ceiling is in their channel with the owner. "
            "Read the handbook before you act past it."
        )


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


# Channel, webhook name, console command. The URL is handed to the server and never printed.
LOG_HOOKS = (
    ("duty-log", "Duty", "staff dutyhook"),
    ("punishments", "Punishments", "staff punishhook"),
    ("economy", "Economy", "staff economyhook"),
)


async def connect_duty_log(guild) -> None:
    """Create the log webhooks and hand each URL to the skyblock console."""
    import rcon_client

    for logical, hook_name, command in LOG_HOOKS:
        channel = find_named(guild, logical)
        if channel is None:
            print(f"staff discord: #{logical} is missing", flush=True)
            continue
        try:
            hook = None
            for item in await channel.webhooks():
                if item.name == hook_name and item.token:
                    hook = item
                    break
            if hook is None:
                hook = await channel.create_webhook(name=hook_name, reason="staff discord: log")
        except discord.HTTPException as exc:
            print(f"staff discord: {logical} webhook was not created ({exc})", flush=True)
            continue
        try:
            answer = rcon_client.execute(command + " " + hook.url)
        except Exception as exc:
            print(
                f"staff discord: {logical} is on Discord, server connect failed ({exc.__class__.__name__})",
                flush=True,
            )
            continue
        if "connected" not in (answer or "").lower():
            print(f"staff discord: the server did not confirm {logical}", flush=True)
            continue
        print(f"staff discord: {logical} connected to the server", flush=True)


async def refresh_roster(guild) -> None:
    """Rebuild #on-duty from the recent duty log. One bot message, replaced when it changes."""
    log = find_named(guild, "duty-log")
    board = find_named(guild, "on-duty")
    if board is None or guild.me is None:
        return
    lines: list[str] = []
    if log is not None:
        try:
            async for message in log.history(limit=200, oldest_first=True):
                if message.content:
                    lines.append(message.content)
        except discord.HTTPException as exc:
            print(f"staff discord: could not read the duty log ({exc})", flush=True)
            return
    text = roster_text(duty_roster(lines))
    existing = None
    async for message in board.history(limit=15):
        if message.author.id == guild.me.id:
            existing = message
            break
    if existing is None:
        await board.send(text)
    elif existing.content != text:
        await existing.edit(content=text)


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

    placed = []
    for category_name, channels in STAFF_LAYOUT:
        category, _ = await ensure_category(guild, category_name)
        for logical, topic, mode, kind in channels:
            channel = await collapse_duplicates(guild, logical, kind)
            if channel is None:
                if kind == "voice":
                    channel = await guild.create_voice_channel(
                        logical,
                        category=category,
                        reason="staff discord: create voice",
                    )
                else:
                    channel = await guild.create_text_channel(
                        logical,
                        category=category,
                        topic=topic,
                        reason="staff discord: create channel",
                    )
            elif kind == "text":
                # Keep a posted handbook marker. A brand-new channel still has the plain topic.
                keep = channel.topic if docs_are_current(channel.topic, logical) else (channel.topic or topic)
                await channel.edit(category=category, topic=keep, reason="staff discord: place channel")
            else:
                await channel.edit(category=category, reason="staff discord: place voice")
            await apply_rank_mode(channel, guild, mode, kind)
            placed.append((logical, topic, mode, kind, channel))

    mentions = {logical: channel.mention for logical, _topic, _mode, kind, channel in placed if kind == "text"}
    sections = handbook_sections(guild.name, _icon_url(guild), mentions)
    posted = 0
    for logical, topic, mode, kind, channel in placed:
        if mode != "docs" or kind != "text":
            continue
        if await post_channel_docs(channel, guild, logical, sections, topic, force_docs):
            posted += 1

    opened = 0
    if bot.intents.members:
        for member in guild.members:
            if holds_team_role({r.name for r in member.roles}, member.id, guild.owner_id):
                status = await open_vent(guild, member)
                if status in ("created", "open"):
                    opened += 1
    else:
        print("staff discord: DISCORD_PRIVILEGED_INTENTS=1 is required for private channels", flush=True)
    await connect_duty_log(guild)
    await refresh_roster(guild)
    print(
        f"staff discord: ready on {guild.name}, handbook pages posted: {posted}, "
        f"private channels checked: {opened}",
        flush=True,
    )
    return f"ready ({posted} handbook pages, {opened} private channels)"


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
                for logical, _, mode, kind in channels:
                    found = find_named(guild, logical, kind)
                    label = found.mention if found else f"`#{logical}` missing"
                    bits.append(f"{label} ({mode})")
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
        before_rank = highest_rank(before_names)
        after_rank = highest_rank(after_names)
        try:
            if not was and now:
                status = await open_vent(after.guild, after)
                if after_rank is not None:
                    await announce_rank(after.guild, after, after_rank, include_brief=status != "created")
            elif was and now and before_rank != after_rank and after_rank is not None:
                await announce_rank(after.guild, after, after_rank, include_brief=True)
            elif was and not now:
                await close_vent(after.guild, after)
        except discord.Forbidden:
            print(f"staff discord: could not update private channel for {after.id}", flush=True)

    bot.add_listener(on_member_update, "on_member_update")

    async def on_message(message: discord.Message):
        if message.guild is None or not is_staff_guild(message.guild) or not message.content:
            return
        if not channel_matches(message.channel.name, "duty-log"):
            return
        try:
            await refresh_roster(message.guild)
        except discord.HTTPException as exc:
            print(f"staff discord: duty board was not updated ({exc})", flush=True)

    bot.add_listener(on_message, "on_message")

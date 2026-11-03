"""Minecraft rank → Discord role planning, and the /link code book.

No Discord or RCON calls live here, so the rules can be tested on their own.
Store ranks are fully synced (highest only). Staff roles are only removed when
this bot assigned them earlier, so a hand-given Guide role is left alone.
"""

from __future__ import annotations

import hmac
import re
import time

import staff_actions

# Highest first. Display names are the Discord role names.
STORE_LADDER: tuple[tuple[str, str, int], ...] = (
    ("mogul", "Mogul", 0xFF6F00),
    ("tycoon", "Tycoon", 0x00838F),
    ("captain", "Captain", 0x1565C0),
    ("surfer", "Surfer", 0x29B6F6),
    ("islander", "Islander", 0xC9A227),
)
STAFF_LADDER: tuple[tuple[str, str], ...] = (
    ("owner", "Owner"),
    ("admin", "Admin"),
    ("mod", "Mod"),
    ("guide", "Guide"),
)
STORE_ROLE_NAMES = frozenset(display for _, display, _ in STORE_LADDER)


class RankRoom:
    """One private channel."""

    def __init__(self, name: str, topic: str, allow: tuple[str, ...]) -> None:
        self.name = name
        self.topic = topic
        self.allow = allow


# Discord rejects an ASCII "+" in channel names, so Donater+ uses a plus emoji.
DONATER_CHANNEL = "donater"
DONATER_PLUS_CHANNEL = "donater\u2795"

# Islander and Surfer share Donater. Captain, Tycoon and Mogul share Donater+.
RANK_ROOMS: tuple[RankRoom, ...] = (
    RankRoom(
        DONATER_CHANNEL,
        "Islander and Surfer. Captain and above do not have access.",
        ("Islander", "Surfer"),
    ),
    RankRoom(
        DONATER_PLUS_CHANNEL,
        "Captain, Tycoon and Mogul.",
        ("Captain", "Tycoon", "Mogul"),
    ),
)
# Previous names. Renamed when the new channel is missing, otherwise removed inside RANKS.
RANK_CHANNEL_RENAMES = {
    "below-captain": DONATER_CHANNEL,
    "above-captain": DONATER_PLUS_CHANNEL,
}
RETIRED_RANK_CHANNELS = ("captain", "below-captain", "above-captain")
RANK_CATEGORY = "RANKS"
STAFF_ROLE_NAMES = frozenset(display for _, display in STAFF_LADDER)
KNOWN_GROUPS = frozenset(
    [key for key, _, _ in STORE_LADDER] + [key for key, _ in STAFF_LADDER] + ["default"]
)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_RE = re.compile(r"^[A-Z0-9]{6}$")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,15}")
LINK_TTL_SECONDS = 600
LINK_ATTEMPTS = 5


class RankError(ValueError):
    pass


def new_code() -> str:
    import secrets

    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


def link_message_command(player: str, code: str) -> str:
    name = staff_actions.minecraft_name(player)
    if not CODE_RE.fullmatch(code or ""):
        raise RankError("Link code is invalid.")
    return (
        f"msg {name} Discord link code: {code}. "
        "In Discord, press Enter code under /link. Expires in 10 minutes."
    )


def parent_info_command(player: str) -> str:
    return f"lp user {staff_actions.minecraft_name(player)} parent info"


def whisper_failed(response: str) -> bool:
    if player_offline(response):
        return True
    text = (response or "").lower()
    return (
        "unknown command" in text
        or "must be a player" in text
        or "only players" in text
        or text.strip().startswith("usage:")
    )


def player_offline(response: str) -> bool:
    text = (response or "").lower()
    return any(
        part in text
        for part in (
            "no player was found",
            "no such player",
            "player not found",
            "is not online",
            "not online",
            "never joined",
        )
    )


def groups_response_ok(response: str) -> bool:
    text = (response or "").lower()
    if not text.strip():
        return False
    if any(
        part in text
        for part in (
            "could not find",
            "couldn't find",
            "could not be found",
            "unable to find",
            "unknown command",
            "does not exist",
            "user not found",
        )
    ):
        return False
    return "parent" in text or "group" in text or "default" in text


def parse_groups(response: str) -> set[str]:
    found: set[str] = set()
    for match in TOKEN_RE.finditer(response or ""):
        token = match.group(0).lower()
        if token in KNOWN_GROUPS:
            found.add(token)
    return found


def highest_store(groups: set[str]) -> str | None:
    for key, display, _colour in STORE_LADDER:
        if key in groups:
            return display
    return None


def highest_staff(groups: set[str]) -> str | None:
    for key, display in STAFF_LADDER:
        if key in groups:
            return display
    return None


class RolePlan:
    def __init__(
        self,
        add: tuple[str, ...],
        remove: tuple[str, ...],
        store: str | None,
        staff: str | None,
        managed_staff: str | None,
    ) -> None:
        self.add = add
        self.remove = remove
        self.store = store
        self.staff = staff
        self.managed_staff = managed_staff


def plan_roles(
    current_roles: set[str], groups: set[str], managed_staff: str | None
) -> RolePlan:
    """Which Discord roles to add or remove for one linked member."""
    store = highest_store(groups)
    staff = highest_staff(groups)
    remove: list[str] = []
    add: list[str] = []
    for name in STORE_ROLE_NAMES:
        if name in current_roles and name != store:
            remove.append(name)
    if store and store not in current_roles:
        add.append(store)
    if managed_staff and managed_staff != staff and managed_staff in current_roles:
        if managed_staff not in remove:
            remove.append(managed_staff)
    if staff and staff not in current_roles and staff not in add:
        add.append(staff)
    return RolePlan(tuple(add), tuple(remove), store, staff, staff)


class LinkDirectory:
    """In-memory link book. Pending codes expire; a name can only be linked once."""

    def __init__(self) -> None:
        self.links: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}

    def owner_of(self, name: str) -> str | None:
        wanted = name.casefold()
        for discord_id, row in self.links.items():
            if str(row.get("name", "")).casefold() == wanted:
                return discord_id
        return None

    def get(self, discord_id: str) -> dict | None:
        row = self.links.get(str(discord_id))
        return dict(row) if row else None

    def start(self, discord_id: str, name: str, code: str, now: float) -> tuple[str, str | None]:
        discord_id = str(discord_id)
        safe = staff_actions.minecraft_name(name)
        if not CODE_RE.fullmatch(code or ""):
            raise RankError("Link code is invalid.")
        owner = self.owner_of(safe)
        if owner and owner != discord_id:
            return code, "That Minecraft account is already linked to another Discord user."
        if discord_id in self.links:
            return code, "You are already linked. Use /unlink first."
        current = self.pending.get(discord_id)
        if (
            current
            and str(current.get("name", "")).casefold() == safe.casefold()
            and float(current.get("expires", 0)) > now
        ):
            return str(current["code"]), None
        self.pending[discord_id] = {
            "name": safe,
            "code": code,
            "expires": now + LINK_TTL_SECONDS,
            "tries": 0,
        }
        return code, None

    def confirm(self, discord_id: str, code: str, now: float) -> tuple[str | None, str | None]:
        discord_id = str(discord_id)
        row = self.pending.get(discord_id)
        if not row:
            return None, "No link in progress. Run /link first."
        if float(row.get("expires", 0)) <= now:
            self.pending.pop(discord_id, None)
            return None, "That code expired. Run /link again while you are online."
        given = "".join(ch for ch in (code or "").upper() if ch.isalnum())
        if not hmac.compare_digest(given, str(row["code"])):
            row["tries"] = int(row.get("tries", 0)) + 1
            if row["tries"] >= LINK_ATTEMPTS:
                self.pending.pop(discord_id, None)
                return None, "Too many wrong codes. Run /link again."
            return None, "That code does not match. Check the message on the server."
        name = str(row["name"])
        owner = self.owner_of(name)
        if owner and owner != discord_id:
            self.pending.pop(discord_id, None)
            return None, "That Minecraft account is already linked to another Discord user."
        self.links[discord_id] = {
            "name": name,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "managed_staff": None,
        }
        self.pending.pop(discord_id, None)
        return name, None

    def unlink(self, discord_id: str) -> dict | None:
        discord_id = str(discord_id)
        self.pending.pop(discord_id, None)
        return self.links.pop(discord_id, None)

    def set_managed_staff(self, discord_id: str, role: str | None) -> None:
        row = self.links.get(str(discord_id))
        if row is not None:
            row["managed_staff"] = role

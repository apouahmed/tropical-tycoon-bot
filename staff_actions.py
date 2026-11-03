"""Build owner-only console commands for the Staff Control Center.

Names and free text are checked here so a Discord field cannot change the command
that gets sent over RCON. The Minecraft server still enforces permissions and amounts.
"""

from __future__ import annotations

import re

MINECRAFT_NAME = re.compile(r"^(?:\.[A-Za-z0-9_]{1,15}|[A-Za-z0-9_]{1,16})$")
TX_ID = re.compile(r"^tx:[A-Za-z0-9_-]{1,61}$")

SERVERS = ("hub", "skyblock", "boss")
EVENTS = ("gen-overload", "sell-frenzy", "lucky-drops")
BOOSTERS = ("sell", "speed", "xp")
KEY_TYPES = ("mystery", "monthly")
STORE_RANKS = ("islander", "surfer", "captain", "tycoon", "mogul")
PET_TYPES = (
    "hermit_crab",
    "parrot",
    "coconut_crab",
    "sea_turtle",
    "toucan",
    "flamingo",
    "monkey",
    "dolphin",
    "manta_ray",
    "reef_shark",
    "golden_crab",
    "tiki_spirit",
    "kraken",
    "pumpkin_king",
)
PET_MAX_LEVEL = 50
KEY_MAX = 64
XP_MAX = 100_000_000
BOOSTER_PERCENT_MAX = 500
BOOSTER_MINUTES_MAX = 24 * 60


class ActionError(ValueError):
    """The Discord input cannot be turned into a safe console command."""


def minecraft_name(raw: str) -> str:
    name = (raw or "").strip()
    if not MINECRAFT_NAME.fullmatch(name):
        raise ActionError(
            "Minecraft name must be 1–16 letters, numbers or underscores "
            "(Bedrock names may start with a dot)."
        )
    return name


def plain_text(raw: str, *, min_len: int, max_len: int, label: str) -> str:
    text = " ".join((raw or "").replace("\r", " ").replace("\n", " ").split())
    cleaned = "".join(ch for ch in text if ch.isalnum() or ch in " .,!?'-:/")
    cleaned = " ".join(cleaned.split())
    if len(cleaned) < min_len or len(cleaned) > max_len:
        raise ActionError(f"{label} must be {min_len}–{max_len} characters.")
    return cleaned


def delivery_tx(raw: str) -> str:
    tx = (raw or "").strip()
    if not TX_ID.fullmatch(tx):
        raise ActionError("Transaction id is invalid.")
    return tx


def profile_commands(player: str) -> tuple[str, str]:
    name = minecraft_name(player)
    return (f"balance {name}", f"lp user {name} info")


def move_command(player: str, server: str) -> str:
    target = (server or "").strip().lower()
    if target not in SERVERS:
        raise ActionError("Server must be hub, skyblock or boss.")
    return f"gens send {minecraft_name(player)} {target}"


def kick_command(player: str, reason: str) -> str:
    why = plain_text(reason, min_len=3, max_len=80, label="Kick reason")
    return f"kick {minecraft_name(player)} {why}"


def announce_command(message: str) -> str:
    text = plain_text(message, min_len=2, max_len=180, label="Announcement")
    return f"say {text}"


def xp_command(player: str, amount: int) -> str:
    if amount < 1 or amount > XP_MAX:
        raise ActionError(f"XP must be 1–{XP_MAX}.")
    return f"gens xp {minecraft_name(player)} {amount}"


def vote_command(player: str) -> str:
    return f"gens vote {minecraft_name(player)} discord"


def keys_command(player: str, amount: int, kind: str, tx: str) -> str:
    crate = (kind or "").strip().lower() or "mystery"
    if crate not in KEY_TYPES:
        raise ActionError("Key type must be mystery or monthly.")
    if amount < 1 or amount > KEY_MAX:
        raise ActionError(f"Amount must be 1–{KEY_MAX}.")
    token = delivery_tx(tx)
    name = minecraft_name(player)
    if crate == "monthly":
        return f"gens keys {name} monthly {amount} {token}"
    return f"gens keys {name} mystery {amount} {token}"


def booster_command(player: str, kind: str, percent: int, minutes: int, tx: str) -> str:
    booster = (kind or "").strip().lower()
    if booster not in BOOSTERS:
        raise ActionError("Booster type must be sell, speed or xp.")
    if percent < 1 or percent > BOOSTER_PERCENT_MAX or minutes < 1 or minutes > BOOSTER_MINUTES_MAX:
        raise ActionError(
            f"Percent 1–{BOOSTER_PERCENT_MAX}, minutes 1–{BOOSTER_MINUTES_MAX}."
        )
    return (
        f"gens booster {minecraft_name(player)} {booster} {percent} {minutes} "
        f"free discord {delivery_tx(tx)}"
    )


def store_command(player: str, rank: str, tx: str) -> str:
    chosen = (rank or "").strip().lower()
    if chosen not in STORE_RANKS:
        raise ActionError("Rank must be one of: " + ", ".join(STORE_RANKS) + ".")
    return f"gens store {minecraft_name(player)} {chosen} {delivery_tx(tx)}"


def pet_command(player: str, pet: str, level: int, reason: str, tx: str) -> str:
    kind = (pet or "").strip().lower().replace(" ", "_")
    if kind not in PET_TYPES:
        raise ActionError("Unknown pet. Use a type such as hermit_crab or reef_shark.")
    if level < 1 or level > PET_MAX_LEVEL:
        raise ActionError(f"Pet level must be 1–{PET_MAX_LEVEL}.")
    why = plain_text(reason, min_len=3, max_len=80, label="Reason")
    return f"pets give {minecraft_name(player)} {kind} {level} {why} {delivery_tx(tx)}"


def event_command(choice: str) -> str:
    if choice == "stop":
        return "gens event stop"
    parts = (choice or "").split(":")
    if len(parts) != 3 or parts[0] != "start" or parts[1] not in EVENTS:
        raise ActionError("Unknown event action.")
    try:
        minutes = int(parts[2])
    except ValueError as e:
        raise ActionError("Event minutes must be a number.") from e
    if minutes < 1 or minutes > 180:
        raise ActionError("Event length must be 1–180 minutes.")
    return f"gens event start {parts[1]} {minutes}"

# Tropical Tycoon Discord bot

Tickets, welcome, rules/FAQ, `/setupdiscord`, Java/Bedrock roles, and an owner-only Staff Control Center.

## What the bot can do
Anyone: `/rules`, `/play`, `/link`, `/unlink`, `/ranksync`.
Staff in a ticket: `/add`, `/remove`.
Admin: `/setupdiscord`, `/setupperms`, `/panel`, `/postrules`, `/postfaq`.
Server owner: `/manage` plus `/lookup`, `/givekeys`, `/givexp`, `/move`, `/kick`, `/announce`, `/serverstatus`, `/acrecent`.

## Rank roles
`/link` asks for your Minecraft name and whispers a code in-game (you must be online). Enter that code in Discord. The bot then reads your LuckPerms groups and sets one store role (Islander, Surfer, Captain, Tycoon or Mogul). Staff groups (Guide, Mod, Admin, Owner) are applied the same way. A role this bot did not assign is left in place.

Every `RANK_SYNC_MINUTES` (default 10) it checks linked accounts again, including after a Tebex rank. `/ranksync` refreshes you immediately. A store rank granted from `/manage` refreshes that linked member too.

The bot's own role must sit above those rank roles, and it needs **Manage Roles**. RCON has to be set or `/link` cannot whisper the code.

`/manage` opens modules for fishing AC, player profiles, kicks and announcements, economy grants (keys, boosters, Tycoon XP, pets, store ranks), the live events (Gen Overload, Sell Frenzy, Lucky Drops), and network status. Grants that the server can dedupe end with a Discord transaction id. Console actions need `RCON_HOST`, `RCON_PORT` and `RCON_PASSWORD`. Audits go to `STAFF_LOG_WEBHOOK` when set.

## Wispbyte
1. Repository: this repo (private) — branch `main`
2. GitHub username + PAT (Contents: Read)
3. `PY_FILE` = `main.py`
4. `REQUIREMENTS_FILE` = `requirements.txt`
5. `AUTO_UPDATE` = `1`
6. Variables: `DISCORD_TOKEN`, `DISCORD_PRIVILEGED_INTENTS=1`, plus `RCON_HOST`, `RCON_PORT`, `RCON_PASSWORD` if the owner tools should reach the skyblock console. Optional: `STAFF_LOG_WEBHOOK`, `AC_LOG_CHANNEL_ID`.
7. Start → in Discord run `/setupdiscord` then `/setupdiscord confirm:True`

Bot needs **Manage Channels** + **Manage Roles** (its role above Member, Java, Bedrock and the rank roles).

## Local
```bash
cp .env.example .env   # set DISCORD_TOKEN
pip install -r requirements.txt
python main.py
```

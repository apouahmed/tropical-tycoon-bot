# Tropical Tycoon Discord bot

Tickets, welcome, rules/FAQ, `/setupdiscord`, Java/Bedrock roles.

## Wispbyte
1. Repository: this repo (private) — branch `main`
2. GitHub username + PAT (Contents: Read)
3. `PY_FILE` = `main.py`
4. `REQUIREMENTS_FILE` = `requirements.txt`
5. `AUTO_UPDATE` = `1`
6. Variables: `DISCORD_TOKEN`, `DISCORD_PRIVILEGED_INTENTS=1`
7. Start → in Discord run `/setupdiscord` then `/setupdiscord confirm:True`

Bot needs **Manage Channels** + **Manage Roles** (role above Member/Java/Bedrock).

## Local
```bash
cp .env.example .env   # set DISCORD_TOKEN
pip install -r requirements.txt
python main.py
```

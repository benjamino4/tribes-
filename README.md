# Tribes \u2014 Telegram Mini App

A Web3 community airdrop project themed on the dawn of humanity. You earn
allocation **with your tribe**, through loyalty and consistency \u2014 never wealth
or headcount. Small fierce tribes beat big lazy ones.

## Two-currency economy

- **Ember** \u2014 your personal currency. Earned by your own actions (daily check-in,
  quests, relics, streaks). Drives your personal airdrop share. Never spent.
- **Loyalty** \u2014 the tribal Hearth pool. A tithe of each member's Ember plus
  tribe bonuses. Spent to upgrade the settlement. Tribes rank by **average
  Loyalty earned per member**, so ghosts and bot-farms only drag you down.

## Screens

Fire (home/campfire) \u00b7 Tribe (Hearth, roster, War Cry, Cave Wall, Beat the Drum)
\u00b7 Ranks (Tribes + Kin) \u00b7 Lands (territory) \u00b7 Sky (Star-Lore + Store) \u00b7 Claim (TON wallet).

## Integrations

- **Aiven Postgres** via `DATABASE_URL` (SSL). Falls back to local SQLite if unset.
- **Telegram Stars** for the cosmetic/convenience Store (`createInvoiceLink` +
  webhook). Never sells Ember, Loyalty, rank, or allocation.
- **TON Connect** wallet binding on the Claim screen.

## Configuration (secrets \u2014 you keep them)

Set these as environment variables on Render (Environment tab). They are never
hard-coded or committed.

| Var | What | Where |
|-----|------|-------|
| `DATABASE_URL` | Aiven Postgres connection string | required for persistence |
| `BOT_TOKEN` | BotFather token | required for production + real Stars |
| `PORT` | provided by Render automatically | \u2014 |

Without `BOT_TOKEN` the app runs in **DEV MODE**: it trusts a demo user, seeds
demo tribes, and the Store uses an offline demo Star balance.

## Run locally

```bash
pip install -r requirements.txt
python main.py            # http://localhost:8000
```

Optional local secrets in a `.env`-style shell export (never commit real values):

```bash
export DATABASE_URL="postgres://..."
export BOT_TOKEN="123:abc"
python main.py
```

## Deploy on Render (flat repo)

- Root Directory: **blank**
- Build: `pip install -r requirements.txt`
- Start: `python main.py`
- Env vars: `DATABASE_URL`, `BOT_TOKEN`

## Wire the bot to Telegram

1. BotFather \u2192 set the Mini App / menu button URL to your Render HTTPS URL.
2. For Stars payments, register the webhook:
   `https://api.telegram.org/bot<token>/setWebhook?url=https://YOUR-APP.onrender.com/api/telegram/webhook`
3. Update `tonconnect-manifest.json` `url`/`iconUrl` to your Render URL (the app
   also serves an auto-filled manifest at `/tonconnect-manifest.json`).

## Tuning

Every economy knob \u2014 Ember rewards, tithe %, decay, the 11-tier settlement
ladder, lands, store prices, Age length \u2014 lives in `config.json`. Edit and refresh;
no code change needed.

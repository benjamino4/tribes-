"""
TRIBES — Telegram Mini App backend (FastAPI).

A Web3 community airdrop project themed on the dawn of humanity. Loyalty and
consistency earn allocation — never wealth or headcount.

Economy:
  EMBER   — personal currency. Earned by YOUR actions (check-in, quests, relics,
            streaks). Drives your personal airdrop share. Never spent.
  LOYALTY — tribal Hearth pool. A tithe of each member's Ember plus tribe
            bonuses. Spent to upgrade the settlement. Tribes are ranked by
            cumulative Loyalty EARNED per member (spending never lowers rank).

Integrations:
  * Postgres (Aiven) via DATABASE_URL, SQLite fallback for local dev.
  * Telegram Stars payments (createInvoiceLink + webhook), demo fallback.
  * TON Connect wallet at claim time.

Secrets are read ONLY from env vars: DATABASE_URL, BOT_TOKEN. Never hard-coded.
"""
import hashlib
import hmac
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
USE_PG = DATABASE_URL.startswith("postgres")

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row
    
    def get_db_connection():
        # Connect to Aiven PostgreSQL using psycopg (v3) matching your requirements.txt
        return psycopg.connect(DATABASE_URL)
else:
    import sqlite3
  
def get_db_connection():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
# -------------------------------------------
_HERE = Path(__file__).resolve().parent
if (_HERE.parent / "frontend").is_dir():
    BASE_DIR = _HERE.parent
    FRONTEND_DIR = BASE_DIR / "frontend"
    _RES_DIR = _HERE
else:
    BASE_DIR = _HERE
    FRONTEND_DIR = _HERE
    _RES_DIR = _HERE

DB_PATH = Path(os.environ.get("TRIBES_DB", BASE_DIR / "tribes.db"))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DEV_MODE = not BOT_TOKEN
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = DATABASE_URL.startswith("postgres")

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row

CONFIG_FILE = _RES_DIR / "config.json"


def cfg() -> dict:
    """Load tunable economy config on every call so edits show up on refresh."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def ladder() -> list:
    return cfg().get("settlement_ladder", [])


def ladder_at(level: int) -> dict:
    for row in ladder():
        if int(row["level"]) == int(level):
            return row
    return {"level": level, "stage": "Campfire", "max_members": 5, "invites_per_day": 2, "cost": 0}


app = FastAPI(title="Tribes Mini App")

# --------------------------------------------------------------------------- #
# Database                                                                     #
# --------------------------------------------------------------------------- #
def _translate(sql: str) -> str:
    if not USE_PG:
        return sql
    s = sql
    if "INSERT OR IGNORE" in s:
        s = s.replace("INSERT OR IGNORE INTO", "INSERT INTO").rstrip()
        if "ON CONFLICT" not in s:
            s = s + " ON CONFLICT DO NOTHING"
    return s.replace("?", "%s")


class _Conn:
    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        return self._raw.execute(_translate(sql), params)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            if not USE_PG:
                self._raw.commit()
        finally:
            self._raw.close()
        return False


def db() -> _Conn:
    if USE_PG:
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        return _Conn(psycopg.connect(url, autocommit=True, row_factory=dict_row))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return _Conn(conn)


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tribes (
                tribe_id       TEXT PRIMARY KEY,
                name           TEXT NOT NULL,
                level          INTEGER NOT NULL DEFAULT 1,
                loyalty_bal    INTEGER NOT NULL DEFAULT 0,
                loyalty_earned INTEGER NOT NULL DEFAULT 0,
                war_cry        TEXT NOT NULL DEFAULT '',
                color          TEXT NOT NULL DEFAULT '#ff7a18',
                crest          TEXT NOT NULL DEFAULT '\U0001F525',
                land           TEXT NOT NULL DEFAULT '',
                created_ts     INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id        TEXT PRIMARY KEY,
                name           TEXT NOT NULL DEFAULT 'Kin',
                tribe_id       TEXT,
                phone_verified INTEGER NOT NULL DEFAULT 0,
                supporter      INTEGER NOT NULL DEFAULT 0,
                freezes        INTEGER NOT NULL DEFAULT 0,
                drum_extra     INTEGER NOT NULL DEFAULT 0,
                stars_demo     INTEGER NOT NULL DEFAULT 100,
                created_ts     INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkins (
                user_id TEXT NOT NULL,
                day     TEXT NOT NULL,
                ts      INTEGER NOT NULL,
                PRIMARY KEY (user_id, day)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS completions (
                user_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                day     TEXT NOT NULL,
                ts      INTEGER NOT NULL,
                PRIMARY KEY (user_id, task_id, day)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS relics (
                user_id TEXT NOT NULL,
                relic_id TEXT NOT NULL,
                ts      INTEGER NOT NULL,
                PRIMARY KEY (user_id, relic_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wallets (
                user_id TEXT PRIMARY KEY,
                address TEXT NOT NULL,
                ts      INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cave_wall (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                tribe_id TEXT NOT NULL,
                author   TEXT NOT NULL,
                text     TEXT NOT NULL,
                ts       INTEGER NOT NULL
            )
            """
            if not USE_PG else
            """
            CREATE TABLE IF NOT EXISTS cave_wall (
                id       SERIAL PRIMARY KEY,
                tribe_id TEXT NOT NULL,
                author   TEXT NOT NULL,
                text     TEXT NOT NULL,
                ts       INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hunts (
                tribe_id TEXT NOT NULL,
                day      TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                won      INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (tribe_id, day)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drum_calls (
                user_id TEXT NOT NULL,
                day     TEXT NOT NULL,
                count   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                charge_id TEXT PRIMARY KEY,
                user_id   TEXT NOT NULL,
                item      TEXT NOT NULL,
                stars     INTEGER NOT NULL,
                ts        INTEGER NOT NULL
            )
            """
        )


init_db()

# --------------------------------------------------------------------------- #
# Telegram identity                                                            #
# --------------------------------------------------------------------------- #
def validate_init_data(init_data: str) -> dict:
    """Validate Telegram WebApp initData (HMAC-SHA256). DEV_MODE trusts a plain
    user_id for local testing when BOT_TOKEN is unset."""
    if DEV_MODE:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        uid = pairs.get("user_id") or "dev-user"
        return {"id": str(uid), "first_name": pairs.get("first_name", "Kin")}

    if not init_data:
        raise HTTPException(status_code=401, detail="missing initData")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="missing hash")
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs.keys()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        raise HTTPException(status_code=401, detail="invalid signature")
    auth_date = int(pairs.get("auth_date", "0"))
    if auth_date and time.time() - auth_date > 86400:
        raise HTTPException(status_code=401, detail="initData expired")
    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=401, detail="bad user payload")
    if "id" not in user:
        raise HTTPException(status_code=401, detail="no user id")
    user["id"] = str(user["id"])
    return user


async def get_user(request: Request) -> dict:
    init_data = request.headers.get("X-Init-Data", "")
    if not init_data and request.method == "POST":
        try:
            body = await request.json()
            init_data = body.get("initData", "") if isinstance(body, dict) else ""
        except Exception:
            init_data = ""
    return validate_init_data(init_data)


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def week_key() -> str:
    iso = datetime.now(timezone.utc).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# --------------------------------------------------------------------------- #
# Users & tribes                                                               #
# --------------------------------------------------------------------------- #
ADJ = ["Ember", "Ashen", "Flint", "Dawn", "Wild", "Stone", "River", "Storm", "Iron", "Bright"]
NOUN = ["Wolves", "Ravens", "Bison", "Hawks", "Bears", "Stags", "Foxes", "Lions", "Elk", "Owls"]


def _slug(uid: str) -> int:
    return int(hashlib.sha256(uid.encode()).hexdigest(), 16)


def ensure_user(conn, uid: str, name: str = "Kin") -> dict:
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
    now = int(time.time())
    if not row:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, name, created_ts) VALUES (?, ?, ?)",
            (uid, (name or "Kin")[:40], now),
        )
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
    elif name and name != "Kin" and row["name"] != name:
        conn.execute("UPDATE users SET name = ? WHERE user_id = ?", (name[:40], uid))
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
    return dict(row)


def auto_place(conn, uid: str) -> str:
    """Drop a tribeless kin into an open tribe, or found a fresh Campfire so they
    never start alone."""
    rows = conn.execute("SELECT tribe_id, level FROM tribes").fetchall()
    for t in rows:
        cap = ladder_at(t["level"])["max_members"]
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE tribe_id = ?", (t["tribe_id"],)
        ).fetchone()["c"]
        if n < cap:
            conn.execute("UPDATE users SET tribe_id = ? WHERE user_id = ?", (t["tribe_id"], uid))
            return t["tribe_id"]
    # none open -> found a new one
    s = _slug(uid + str(time.time()))
    tid = f"t_{s % 10_000_000}"
    name = f"{ADJ[s % len(ADJ)]} {NOUN[(s // 7) % len(NOUN)]}"
    land = cfg().get("lands", ["The Great Rift"])[s % max(1, len(cfg().get("lands", [1])))]
    conn.execute(
        "INSERT OR IGNORE INTO tribes (tribe_id, name, land, created_ts) VALUES (?, ?, ?, ?)",
        (tid, name, land, int(time.time())),
    )
    conn.execute("UPDATE users SET tribe_id = ? WHERE user_id = ?", (tid, uid))
    return tid

# --------------------------------------------------------------------------- #
# Economy: streak, Ember (personal), Loyalty (tribal Hearth)                    #
# --------------------------------------------------------------------------- #
def streak_of(days: set) -> int:
    today = date.fromisoformat(today_iso())
    cursor = today
    if cursor.isoformat() not in days:
        cursor = cursor - timedelta(days=1)
    streak = 0
    while cursor.isoformat() in days:
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak


def streak_bonus(streak: int, c: dict) -> int:
    e = c.get("ember", {})
    return min(int(streak) * int(e.get("streak_bonus_per_day", 2)), int(e.get("streak_bonus_cap", 40)))


def resolve_tasks(days, streak, wallet, manual_today, manual_ever, c):
    today = today_iso()
    out = []
    for t in c.get("tasks", []):
        kind = t.get("kind", "manual")
        if kind == "checkin":
            done = today in days
        elif kind == "streak":
            done = streak >= int(t.get("target", 3))
        elif kind == "wallet":
            done = wallet is not None
        elif t.get("repeat") == "once":
            done = t["id"] in manual_ever
        else:
            done = t["id"] in manual_today
        out.append({**t, "done": done})
    return out


def compute_ember(conn, uid: str) -> dict:
    """Deterministically compute a user's personal Ember from their history so
    the number can never be double-credited. Ember never gets spent."""
    c = cfg()
    e = c.get("ember", {})
    rows = conn.execute("SELECT day FROM checkins WHERE user_id = ? ORDER BY day DESC", (uid,)).fetchall()
    days = {r["day"] for r in rows}
    total_days = len(days)
    streak = streak_of(days)
    comp = conn.execute("SELECT task_id, day FROM completions WHERE user_id = ?", (uid,)).fetchall()
    today = today_iso()
    manual_today = {r["task_id"] for r in comp if r["day"] == today}
    manual_ever = {r["task_id"] for r in comp}
    relic_rows = conn.execute("SELECT relic_id FROM relics WHERE user_id = ?", (uid,)).fetchall()
    wrow = conn.execute("SELECT address FROM wallets WHERE user_id = ?", (uid,)).fetchone()
    wallet = wrow["address"] if wrow else None

    tasks = resolve_tasks(days, streak, wallet, manual_today, manual_ever, c)

    ember = total_days * int(e.get("checkin", 10))
    ember += streak_bonus(streak, c)
    ember += len(relic_rows) * int(e.get("relic_find", 25))
    ember += sum(int(t.get("reward", 0)) for t in tasks if t["done"])

    # decay: idle days beyond a grace period gently erode Ember
    if days:
        last = max(date.fromisoformat(d) for d in days)
        idle = (date.fromisoformat(today) - last).days
        grace = int(e.get("decay_grace_days", 3))
        if idle > grace:
            ember -= (idle - grace) * int(e.get("decay_per_idle_day", 3))
    ember = max(0, ember)

    heat = []
    for i in range(6, -1, -1):
        d = (date.fromisoformat(today) - timedelta(days=i)).isoformat()
        heat.append({"day": d, "active": d in days})

    return {
        "ember": ember, "streak": streak, "total_days": total_days,
        "today": today in days, "tasks": tasks, "heatmap": heat,
        "relics": [r["relic_id"] for r in relic_rows], "wallet": wallet,
    }


def credit_loyalty(conn, tribe_id: str, amount: int) -> None:
    if not tribe_id or amount <= 0:
        return
    conn.execute(
        "UPDATE tribes SET loyalty_bal = loyalty_bal + ?, loyalty_earned = loyalty_earned + ? WHERE tribe_id = ?",
        (int(amount), int(amount), tribe_id),
    )


def tribe_member_count(conn, tribe_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM users WHERE tribe_id = ?", (tribe_id,)
    ).fetchone()["c"]


def tribe_summary(conn, tribe_id: str) -> dict:
    t = conn.execute("SELECT * FROM tribes WHERE tribe_id = ?", (tribe_id,)).fetchone()
    if not t:
        return {}
    t = dict(t)
    members = tribe_member_count(conn, tribe_id)
    lvl = int(t["level"])
    cur = ladder_at(lvl)
    nxt = ladder_at(lvl + 1) if lvl < len(ladder()) else None
    avg = (t["loyalty_earned"] / members) if members else 0
    return {
        "tribe_id": tribe_id, "name": t["name"], "level": lvl, "stage": cur["stage"],
        "members": members, "max_members": cur["max_members"], "invites_per_day": cur["invites_per_day"],
        "loyalty_bal": int(t["loyalty_bal"]), "loyalty_earned": int(t["loyalty_earned"]),
        "avg_loyalty": round(avg, 1), "war_cry": t["war_cry"], "color": t["color"],
        "crest": t["crest"], "land": t["land"],
        "next": ({"stage": nxt["stage"], "cost": nxt["cost"], "max_members": nxt["max_members"],
                  "invites_per_day": nxt["invites_per_day"]} if nxt else None),
    }

# --------------------------------------------------------------------------- #
# Aggregated state, leaderboards, lands, allocation                            #
# --------------------------------------------------------------------------- #
DRUM_FREE_PER_DAY = 1
HUNT_TARGET_BASE = 30      # base daily-hunt goal; scales with tribe size


def hunt_target(members: int) -> int:
    return HUNT_TARGET_BASE + max(0, members - 1) * 8


def drum_calls_left(conn, uid: str, extra: int) -> int:
    row = conn.execute(
        "SELECT count FROM drum_calls WHERE user_id = ? AND day = ?", (uid, today_iso())
    ).fetchone()
    used = int(row["count"]) if row else 0
    return max(0, DRUM_FREE_PER_DAY + extra - used)


def allocation_preview(conn, uid: str, my_ember: int) -> dict:
    """Off-chain estimate of this kin's share if the Age ended now: your Ember
    over the whole population's Ember (v1 is illustrative only)."""
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    total = 0
    for r in rows:
        total += compute_ember(conn, r["user_id"])["ember"]
    pct = (my_ember / total * 100.0) if total else 0.0
    return {"your_ember": my_ember, "total_ember": total, "share_pct": round(pct, 3)}


def compute_state(uid: str, name: str = "Kin") -> dict:
    with db() as conn:
        u = ensure_user(conn, uid, name)
        if not u.get("tribe_id"):
            auto_place(conn, uid)
            u = ensure_user(conn, uid, name)
        em = compute_ember(conn, uid)
        tribe = tribe_summary(conn, u["tribe_id"]) if u.get("tribe_id") else {}
        # daily hunt for the tribe
        hunt = {"progress": 0, "target": 0, "won": False}
        if u.get("tribe_id"):
            members = tribe.get("members", 1)
            hrow = conn.execute(
                "SELECT progress, won FROM hunts WHERE tribe_id = ? AND day = ?",
                (u["tribe_id"], today_iso()),
            ).fetchone()
            prog = int(hrow["progress"]) if hrow else 0
            hunt = {"progress": prog, "target": hunt_target(members), "won": bool(hrow["won"]) if hrow else False}
        drums = drum_calls_left(conn, uid, int(u.get("drum_extra", 0)))
        alloc = allocation_preview(conn, uid, em["ember"])

    c = cfg()
    state = {
        "name": u["name"], "dev_mode": DEV_MODE,
        "ember": em["ember"], "streak": em["streak"], "total_days": em["total_days"],
        "today": em["today"], "tasks": em["tasks"], "heatmap": em["heatmap"],
        "relics": em["relics"], "wallet": em["wallet"],
        "supporter": bool(u.get("supporter", 0)), "freezes": int(u.get("freezes", 0)),
        "drum_calls_left": drums, "phone_verified": bool(u.get("phone_verified", 0)),
        "stars_demo": int(u.get("stars_demo", 0)),
        "tribe": tribe, "hunt": hunt, "allocation": alloc,
        "age": c.get("age", {}), "lands": c.get("lands", []),
        "store": c.get("store", {}).get("items", []),
        "ladder": ladder(),
        "payments_live": not DEV_MODE,
    }
    return state


def kin_leaderboard(conn, current_uid: str, limit: int = 50) -> dict:
    rows = conn.execute("SELECT user_id, name, supporter FROM users").fetchall()
    entries = []
    for r in rows:
        em = compute_ember(conn, r["user_id"])
        entries.append({"user_id": r["user_id"], "name": r["name"], "ember": em["ember"],
                        "streak": em["streak"], "supporter": bool(r["supporter"])})
    entries.sort(key=lambda x: (x["ember"], x["streak"]), reverse=True)
    board, me = [], None
    for i, e in enumerate(entries):
        item = {"rank": i + 1, "name": e["name"], "ember": e["ember"], "streak": e["streak"],
                "supporter": e["supporter"], "you": e["user_id"] == current_uid}
        if item["you"]:
            me = item
        if i < limit:
            board.append(item)
    return {"board": board, "me": me, "count": len(entries)}


def tribe_leaderboard(conn, current_tribe: str, limit: int = 50) -> dict:
    rows = conn.execute("SELECT * FROM tribes").fetchall()
    entries = []
    for t in rows:
        members = tribe_member_count(conn, t["tribe_id"])
        avg = (t["loyalty_earned"] / members) if members else 0
        entries.append({"tribe_id": t["tribe_id"], "name": t["name"], "crest": t["crest"],
                        "stage": ladder_at(t["level"])["stage"], "members": members,
                        "avg_loyalty": round(avg, 1), "loyalty_earned": int(t["loyalty_earned"]),
                        "color": t["color"], "land": t["land"]})
    entries.sort(key=lambda x: (x["avg_loyalty"], x["loyalty_earned"]), reverse=True)
    board, me, rival = [], None, None
    for i, e in enumerate(entries):
        item = {"rank": i + 1, **e, "you": e["tribe_id"] == current_tribe}
        if item["you"]:
            me = item
            if i + 1 < len(entries):
                nb = entries[i - 1] if i > 0 else entries[i + 1]
                rival = {"rank": (i if i > 0 else i + 2), "name": nb["name"], "crest": nb["crest"],
                         "avg_loyalty": nb["avg_loyalty"]}
        if i < limit:
            board.append(item)
    return {"board": board, "me": me, "rival": rival, "count": len(entries)}


def lands_state(conn) -> list:
    """Which tribe holds each Land = tribe with the most members currently sitting
    on it (v1 proxy for activity). Tribes are assigned a home land on founding."""
    lands = cfg().get("lands", [])
    holders = {}
    rows = conn.execute("SELECT tribe_id, name, crest, color, land, loyalty_earned FROM tribes").fetchall()
    for t in rows:
        land = t["land"]
        if not land:
            continue
        cur = holders.get(land)
        if not cur or t["loyalty_earned"] > cur["loyalty_earned"]:
            holders[land] = {"tribe_id": t["tribe_id"], "name": t["name"], "crest": t["crest"],
                             "color": t["color"], "loyalty_earned": int(t["loyalty_earned"])}
    return [{"land": ln, "holder": holders.get(ln)} for ln in lands]

# --------------------------------------------------------------------------- #
# Store item effects (cosmetic / convenience ONLY — never rank/allocation)      #
# --------------------------------------------------------------------------- #
def store_item(item_id: str) -> dict:
    for it in cfg().get("store", {}).get("items", []):
        if it["id"] == item_id:
            return it
    return {}


def grant_item(conn, uid: str, item_id: str, value: str = "") -> bool:
    """Apply a purchased item's effect. Returns False for unknown items.
    IMPORTANT: none of these touch Ember, Loyalty, rank, or allocation."""
    it = store_item(item_id)
    if not it:
        return False
    kind = it.get("kind")
    if kind == "freeze":
        conn.execute("UPDATE users SET freezes = freezes + 1 WHERE user_id = ?", (uid,))
    elif kind == "cosmetic_user":
        conn.execute("UPDATE users SET supporter = 1 WHERE user_id = ?", (uid,))
    elif kind == "convenience":
        conn.execute("UPDATE users SET drum_extra = drum_extra + 3 WHERE user_id = ?", (uid,))
    elif kind == "cosmetic_tribe":
        u = conn.execute("SELECT tribe_id FROM users WHERE user_id = ?", (uid,)).fetchone()
        crest = (value or "").strip()[:4] or "\U0001F531"
        if u and u["tribe_id"]:
            conn.execute("UPDATE tribes SET crest = ? WHERE tribe_id = ?", (crest, u["tribe_id"]))
    return True


# --------------------------------------------------------------------------- #
# Demo seed (DEV_MODE only) so leaderboards & lands aren't empty               #
# --------------------------------------------------------------------------- #
def seed_demo() -> None:
    if not DEV_MODE:
        return
    with db() as conn:
        if conn.execute("SELECT 1 FROM tribes WHERE tribe_id LIKE 'demo_%' LIMIT 1").fetchone():
            return
        lands = cfg().get("lands", ["The Great Rift"])
        now = int(time.time())
        demo_tribes = [
            ("demo_wolves", "Ashen Wolves", 4, 52000, "\U0001F43A", "#ff5a3c"),
            ("demo_ravens", "Storm Ravens", 3, 28000, "\U0001FAB6", "#3ce0c8"),
            ("demo_bison",  "Flint Bison",  2, 9000,  "\U0001F9AC", "#ffb020"),
        ]
        for i, (tid, nm, lvl, loy, crest, color) in enumerate(demo_tribes):
            conn.execute(
                "INSERT OR IGNORE INTO tribes (tribe_id, name, level, loyalty_bal, loyalty_earned, crest, color, land, war_cry, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tid, nm, lvl, loy, loy, crest, color, lands[i % len(lands)], "For the fire that never dies!", now),
            )
        demo_kin = [("demo_ka", "Karu", "demo_wolves", 18), ("demo_ma", "Mara", "demo_wolves", 12),
                    ("demo_te", "Tek", "demo_ravens", 15), ("demo_lo", "Lowa", "demo_ravens", 8),
                    ("demo_bo", "Boru", "demo_bison", 6)]
        for uid, nm, tid, streak in demo_kin:
            conn.execute("INSERT OR IGNORE INTO users (user_id, name, tribe_id, created_ts) VALUES (?, ?, ?, ?)",
                         (uid, nm, tid, now))
            for d in range(streak):
                day = (date.fromisoformat(today_iso()) - timedelta(days=d)).isoformat()
                conn.execute("INSERT OR IGNORE INTO checkins (user_id, day, ts) VALUES (?, ?, ?)", (uid, day, now))


seed_demo()


def _resp(uid, name):
    return JSONResponse(compute_state(uid, name))

# --------------------------------------------------------------------------- #
# API routes                                                                   #
# --------------------------------------------------------------------------- #
@app.get("/api/state")
async def api_state(request: Request):
    user = await get_user(request)
    return _resp(user["id"], user.get("first_name", "Kin"))


@app.post("/api/checkin")
async def api_checkin(request: Request):
    user = await get_user(request)
    uid = user["id"]
    c = cfg()
    with db() as conn:
        u = ensure_user(conn, uid, user.get("first_name", "Kin"))
        if not u.get("tribe_id"):
            auto_place(conn, uid)
            u = ensure_user(conn, uid)
        before = conn.execute("SELECT 1 FROM checkins WHERE user_id = ? AND day = ?",
                              (uid, today_iso())).fetchone()
        conn.execute("INSERT OR IGNORE INTO checkins (user_id, day, ts) VALUES (?, ?, ?)",
                     (uid, today_iso(), int(time.time())))
        if not before:
            # tithe today's Ember gain into the tribal Hearth
            days = {r["day"] for r in conn.execute(
                "SELECT day FROM checkins WHERE user_id = ?", (uid,)).fetchall()}
            daily = int(c.get("ember", {}).get("checkin", 10)) + streak_bonus(streak_of(days), c)
            tithe = round(daily * float(c.get("loyalty", {}).get("tithe_pct", 0.2)))
            credit_loyalty(conn, u["tribe_id"], tithe)
            # advance the tribe's daily hunt
            conn.execute("INSERT OR IGNORE INTO hunts (tribe_id, day, progress, won) VALUES (?, ?, 0, 0)",
                         (u["tribe_id"], today_iso()))
            conn.execute("UPDATE hunts SET progress = progress + 1 WHERE tribe_id = ? AND day = ?",
                         (u["tribe_id"], today_iso()))
            _check_hunt_win(conn, u["tribe_id"])
    return _resp(uid, user.get("first_name", "Kin"))


def _check_hunt_win(conn, tribe_id: str):
    members = tribe_member_count(conn, tribe_id)
    row = conn.execute("SELECT progress, won FROM hunts WHERE tribe_id = ? AND day = ?",
                       (tribe_id, today_iso())).fetchone()
    if row and not row["won"] and int(row["progress"]) >= hunt_target(members):
        conn.execute("UPDATE hunts SET won = 1 WHERE tribe_id = ? AND day = ?", (tribe_id, today_iso()))
        credit_loyalty(conn, tribe_id, int(cfg().get("loyalty", {}).get("daily_hunt_win", 300)))


@app.post("/api/tasks/complete")
async def api_task(request: Request):
    user = await get_user(request)
    uid = user["id"]
    body = await request.json()
    task_id = (body or {}).get("task_id", "")
    task = next((t for t in cfg().get("tasks", []) if t["id"] == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="unknown task")
    if task.get("kind", "manual") in ("manual", "link"):
        with db() as conn:
            conn.execute("INSERT OR IGNORE INTO completions (user_id, task_id, day, ts) VALUES (?, ?, ?, ?)",
                         (uid, task_id, today_iso(), int(time.time())))
    return _resp(uid, user.get("first_name", "Kin"))


@app.post("/api/relic/find")
async def api_relic(request: Request):
    """Discover a relic while exploring — grants a hidden Ember bonus once each."""
    user = await get_user(request)
    uid = user["id"]
    body = await request.json()
    rid = (body or {}).get("relic_id", "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="missing relic_id")
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO relics (user_id, relic_id, ts) VALUES (?, ?, ?)",
                     (uid, rid, int(time.time())))
    return _resp(uid, user.get("first_name", "Kin"))


@app.post("/api/wallet")
async def api_wallet(request: Request):
    user = await get_user(request)
    uid = user["id"]
    body = await request.json()
    address = (body or {}).get("address", "").strip()
    with db() as conn:
        ensure_user(conn, uid, user.get("first_name", "Kin"))
        if address:
            conn.execute(
                "INSERT INTO wallets (user_id, address, ts) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET address=excluded.address, ts=excluded.ts",
                (uid, address[:120], int(time.time())))
        else:
            conn.execute("DELETE FROM wallets WHERE user_id = ?", (uid,))
    return _resp(uid, user.get("first_name", "Kin"))

@app.get("/api/tribe")
async def api_tribe(request: Request):
    user = await get_user(request)
    uid = user["id"]
    with db() as conn:
        u = ensure_user(conn, uid, user.get("first_name", "Kin"))
        if not u.get("tribe_id"):
            auto_place(conn, uid)
            u = ensure_user(conn, uid)
        tid = u["tribe_id"]
        summary = tribe_summary(conn, tid)
        mrows = conn.execute("SELECT user_id, name, supporter FROM users WHERE tribe_id = ?", (tid,)).fetchall()
        roster = []
        for m in mrows:
            em = compute_ember(conn, m["user_id"])
            roster.append({"name": m["name"], "ember": em["ember"], "streak": em["streak"],
                           "supporter": bool(m["supporter"]), "you": m["user_id"] == uid})
        roster.sort(key=lambda x: x["ember"], reverse=True)
        # roles by Ember: top = Chief, next 2 = Elders, rest = Kin
        for i, r in enumerate(roster):
            r["role"] = "Chief" if i == 0 else ("Elder" if i <= 2 else "Kin")
        wall = conn.execute(
            "SELECT author, text, ts FROM cave_wall WHERE tribe_id = ? ORDER BY ts DESC LIMIT 30", (tid,)
        ).fetchall()
        cave = [{"author": w["author"], "text": w["text"], "ts": int(w["ts"])} for w in wall]
    return JSONResponse({"tribe": summary, "roster": roster, "cave_wall": cave, "dev_mode": DEV_MODE})


@app.post("/api/tribe/warcry")
async def api_warcry(request: Request):
    user = await get_user(request)
    uid = user["id"]
    body = await request.json()
    text = (body or {}).get("text", "").strip()[:120]
    with db() as conn:
        u = ensure_user(conn, uid, user.get("first_name", "Kin"))
        if u.get("tribe_id") and text:
            conn.execute("UPDATE tribes SET war_cry = ? WHERE tribe_id = ?", (text, u["tribe_id"]))
            conn.execute("INSERT OR IGNORE INTO completions (user_id, task_id, day, ts) VALUES (?, 'war_cry', ?, ?)",
                         (uid, today_iso(), int(time.time())))
    return _resp(uid, user.get("first_name", "Kin"))


@app.post("/api/tribe/cave")
async def api_cave(request: Request):
    user = await get_user(request)
    uid = user["id"]
    body = await request.json()
    text = (body or {}).get("text", "").strip()[:200]
    if not text:
        raise HTTPException(status_code=400, detail="empty")
    with db() as conn:
        u = ensure_user(conn, uid, user.get("first_name", "Kin"))
        if u.get("tribe_id"):
            conn.execute("INSERT INTO cave_wall (tribe_id, author, text, ts) VALUES (?, ?, ?, ?)",
                         (u["tribe_id"], u["name"], text, int(time.time())))
    return JSONResponse({"ok": True})


@app.post("/api/tribe/upgrade")
async def api_upgrade(request: Request):
    """Spend the Hearth's Loyalty balance to graduate the settlement one level.
    Spending never lowers the tribe's rank (which uses loyalty EARNED)."""
    user = await get_user(request)
    uid = user["id"]
    with db() as conn:
        u = ensure_user(conn, uid, user.get("first_name", "Kin"))
        tid = u.get("tribe_id")
        t = conn.execute("SELECT level, loyalty_bal FROM tribes WHERE tribe_id = ?", (tid,)).fetchone()
        if not t:
            raise HTTPException(status_code=404, detail="no tribe")
        lvl = int(t["level"])
        if lvl >= len(ladder()):
            return JSONResponse({**compute_state(uid, user.get("first_name", "Kin")), "ok": False, "error": "max_level"})
        cost = int(ladder_at(lvl + 1)["cost"])
        if int(t["loyalty_bal"]) < cost:
            return JSONResponse({**compute_state(uid, user.get("first_name", "Kin")), "ok": False, "error": "not_enough"})
        conn.execute("UPDATE tribes SET level = level + 1, loyalty_bal = loyalty_bal - ? WHERE tribe_id = ?",
                     (cost, tid))
    return JSONResponse({**compute_state(uid, user.get("first_name", "Kin")), "ok": True})


@app.post("/api/drum")
async def api_drum(request: Request):
    """Beat the Drum — nudge sleeping mates. Limited per day (+ purchased extras)."""
    user = await get_user(request)
    uid = user["id"]
    with db() as conn:
        u = ensure_user(conn, uid, user.get("first_name", "Kin"))
        left = drum_calls_left(conn, uid, int(u.get("drum_extra", 0)))
        if left < 1:
            return JSONResponse({**compute_state(uid, user.get("first_name", "Kin")), "ok": False, "error": "no_drums"})
        conn.execute("INSERT OR IGNORE INTO drum_calls (user_id, day, count) VALUES (?, ?, 0)",
                     (uid, today_iso()))
        conn.execute("UPDATE drum_calls SET count = count + 1 WHERE user_id = ? AND day = ?",
                     (uid, today_iso()))
        conn.execute("INSERT OR IGNORE INTO completions (user_id, task_id, day, ts) VALUES (?, 'beat_drum', ?, ?)",
                     (uid, today_iso(), int(time.time())))
    return JSONResponse({**compute_state(uid, user.get("first_name", "Kin")), "ok": True})


@app.get("/api/leaderboard/kin")
async def api_lb_kin(request: Request):
    user = await get_user(request)
    with db() as conn:
        ensure_user(conn, user["id"], user.get("first_name", "Kin"))
        data = kin_leaderboard(conn, user["id"])
    return JSONResponse(data)


@app.get("/api/leaderboard/tribes")
async def api_lb_tribes(request: Request):
    user = await get_user(request)
    with db() as conn:
        u = ensure_user(conn, user["id"], user.get("first_name", "Kin"))
        data = tribe_leaderboard(conn, u.get("tribe_id"))
    return JSONResponse(data)


@app.get("/api/lands")
async def api_lands(request: Request):
    user = await get_user(request)
    with db() as conn:
        u = ensure_user(conn, user["id"], user.get("first_name", "Kin"))
        lands = lands_state(conn)
        mine = tribe_summary(conn, u.get("tribe_id")) if u.get("tribe_id") else {}
    return JSONResponse({"lands": lands, "my_tribe": mine})

# --------------------------------------------------------------------------- #
# Telegram Stars payments (XTR)                                                #
#   Live flow:  POST /api/store/invoice -> createInvoiceLink -> frontend calls #
#               tg.openInvoice(link). On payment Telegram hits the webhook.     #
#   Dev flow:   POST /api/store/buy_demo spends a demo Star balance offline.    #
# --------------------------------------------------------------------------- #
TG_API = "https://api.telegram.org"


@app.post("/api/store/invoice")
async def api_invoice(request: Request):
    """Create a Telegram Stars invoice link for a store item. Requires BOT_TOKEN."""
    user = await get_user(request)
    uid = user["id"]
    body = await request.json()
    item_id = (body or {}).get("item", "")
    value = (body or {}).get("value", "")
    it = store_item(item_id)
    if not it:
        raise HTTPException(status_code=400, detail="unknown item")
    if DEV_MODE:
        raise HTTPException(status_code=400, detail="no BOT_TOKEN: use demo purchase")
    payload = json.dumps({"uid": uid, "item": item_id, "value": value})[:128]
    body_req = {
        "title": it["title"][:32],
        "description": it["desc"][:255],
        "payload": payload,
        "currency": "XTR",
        "prices": [{"label": it["title"][:32], "amount": int(it["stars"])}],
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{TG_API}/bot{BOT_TOKEN}/createInvoiceLink", json=body_req)
    data = r.json()
    if not data.get("ok"):
        raise HTTPException(status_code=502, detail=f"telegram: {data.get('description', 'error')}")
    return JSONResponse({"ok": True, "invoice_link": data["result"]})


@app.post("/api/telegram/webhook")
async def tg_webhook(request: Request):
    """Telegram update webhook. Answers pre_checkout_query and, on a successful
    Stars payment, grants the purchased item exactly once (idempotent by
    telegram_payment_charge_id)."""
    if DEV_MODE:
        return JSONResponse({"ok": True})
    update = await request.json()
    # 1) approve the pre-checkout
    pcq = update.get("pre_checkout_query")
    if pcq:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(f"{TG_API}/bot{BOT_TOKEN}/answerPreCheckoutQuery",
                              json={"pre_checkout_query_id": pcq["id"], "ok": True})
        return JSONResponse({"ok": True})
    # 2) fulfil a successful payment
    msg = update.get("message", {})
    sp = msg.get("successful_payment")
    if sp:
        try:
            payload = json.loads(sp.get("invoice_payload", "{}"))
        except Exception:
            payload = {}
        uid = str(payload.get("uid", ""))
        item = payload.get("item", "")
        value = payload.get("value", "")
        charge = sp.get("telegram_payment_charge_id", "")
        stars = int(sp.get("total_amount", 0))
        if uid and item and charge:
            with db() as conn:
                dup = conn.execute("SELECT 1 FROM payments WHERE charge_id = ?", (charge,)).fetchone()
                if not dup:
                    ensure_user(conn, uid)
                    grant_item(conn, uid, item, value)
                    conn.execute(
                        "INSERT OR IGNORE INTO payments (charge_id, user_id, item, stars, ts) VALUES (?, ?, ?, ?, ?)",
                        (charge, uid, item, stars, int(time.time())))
    return JSONResponse({"ok": True})


@app.post("/api/store/buy_demo")
async def api_buy_demo(request: Request):
    """Offline purchase using a demo Star balance (DEV_MODE / no BOT_TOKEN only),
    so the full store UI works before real Stars are wired up."""
    user = await get_user(request)
    uid = user["id"]
    body = await request.json()
    item_id = (body or {}).get("item", "")
    value = (body or {}).get("value", "")
    it = store_item(item_id)
    if not it:
        raise HTTPException(status_code=400, detail="unknown item")
    with db() as conn:
        u = ensure_user(conn, uid, user.get("first_name", "Kin"))
        if int(u.get("stars_demo", 0)) < int(it["stars"]):
            return JSONResponse({**compute_state(uid, user.get("first_name", "Kin")), "ok": False, "error": "insufficient_stars"})
        conn.execute("UPDATE users SET stars_demo = stars_demo - ? WHERE user_id = ?",
                     (int(it["stars"]), uid))
        grant_item(conn, uid, item_id, value)
    return JSONResponse({**compute_state(uid, user.get("first_name", "Kin")), "ok": True})


@app.get("/api/claim")
async def api_claim(request: Request):
    user = await get_user(request)
    uid = user["id"]
    with db() as conn:
        u = ensure_user(conn, uid, user.get("first_name", "Kin"))
        em = compute_ember(conn, uid)
        alloc = allocation_preview(conn, uid, em["ember"])
    return JSONResponse({"wallet": em["wallet"], "allocation": alloc, "age": cfg().get("age", {}),
                         "dev_mode": DEV_MODE})


@app.get("/healthz")
async def healthz():
    return JSONResponse({"ok": True, "db": "postgres" if USE_PG else "sqlite",
                         "payments": "live" if not DEV_MODE else "demo"})


@app.get("/tonconnect-manifest.json")
async def ton_manifest(request: Request):
    """Serve the TON Connect manifest, auto-filling the app URL from the request
    so wallets show the right origin without manual editing."""
    base = str(request.base_url).rstrip("/")
    path = FRONTEND_DIR / "tonconnect-manifest.json"
    manifest = {"url": base, "name": "Tribes", "iconUrl": f"{base}/icon.png"}
    if path.exists():
        try:
            m = json.loads(path.read_text())
            if not m.get("url", "").startswith("https://REPLACE"):
                manifest = m
        except Exception:
            pass
    return JSONResponse(manifest)


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))

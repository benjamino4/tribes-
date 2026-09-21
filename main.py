"""
TRIBES v2 - Telegram Mini App backend (FastAPI).

A Web3 community airdrop themed on the dawn of humanity. The TRIBE is the hero:
loyalty is a shared pool, individuals earn a Kindle Score (effort/activeness)
that sets their in-tribe rank and feeds the tribe. Neglect triggers Ashfall
decay; kin can Rekindle each other. Tribes hold and invade Lands for influence.
Admins (@Joeldan) tune every rule live from the in-app Elders' Forge.

Secrets come ONLY from env vars: DATABASE_URL, BOT_TOKEN. Never hard-coded.
Store is cosmetic/convenience/social ONLY - never Loyalty, Kindle, rank, land
or allocation - to keep the airdrop fair.
"""
import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

_HERE = Path(__file__).resolve().parent
BASE_DIR = _HERE
FRONTEND_DIR = _HERE
_RES_DIR = _HERE

DB_PATH = Path(os.environ.get("TRIBES_DB", BASE_DIR / "tribes.db"))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DEV_MODE = not BOT_TOKEN
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = DATABASE_URL.startswith("postgres")
TG_API = "https://api.telegram.org"
CONFIG_FILE = _RES_DIR / "config.json"

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row

app = FastAPI(title="Tribes v2 Mini App")


# --------------------------------------------------------------------------- #
# Database plumbing (SQLite local / Postgres prod)                            #
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


def _row(r):
    return dict(r) if r is not None else None


def _rows(rs):
    return [dict(r) for r in rs]

# --------------------------------------------------------------------------- #
# Config: file defaults + live admin overrides stored in the DB (persist)     #
# --------------------------------------------------------------------------- #
def _file_cfg() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def get_setting(key: str, default=None):
    try:
        with db() as conn:
            r = conn.execute("SELECT v FROM settings WHERE k = ?", (key,)).fetchone()
        if r:
            return json.loads(_row(r)["v"])
    except Exception:
        pass
    return default


def set_setting(key: str, value) -> None:
    blob = json.dumps(value)
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO settings (k, v) VALUES (?, ?)", (key, blob))
        conn.execute("UPDATE settings SET v = ? WHERE k = ?", (blob, key))


def cfg() -> dict:
    """Effective config = file defaults deep-merged with live admin overrides."""
    base = _file_cfg()
    over = get_setting("config_override", {})
    return _deep_merge(base, over) if over else base


def ladder() -> list:
    return cfg().get("settlement_ladder", [])


def ladder_at(level: int) -> dict:
    for r in ladder():
        if int(r["level"]) == int(level):
            return r
    return {"level": level, "stage": "Campfire", "max_members": 5, "invites_per_day": 2, "cost": 0}


def age_now() -> dict:
    c = cfg().get("age", {})
    cur = c.get("current", "fire")
    ages = c.get("ages", {})
    a = dict(ages.get(cur, {}))
    a["id"] = cur
    return a


# --------------------------------------------------------------------------- #
# Schema                                                                      #
# --------------------------------------------------------------------------- #
def init_db() -> None:
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS settings (
            k TEXT PRIMARY KEY, v TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tribes (
            tribe_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            chief_id TEXT,
            crest TEXT DEFAULT 'flame',
            color TEXT DEFAULT '#ff5a3c',
            level INTEGER NOT NULL DEFAULT 1,
            loyalty INTEGER NOT NULL DEFAULT 0,
            loyalty_earned INTEGER NOT NULL DEFAULT 0,
            embertide INTEGER NOT NULL DEFAULT 0,
            war_cry TEXT DEFAULT '',
            chill_days INTEGER NOT NULL DEFAULT 0,
            created_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            username TEXT DEFAULT '',
            tribe_id TEXT,
            kindle INTEGER NOT NULL DEFAULT 0,
            ember INTEGER NOT NULL DEFAULT 0,
            last_checkin TEXT DEFAULT '',
            referrer_id TEXT DEFAULT '',
            cosmetics TEXT DEFAULT '{}',
            title TEXT DEFAULT '',
            wallet TEXT DEFAULT '',
            wards INTEGER NOT NULL DEFAULT 0,
            created_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS checkins (
            user_id TEXT NOT NULL, day TEXT NOT NULL,
            PRIMARY KEY (user_id, day))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS completions (
            user_id TEXT NOT NULL, task_id TEXT NOT NULL, period TEXT NOT NULL,
            PRIMARY KEY (user_id, task_id, period))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS relics (
            user_id TEXT NOT NULL, day TEXT NOT NULL,
            PRIMARY KEY (user_id, day))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS lands (
            land_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            owner_tribe TEXT DEFAULT '',
            staked INTEGER NOT NULL DEFAULT 0,
            attacker_tribe TEXT DEFAULT '',
            attacker_staked INTEGER NOT NULL DEFAULT 0,
            contest_ends TEXT DEFAULT '',
            cooldown_until TEXT DEFAULT '')""")
        conn.execute("""CREATE TABLE IF NOT EXISTS rekindles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            savior_id TEXT, saved_id TEXT, ts TEXT)""") if not USE_PG else conn.execute(
            """CREATE TABLE IF NOT EXISTS rekindles (
            id SERIAL PRIMARY KEY, savior_id TEXT, saved_id TEXT, ts TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS referrals (
            referrer_id TEXT NOT NULL, newcomer_id TEXT NOT NULL,
            joined_tribe TEXT DEFAULT '', ts TEXT,
            PRIMARY KEY (referrer_id, newcomer_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS inventory (
            owner TEXT NOT NULL, owner_type TEXT NOT NULL,
            item_id TEXT NOT NULL, qty INTEGER NOT NULL DEFAULT 1,
            meta TEXT DEFAULT '',
            PRIMARY KEY (owner, owner_type, item_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS payments (
            charge_id TEXT PRIMARY KEY, user_id TEXT, item_id TEXT, stars INTEGER, ts TEXT)""")

# --------------------------------------------------------------------------- #
# Telegram auth (HMAC-verified initData)                                      #
# --------------------------------------------------------------------------- #
def validate_init_data(init_data: str) -> dict:
    if DEV_MODE:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        uid = pairs.get("user_id") or "dev-user"
        return {"id": str(uid), "first_name": pairs.get("first_name", "Kin"),
                "username": pairs.get("username", "")}
    if not init_data:
        raise HTTPException(status_code=401, detail="missing initData")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="missing hash")
    dcs = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs.keys()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
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


async def _init_data_from(request: Request) -> str:
    init_data = request.headers.get("X-Init-Data", "")
    if not init_data and request.method == "POST":
        try:
            body = await request.json()
            init_data = body.get("initData", "") if isinstance(body, dict) else ""
        except Exception:
            init_data = ""
    return init_data


async def get_user(request: Request) -> dict:
    return validate_init_data(await _init_data_from(request))


async def body_of(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


def is_admin(user: dict) -> bool:
    adm = cfg().get("admin", {})
    uname = (user.get("username") or "").lower().lstrip("@")
    unames = [u.lower().lstrip("@") for u in adm.get("usernames", [])]
    ids = [str(x) for x in adm.get("user_ids", [])]
    return (uname and uname in unames) or (str(user.get("id")) in ids)


def require_admin(user: dict):
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="elders only")


# --------------------------------------------------------------------------- #
# Time helpers                                                                #
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def today_iso() -> str:
    return _now().date().isoformat()


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def parse_iso(s: str):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def week_period() -> str:
    y, w, _ = _now().isocalendar()
    return f"{y}-W{w:02d}"


def days_idle(last_checkin: str) -> int:
    if not last_checkin:
        return 999
    try:
        d = date.fromisoformat(last_checkin)
    except Exception:
        return 999
    return (_now().date() - d).days


def activity_state(last_checkin: str) -> str:
    a = cfg().get("ashfall", {})
    idle = days_idle(last_checkin)
    if idle >= int(a.get("fading_after_days", 4)):
        return "fading"
    if idle >= int(a.get("cooling_after_days", 2)):
        return "cooling"
    return "active"

# --------------------------------------------------------------------------- #
# Users, tribes, scoring                                                      #
# --------------------------------------------------------------------------- #
def ensure_user(conn, uid: str, name: str = "Kin", username: str = "") -> dict:
    r = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
    if r:
        u = _row(r)
        if username and u.get("username") != username:
            conn.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, uid))
            u["username"] = username
        return u
    conn.execute(
        "INSERT INTO users (user_id, name, username, created_at) VALUES (?, ?, ?, ?)",
        (uid, name, username, iso(_now())))
    return _row(conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone())


def _slug(text: str) -> str:
    keep = "".join(ch.lower() if ch.isalnum() else "_" for ch in text).strip("_")
    return keep[:20] or "tribe"


def new_tribe_id(conn, name: str) -> str:
    base = _slug(name)
    tid = base
    n = 1
    while conn.execute("SELECT 1 FROM tribes WHERE tribe_id = ?", (tid,)).fetchone():
        n += 1
        tid = f"{base}_{n}"
    return tid


def award_kindle(conn, uid: str, amount: int) -> None:
    if amount <= 0:
        return
    conn.execute("UPDATE users SET kindle = kindle + ? WHERE user_id = ?", (int(amount), uid))
    u = _row(conn.execute("SELECT tribe_id FROM users WHERE user_id = ?", (uid,)).fetchone())
    if u and u.get("tribe_id"):
        k2l = float(cfg().get("loyalty", {}).get("kindle_to_loyalty", 0.5))
        gain = int(round(amount * k2l))
        if gain:
            conn.execute(
                "UPDATE tribes SET loyalty = loyalty + ?, loyalty_earned = loyalty_earned + ? WHERE tribe_id = ?",
                (gain, gain, u["tribe_id"]))


def credit_loyalty(conn, tribe_id: str, amount: int, earned: bool = True) -> None:
    if not tribe_id or amount == 0:
        return
    conn.execute("UPDATE tribes SET loyalty = loyalty + ? WHERE tribe_id = ?", (int(amount), tribe_id))
    if earned and amount > 0:
        conn.execute("UPDATE tribes SET loyalty_earned = loyalty_earned + ? WHERE tribe_id = ?",
                     (int(amount), tribe_id))


def add_embertide(conn, tribe_id: str, amount: int) -> None:
    if tribe_id and amount:
        conn.execute("UPDATE tribes SET embertide = embertide + ? WHERE tribe_id = ?",
                     (int(amount), tribe_id))


def streak_of(conn, uid: str) -> int:
    rows = conn.execute("SELECT day FROM checkins WHERE user_id = ?", (uid,)).fetchall()
    days = {(_row(r)["day"]) for r in rows}
    if not days:
        return 0
    streak, cur = 0, _now().date()
    # allow today or yesterday as the anchor
    if cur.isoformat() not in days and (cur - timedelta(days=1)).isoformat() not in days:
        return 0
    if cur.isoformat() not in days:
        cur = cur - timedelta(days=1)
    while cur.isoformat() in days:
        streak += 1
        cur -= timedelta(days=1)
    return streak


def rank_for(kindle: int, peers: list) -> dict:
    """peers = sorted list of kindle scores (all tribe members). Percentile rank."""
    ranks = cfg().get("ranks", [])
    if not peers:
        pct = 0.0
    else:
        below = sum(1 for k in peers if k < kindle)
        pct = below / len(peers)
    chosen = ranks[0] if ranks else {"name": "Ash-born", "id": "ashborn"}
    top_kindle = max(peers) if peers else 0
    for r in ranks:
        if r.get("top_only") and not (kindle >= top_kindle and kindle > 0):
            continue
        if pct >= float(r.get("min_pct", 0)):
            chosen = r
    return {"id": chosen.get("id"), "name": chosen.get("name"),
            "icon": chosen.get("icon", chosen.get("id")), "percentile": round(pct, 3)}

# --------------------------------------------------------------------------- #
# Ashfall: daily Loyalty decay driven by neglect (compounds via chill)        #
# --------------------------------------------------------------------------- #
def run_ashfall(force: bool = False) -> dict:
    a = cfg().get("ashfall", {})
    age_mult = float(age_now().get("decay_multiplier", 1.0))
    today = today_iso()
    if not force and get_setting("last_ashfall") == today:
        return {"ran": False}
    changed = []
    with db() as conn:
        tribes = _rows(conn.execute("SELECT * FROM tribes").fetchall())
        for t in tribes:
            members = _rows(conn.execute(
                "SELECT last_checkin FROM users WHERE tribe_id = ?", (t["tribe_id"],)).fetchall())
            n = len(members) or 1
            cooling = sum(1 for m in members if activity_state(m["last_checkin"]) == "cooling")
            fading = sum(1 for m in members if activity_state(m["last_checkin"]) == "fading")
            neglect = (cooling * float(a.get("cooling_weight", 0.5))
                       + fading * float(a.get("fading_weight", 1.0))) / n
            fading_ratio = fading / n
            chill_days = int(t.get("chill_days", 0))
            if fading_ratio >= float(a.get("high_fading_ratio", 0.34)):
                chill_days += 1
            else:
                chill_days = 0
            chill = min(float(a.get("chill_cap", 2.0)),
                        1.0 + float(a.get("chill_step", 0.1)) * chill_days)
            pct = min(float(a.get("max_daily_pct", 0.15)),
                      float(a.get("base_rate", 0.06)) * neglect) * age_mult * chill
            loss = int(round(int(t["loyalty"]) * pct))
            if loss > 0:
                conn.execute("UPDATE tribes SET loyalty = MAX(0, loyalty - ?), chill_days = ? WHERE tribe_id = ?",
                             (loss, chill_days, t["tribe_id"]))
                changed.append({"tribe": t["tribe_id"], "loss": loss, "chill": round(chill, 2)})
            else:
                conn.execute("UPDATE tribes SET chill_days = ? WHERE tribe_id = ?",
                             (chill_days, t["tribe_id"]))
            # fading members' own Kindle cools
            kdecay = float(cfg().get("kindle", {}).get("decay_when_fading", 0.9))
            if kdecay < 1.0:
                conn.execute(
                    "UPDATE users SET kindle = CAST(kindle * ? AS INTEGER) WHERE tribe_id = ? AND last_checkin <= ?",
                    (kdecay, t["tribe_id"],
                     (_now().date() - timedelta(days=int(a.get("fading_after_days", 4)))).isoformat()))
    set_setting("last_ashfall", today)
    return {"ran": True, "changed": changed}


def fading_members(conn, tribe_id: str) -> list:
    rows = _rows(conn.execute(
        "SELECT user_id, name, username, kindle, last_checkin FROM users WHERE tribe_id = ?",
        (tribe_id,)).fetchall())
    out = []
    for r in rows:
        if activity_state(r["last_checkin"]) == "fading":
            r["idle_days"] = days_idle(r["last_checkin"])
            out.append(r)
    out.sort(key=lambda x: -x["idle_days"])
    return out


def do_rekindle(conn, savior_id: str, saved_id: str) -> dict:
    rk = cfg().get("rekindle", {})
    saved = _row(conn.execute("SELECT * FROM users WHERE user_id = ?", (saved_id,)).fetchone())
    if not saved:
        raise HTTPException(status_code=404, detail="kin not found")
    if activity_state(saved["last_checkin"]) != "fading":
        raise HTTPException(status_code=400, detail="that kin is not fading")
    # grace: mark a recent checkin so decay halts
    grace_day = (_now().date() - timedelta(days=int(rk.get("grace_days", 3)) - 1)).isoformat()
    conn.execute("UPDATE users SET last_checkin = ? WHERE user_id = ?", (grace_day, saved_id))
    if saved.get("tribe_id"):
        credit_loyalty(conn, saved["tribe_id"], int(rk.get("loyalty_restore", 150)))
    award_kindle(conn, savior_id, int(rk.get("savior_kindle", 25)))
    conn.execute("UPDATE users SET title = ? WHERE user_id = ?", ("Kindred Flame", savior_id))
    conn.execute("INSERT INTO rekindles (savior_id, saved_id, ts) VALUES (?, ?, ?)",
                 (savior_id, saved_id, iso(_now())))
    _grant(conn, savior_id, "user", "kindred_flame", 1)
    return {"saved": saved.get("name"), "loyalty_restore": int(rk.get("loyalty_restore", 150))}

# --------------------------------------------------------------------------- #
# Inventory (Satchel = user, Tribe Cache = tribe)                             #
# --------------------------------------------------------------------------- #
def _grant(conn, owner: str, owner_type: str, item_id: str, qty: int = 1, meta: str = "") -> None:
    if not owner:
        return
    r = conn.execute(
        "SELECT qty FROM inventory WHERE owner = ? AND owner_type = ? AND item_id = ?",
        (owner, owner_type, item_id)).fetchone()
    if r:
        conn.execute(
            "UPDATE inventory SET qty = qty + ? WHERE owner = ? AND owner_type = ? AND item_id = ?",
            (qty, owner, owner_type, item_id))
    else:
        conn.execute(
            "INSERT INTO inventory (owner, owner_type, item_id, qty, meta) VALUES (?, ?, ?, ?, ?)",
            (owner, owner_type, item_id, qty, meta))


def inventory_of(conn, owner: str, owner_type: str) -> list:
    rows = _rows(conn.execute(
        "SELECT item_id, qty, meta FROM inventory WHERE owner = ? AND owner_type = ?",
        (owner, owner_type)).fetchall())
    items = {i["id"]: i for i in cfg().get("store", {}).get("items", [])}
    extra = {"kindred_flame": {"title": "Kindred Flame", "art": "rekindle", "desc": "You saved a Fading kin."},
             "land_relic": {"title": "Land Relic", "art": "relic", "desc": "A claimable relic node (future NFT)."}}
    out = []
    for r in rows:
        meta = items.get(r["item_id"]) or extra.get(r["item_id"]) or {"title": r["item_id"], "art": "relic"}
        out.append({"item_id": r["item_id"], "qty": r["qty"],
                    "title": meta.get("title"), "art": meta.get("art", "relic"),
                    "desc": meta.get("desc", "")})
    return out


# --------------------------------------------------------------------------- #
# Lands & invasion (Embertide)                                                #
# --------------------------------------------------------------------------- #
def ensure_lands(conn) -> None:
    for i, name in enumerate(cfg().get("lands", [])):
        lid = f"land_{i}"
        conn.execute("INSERT OR IGNORE INTO lands (land_id, name) VALUES (?, ?)", (lid, name))


def _tribe_name(conn, tid: str) -> str:
    if not tid:
        return ""
    r = conn.execute("SELECT name FROM tribes WHERE tribe_id = ?", (tid,)).fetchone()
    return _row(r)["name"] if r else tid


def lands_state(conn) -> list:
    ensure_lands(conn)
    inv = cfg().get("invasion", {})
    base = int(inv.get("base_hold_cost", 1000))
    rows = _rows(conn.execute("SELECT * FROM lands ORDER BY land_id").fetchall())
    now = _now()
    out = []
    for l in rows:
        contest_ends = parse_iso(l.get("contest_ends"))
        contested = bool(l.get("attacker_tribe")) and contest_ends and contest_ends > now
        out.append({
            "land_id": l["land_id"], "name": l["name"],
            "owner": l.get("owner_tribe") or "",
            "owner_name": _tribe_name(conn, l.get("owner_tribe")),
            "staked": int(l.get("staked", 0)),
            "hold_cost": base,
            "contested": contested,
            "attacker": l.get("attacker_tribe") or "",
            "attacker_name": _tribe_name(conn, l.get("attacker_tribe")),
            "attacker_staked": int(l.get("attacker_staked", 0)),
            "contest_ends": l.get("contest_ends") or "",
            "cooldown_until": l.get("cooldown_until") or "",
            "bonus_per_day": int(cfg().get("loyalty", {}).get("land_hold_bonus_per_day", 200)),
        })
    return out


def resolve_contests(conn) -> None:
    now = _now()
    inv = cfg().get("invasion", {})
    rows = _rows(conn.execute("SELECT * FROM lands WHERE attacker_tribe != ''").fetchall())
    for l in rows:
        ce = parse_iso(l.get("contest_ends"))
        if not ce or ce > now:
            continue
        attacker = l["attacker_tribe"]
        atk, dfd = int(l.get("attacker_staked", 0)), int(l.get("staked", 0))
        cooldown = iso(now + timedelta(hours=int(inv.get("cooldown_hours", 48))))
        if atk > dfd:
            add_embertide(conn, attacker, -atk)  # consume stake
            credit_loyalty(conn, attacker, int(cfg().get("loyalty", {}).get("invade_win", 500)))
            conn.execute(
                "UPDATE lands SET owner_tribe = ?, staked = ?, attacker_tribe = '', attacker_staked = 0, contest_ends = '', cooldown_until = ? WHERE land_id = ?",
                (attacker, atk, cooldown, l["land_id"]))
        else:
            conn.execute(
                "UPDATE lands SET attacker_tribe = '', attacker_staked = 0, contest_ends = '', cooldown_until = ? WHERE land_id = ?",
                (cooldown, l["land_id"]))

# --------------------------------------------------------------------------- #
# Tribe views                                                                 #
# --------------------------------------------------------------------------- #
def tribe_summary(conn, tribe_id: str) -> dict:
    t = _row(conn.execute("SELECT * FROM tribes WHERE tribe_id = ?", (tribe_id,)).fetchone())
    if not t:
        return {}
    members = _rows(conn.execute(
        "SELECT last_checkin FROM users WHERE tribe_id = ?", (tribe_id,)).fetchall())
    n = len(members)
    active = sum(1 for m in members if activity_state(m["last_checkin"]) == "active")
    cooling = sum(1 for m in members if activity_state(m["last_checkin"]) == "cooling")
    fading = sum(1 for m in members if activity_state(m["last_checkin"]) == "fading")
    lvl = ladder_at(t["level"])
    nxt = ladder_at(t["level"] + 1)
    held = _rows(conn.execute("SELECT name FROM lands WHERE owner_tribe = ?", (tribe_id,)).fetchall())
    return {
        "tribe_id": t["tribe_id"], "name": t["name"], "crest": t.get("crest", "flame"),
        "color": t.get("color", "#ff5a3c"), "chief_id": t.get("chief_id"),
        "loyalty": int(t["loyalty"]), "loyalty_earned": int(t["loyalty_earned"]),
        "embertide": int(t["embertide"]), "war_cry": t.get("war_cry", ""),
        "level": t["level"], "stage": lvl.get("stage"),
        "max_members": lvl.get("max_members"), "members": n,
        "next_stage": nxt.get("stage") if nxt.get("level") != t["level"] else None,
        "next_cost": nxt.get("cost") if nxt.get("level") != t["level"] else None,
        "active": active, "cooling": cooling, "fading": fading,
        "chill_days": int(t.get("chill_days", 0)),
        "lands": [h["name"] for h in held],
    }


def tribe_roster(conn, tribe_id: str) -> list:
    rows = _rows(conn.execute(
        "SELECT user_id, name, username, kindle, ember, last_checkin, title, cosmetics FROM users WHERE tribe_id = ? ORDER BY kindle DESC",
        (tribe_id,)).fetchall())
    peers = [r["kindle"] for r in rows]
    out = []
    for i, r in enumerate(rows):
        rk = rank_for(r["kindle"], peers)
        try:
            cos = json.loads(r.get("cosmetics") or "{}")
        except Exception:
            cos = {}
        out.append({
            "user_id": r["user_id"], "name": r["name"], "username": r.get("username", ""),
            "kindle": int(r["kindle"]), "ember": int(r["ember"]),
            "position": i + 1, "rank": rk, "title": r.get("title", ""),
            "state": activity_state(r["last_checkin"]),
            "idle_days": days_idle(r["last_checkin"]),
            "cosmetics": cos,
        })
    return out


def apply_land_income(conn) -> None:
    """Daily: each held land feeds its owner Loyalty + Embertide (part of tick)."""
    inv = cfg().get("invasion", {})
    loy = cfg().get("loyalty", {})
    lands = _rows(conn.execute("SELECT owner_tribe FROM lands WHERE owner_tribe != ''").fetchall())
    for l in lands:
        credit_loyalty(conn, l["owner_tribe"], int(loy.get("land_hold_bonus_per_day", 200)))
        add_embertide(conn, l["owner_tribe"], int(inv.get("embertide_per_land_per_day", 50)))


def daily_tick() -> None:
    today = today_iso()
    if get_setting("last_tick") == today:
        return
    with db() as conn:
        apply_land_income(conn)
        resolve_contests(conn)
    run_ashfall()
    set_setting("last_tick", today)


def referral_apply(conn, newcomer_id: str, referrer_id: str) -> None:
    if not referrer_id or referrer_id == newcomer_id:
        return
    nc = _row(conn.execute("SELECT referrer_id FROM users WHERE user_id = ?", (newcomer_id,)).fetchone())
    if nc and nc.get("referrer_id"):
        return
    if not conn.execute("SELECT 1 FROM users WHERE user_id = ?", (referrer_id,)).fetchone():
        return
    conn.execute("UPDATE users SET referrer_id = ? WHERE user_id = ?", (referrer_id, newcomer_id))
    ref = cfg().get("referral", {})
    conn.execute("UPDATE users SET ember = ember + ? WHERE user_id = ?",
                 (int(ref.get("newcomer_ember", 25)), newcomer_id))
    conn.execute("INSERT OR IGNORE INTO referrals (referrer_id, newcomer_id, ts) VALUES (?, ?, ?)",
                 (referrer_id, newcomer_id, iso(_now())))

# --------------------------------------------------------------------------- #
# Tasks + aggregate state                                                     #
# --------------------------------------------------------------------------- #
def resolve_tasks(conn, uid: str, streak: int) -> list:
    period_week = week_period()
    done = {(_row(r)["task_id"]) for r in conn.execute(
        "SELECT task_id FROM completions WHERE user_id = ? AND period IN (?, ?)",
        (uid, period_week, "once")).fetchall()}
    today = today_iso()
    daily_done = {(_row(r)["task_id"]) for r in conn.execute(
        "SELECT task_id FROM completions WHERE user_id = ? AND period = ?",
        (uid, today)).fetchall()}
    u = _row(conn.execute("SELECT last_checkin, wallet FROM users WHERE user_id = ?", (uid,)).fetchone())
    out = []
    for t in cfg().get("tasks", []):
        kind = t.get("kind")
        complete = False
        if kind == "checkin":
            complete = (u and u.get("last_checkin") == today)
        elif kind == "streak":
            complete = streak >= int(t.get("target", 1))
        elif kind == "wallet":
            complete = bool(u and u.get("wallet"))
        elif t.get("repeat") == "daily":
            complete = t["id"] in daily_done
        else:
            complete = t["id"] in done
        out.append({"id": t["id"], "title": t["title"], "hint": t.get("hint", ""),
                    "reward": t.get("reward", 0), "kind": kind, "complete": complete})
    return out


def bot_username() -> str:
    return get_setting("bot_username", "") or ""


def compute_state(uid: str, name: str = "Kin", username: str = "") -> dict:
    daily_tick()
    with db() as conn:
        u = ensure_user(conn, uid, name, username)
        streak = streak_of(conn, uid)
        tasks = resolve_tasks(conn, uid, streak)
        tribe = tribe_summary(conn, u["tribe_id"]) if u.get("tribe_id") else None
        my_rank = None
        fading = []
        if u.get("tribe_id"):
            roster = tribe_roster(conn, u["tribe_id"])
            for m in roster:
                if m["user_id"] == uid:
                    my_rank = m["rank"]
                    my_rank["position"] = m["position"]
                    break
            fading = [f for f in fading_members(conn, u["tribe_id"]) if f["user_id"] != uid][:5]
        ref_count = _row(conn.execute(
            "SELECT COUNT(*) AS c FROM referrals WHERE referrer_id = ?", (uid,)).fetchone())["c"]
        try:
            cos = json.loads(u.get("cosmetics") or "{}")
        except Exception:
            cos = {}
        age = age_now()
        bu = bot_username()
        return {
            "user": {
                "id": uid, "name": u["name"], "username": u.get("username", ""),
                "kindle": int(u["kindle"]), "ember": int(u["ember"]),
                "streak": streak, "title": u.get("title", ""),
                "wards": int(u.get("wards", 0)), "wallet": u.get("wallet", ""),
                "state": activity_state(u.get("last_checkin", "")),
                "rank": my_rank, "cosmetics": cos, "is_admin": is_admin(
                    {"id": uid, "username": u.get("username", "")}),
            },
            "tribe": tribe,
            "is_wanderer": not u.get("tribe_id"),
            "age": {"id": age.get("id"), "name": age.get("name"),
                     "tagline": age.get("tagline", ""), "palette": age.get("palette", [])},
            "tasks": tasks,
            "fading_kin": fading,
            "referral": {
                "count": ref_count,
                "link": (f"https://t.me/{bu}?startapp=ref_{uid}" if bu else f"ref_{uid}"),
                "code": f"ref_{uid}",
            },
            "dev_mode": DEV_MODE,
            "rekindle_cost": int(cfg().get("rekindle", {}).get("stars_cost", 30)),
        }


def seed_demo() -> None:
    if not DEV_MODE:
        return
    with db() as conn:
        if conn.execute("SELECT 1 FROM tribes WHERE tribe_id LIKE 'demo_%' LIMIT 1").fetchone():
            return
        demo = [("demo_wolves", "Ashen Wolves", "wolf", "#ff5a3c", 52000),
                ("demo_ravens", "Storm Ravens", "raven", "#3ce0c8", 28000),
                ("demo_bison", "Flint Bison", "bison", "#ffb020", 9000)]
        for tid, nm, crest, color, loy in demo:
            conn.execute(
                "INSERT OR IGNORE INTO tribes (tribe_id, name, crest, color, loyalty, loyalty_earned, level, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tid, nm, crest, color, loy, loy, 3, iso(_now())))
        kin = [("demo_ka", "Karu", "demo_wolves", 820), ("demo_ma", "Mara", "demo_wolves", 540),
               ("demo_te", "Tek", "demo_ravens", 610), ("demo_lo", "Lowa", "demo_ravens", 300),
               ("demo_bo", "Boru", "demo_bison", 180)]
        for kid, nm, tid, kv in kin:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, name, tribe_id, kindle, ember, last_checkin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (kid, nm, tid, kv, kv // 2, today_iso(), iso(_now())))
        ensure_lands(conn)
        conn.execute("UPDATE lands SET owner_tribe = 'demo_wolves', staked = 1200 WHERE land_id = 'land_0'")
        conn.execute("UPDATE lands SET owner_tribe = 'demo_ravens', staked = 900 WHERE land_id = 'land_1'")


init_db()
seed_demo()

# --------------------------------------------------------------------------- #
# Core API                                                                    #
# --------------------------------------------------------------------------- #
async def _who(request: Request):
    u = await get_user(request)
    return str(u["id"]), u.get("first_name", "Kin"), (u.get("username") or ""), u


@app.get("/api/state")
async def api_state(request: Request):
    uid, name, uname, _ = await _who(request)
    return JSONResponse(compute_state(uid, name, uname))


@app.post("/api/start")
async def api_start(request: Request):
    """Called on launch; captures ?startapp=ref_<uid> for Bloodline referrals."""
    uid, name, uname, _ = await _who(request)
    body = await body_of(request)
    code = str(body.get("start_param") or body.get("ref") or "").strip()
    with db() as conn:
        ensure_user(conn, uid, name, uname)
        if code.startswith("ref_"):
            referral_apply(conn, uid, code[4:])
    return JSONResponse(compute_state(uid, name, uname))


@app.post("/api/checkin")
async def api_checkin(request: Request):
    uid, name, uname, _ = await _who(request)
    c = cfg()
    with db() as conn:
        ensure_user(conn, uid, name, uname)
        day = today_iso()
        exists = conn.execute("SELECT 1 FROM checkins WHERE user_id = ? AND day = ?", (uid, day)).fetchone()
        if exists:
            return JSONResponse({"already": True, **compute_state(uid, name, uname)})
        conn.execute("INSERT OR IGNORE INTO checkins (user_id, day) VALUES (?, ?)", (uid, day))
        conn.execute("UPDATE users SET last_checkin = ?, ember = ember + ? WHERE user_id = ?",
                     (day, int(c.get("ember", {}).get("checkin", 10)), uid))
        streak = streak_of(conn, uid)
        k = c.get("kindle", {})
        bonus = min(int(k.get("streak_cap", 60)), streak * int(k.get("per_streak_day", 3)))
        award_kindle(conn, uid, int(k.get("per_checkin", 12)) + bonus)
        u = _row(conn.execute("SELECT tribe_id FROM users WHERE user_id = ?", (uid,)).fetchone())
        add_embertide(conn, u.get("tribe_id"), int(c.get("invasion", {}).get("embertide_per_checkin", 4)))
    return JSONResponse({"ok": True, **compute_state(uid, name, uname)})


@app.post("/api/tasks/complete")
async def api_task(request: Request):
    uid, name, uname, _ = await _who(request)
    body = await body_of(request)
    task_id = str(body.get("task_id", ""))
    task = next((t for t in cfg().get("tasks", []) if t["id"] == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="no such task")
    period = today_iso() if task.get("repeat") == "daily" else (
        "once" if task.get("repeat") == "once" else week_period())
    with db() as conn:
        ensure_user(conn, uid, name, uname)
        if conn.execute("SELECT 1 FROM completions WHERE user_id = ? AND task_id = ? AND period = ?",
                        (uid, task_id, period)).fetchone():
            return JSONResponse({"already": True, **compute_state(uid, name, uname)})
        conn.execute("INSERT OR IGNORE INTO completions (user_id, task_id, period) VALUES (?, ?, ?)",
                     (uid, task_id, period))
        conn.execute("UPDATE users SET ember = ember + ? WHERE user_id = ?",
                     (int(task.get("reward", 0)), uid))
        award_kindle(conn, uid, int(cfg().get("kindle", {}).get("per_quest", 8)))
        u = _row(conn.execute("SELECT tribe_id FROM users WHERE user_id = ?", (uid,)).fetchone())
        add_embertide(conn, u.get("tribe_id"), int(cfg().get("invasion", {}).get("embertide_per_quest", 3)))
    return JSONResponse({"ok": True, **compute_state(uid, name, uname)})


@app.post("/api/relic/find")
async def api_relic(request: Request):
    uid, name, uname, _ = await _who(request)
    with db() as conn:
        ensure_user(conn, uid, name, uname)
        day = today_iso()
        if conn.execute("SELECT 1 FROM relics WHERE user_id = ? AND day = ?", (uid, day)).fetchone():
            return JSONResponse({"already": True, **compute_state(uid, name, uname)})
        conn.execute("INSERT OR IGNORE INTO relics (user_id, day) VALUES (?, ?)", (uid, day))
        conn.execute("UPDATE users SET ember = ember + ? WHERE user_id = ?",
                     (int(cfg().get("ember", {}).get("relic_find", 25)), uid))
        award_kindle(conn, uid, int(cfg().get("kindle", {}).get("per_relic", 10)))
        _grant(conn, uid, "user", "land_relic", 1)
    return JSONResponse({"ok": True, **compute_state(uid, name, uname)})


@app.post("/api/wallet")
async def api_wallet(request: Request):
    uid, name, uname, _ = await _who(request)
    body = await body_of(request)
    addr = str(body.get("address", "")).strip()[:80]
    with db() as conn:
        ensure_user(conn, uid, name, uname)
        conn.execute("UPDATE users SET wallet = ? WHERE user_id = ?", (addr, uid))
    return JSONResponse({"ok": True, **compute_state(uid, name, uname)})

# --------------------------------------------------------------------------- #
# Tribes: found / join / leave / view / warcry / upgrade / rekindle           #
# --------------------------------------------------------------------------- #
@app.post("/api/tribe/found")
async def api_found(request: Request):
    uid, name, uname, _ = await _who(request)
    body = await body_of(request)
    tname = str(body.get("name", "")).strip()[:32]
    crest = str(body.get("crest", "flame"))[:20]
    color = str(body.get("color", "#ff5a3c"))[:9]
    if not tname:
        raise HTTPException(status_code=400, detail="name your tribe")
    tc = cfg().get("tribe", {})
    with db() as conn:
        u = ensure_user(conn, uid, name, uname)
        if u.get("tribe_id"):
            raise HTTPException(status_code=400, detail="leave your tribe first")
        if int(u.get("kindle", 0)) < int(tc.get("found_min_kindle", 0)):
            raise HTTPException(status_code=400, detail="not enough Kindle to found a tribe")
        tid = new_tribe_id(conn, tname)
        seed = int(cfg().get("loyalty", {}).get("found_seed", 100))
        conn.execute(
            "INSERT INTO tribes (tribe_id, name, chief_id, crest, color, loyalty, loyalty_earned, level, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, tname, uid, crest, color, seed, seed, 1, iso(_now())))
        conn.execute("UPDATE users SET tribe_id = ? WHERE user_id = ?", (tid, uid))
    return JSONResponse({"ok": True, **compute_state(uid, name, uname)})


@app.post("/api/tribe/join")
async def api_join(request: Request):
    uid, name, uname, _ = await _who(request)
    body = await body_of(request)
    tid = str(body.get("tribe_id", ""))
    with db() as conn:
        u = ensure_user(conn, uid, name, uname)
        t = _row(conn.execute("SELECT * FROM tribes WHERE tribe_id = ?", (tid,)).fetchone())
        if not t:
            raise HTTPException(status_code=404, detail="tribe not found")
        cur = tribe_member_count(conn, tid)
        if cur >= int(ladder_at(t["level"]).get("max_members", 5)):
            raise HTTPException(status_code=400, detail="tribe is full")
        conn.execute("UPDATE users SET tribe_id = ? WHERE user_id = ?", (tid, uid))
        u2 = _row(conn.execute("SELECT referrer_id FROM users WHERE user_id = ?", (uid,)).fetchone())
        rid = u2.get("referrer_id") if u2 else ""
        if rid:
            ref = cfg().get("referral", {})
            award_kindle(conn, rid, int(ref.get("referrer_kindle", 40)))
            conn.execute("UPDATE referrals SET joined_tribe = ? WHERE referrer_id = ? AND newcomer_id = ?",
                         (tid, rid, uid))
    return JSONResponse({"ok": True, **compute_state(uid, name, uname)})


@app.post("/api/tribe/leave")
async def api_leave(request: Request):
    uid, name, uname, _ = await _who(request)
    with db() as conn:
        ensure_user(conn, uid, name, uname)
        conn.execute("UPDATE users SET tribe_id = NULL WHERE user_id = ?", (uid,))
    return JSONResponse({"ok": True, **compute_state(uid, name, uname)})


def tribe_member_count(conn, tribe_id: str) -> int:
    return _row(conn.execute("SELECT COUNT(*) AS c FROM users WHERE tribe_id = ?", (tribe_id,)).fetchone())["c"]


@app.get("/api/tribe")
async def api_tribe(request: Request):
    uid, name, uname, _ = await _who(request)
    with db() as conn:
        u = ensure_user(conn, uid, name, uname)
        if not u.get("tribe_id"):
            return JSONResponse({"tribe": None, "roster": [], "fading": [], "lands": lands_state(conn)})
        return JSONResponse({
            "tribe": tribe_summary(conn, u["tribe_id"]),
            "roster": tribe_roster(conn, u["tribe_id"]),
            "fading": fading_members(conn, u["tribe_id"]),
            "lands": [l for l in lands_state(conn) if l["owner"] == u["tribe_id"]],
            "is_chief": tribe_summary(conn, u["tribe_id"]).get("chief_id") == uid,
        })


@app.post("/api/tribe/warcry")
async def api_warcry(request: Request):
    uid, name, uname, _ = await _who(request)
    body = await body_of(request)
    text = str(body.get("text", "")).strip()[:80]
    with db() as conn:
        u = ensure_user(conn, uid, name, uname)
        if not u.get("tribe_id"):
            raise HTTPException(status_code=400, detail="join a tribe first")
        conn.execute("UPDATE tribes SET war_cry = ? WHERE tribe_id = ?", (text, u["tribe_id"]))
    return JSONResponse({"ok": True, **compute_state(uid, name, uname)})


@app.post("/api/tribe/upgrade")
async def api_upgrade(request: Request):
    uid, name, uname, _ = await _who(request)
    with db() as conn:
        u = ensure_user(conn, uid, name, uname)
        if not u.get("tribe_id"):
            raise HTTPException(status_code=400, detail="no tribe")
        t = _row(conn.execute("SELECT * FROM tribes WHERE tribe_id = ?", (u["tribe_id"],)).fetchone())
        nxt = ladder_at(t["level"] + 1)
        if nxt.get("level") == t["level"]:
            raise HTTPException(status_code=400, detail="max stage")
        cost = int(nxt.get("cost", 0))
        if int(t["loyalty"]) < cost:
            raise HTTPException(status_code=400, detail="not enough Loyalty")
        conn.execute("UPDATE tribes SET loyalty = loyalty - ?, level = level + 1 WHERE tribe_id = ?",
                     (cost, u["tribe_id"]))
    return JSONResponse({"ok": True, **compute_state(uid, name, uname)})


@app.post("/api/rekindle")
async def api_rekindle(request: Request):
    uid, name, uname, _ = await _who(request)
    body = await body_of(request)
    target = str(body.get("user_id", ""))
    # In DEV_MODE we allow a direct (free) rekindle; in prod it is Stars-gated
    # via the store invoice flow (kind == 'rekindle') which calls this on success.
    if not DEV_MODE and not body.get("paid"):
        raise HTTPException(status_code=402, detail="buy a Rekindle in the store")
    with db() as conn:
        ensure_user(conn, uid, name, uname)
        res = do_rekindle(conn, uid, target)
    return JSONResponse({"ok": True, "result": res, **compute_state(uid, name, uname)})

# --------------------------------------------------------------------------- #
# Leaderboards, tribe directory, lands, inventory, bloodline                  #
# --------------------------------------------------------------------------- #
@app.get("/api/leaderboard/tribes")
async def api_lb_tribes(request: Request):
    uid, name, uname, _ = await _who(request)
    with db() as conn:
        u = ensure_user(conn, uid, name, uname)
        rows = _rows(conn.execute(
            "SELECT tribe_id, name, crest, color, loyalty_earned, level FROM tribes ORDER BY loyalty_earned DESC LIMIT 50").fetchall())
        out = []
        for i, r in enumerate(rows):
            r["position"] = i + 1
            r["members"] = tribe_member_count(conn, r["tribe_id"])
            r["is_mine"] = (r["tribe_id"] == u.get("tribe_id"))
            out.append(r)
    return JSONResponse({"tribes": out})


@app.get("/api/leaderboard/kin")
async def api_lb_kin(request: Request):
    uid, name, uname, _ = await _who(request)
    with db() as conn:
        u = ensure_user(conn, uid, name, uname)
        tid = u.get("tribe_id")
        if not tid:
            return JSONResponse({"kin": []})
        roster = tribe_roster(conn, tid)
        for m in roster:
            m["is_me"] = (m["user_id"] == uid)
    return JSONResponse({"kin": roster})


@app.get("/api/tribes")
async def api_tribes(request: Request):
    await get_user(request)
    with db() as conn:
        rows = _rows(conn.execute(
            "SELECT tribe_id, name, crest, color, level, loyalty_earned FROM tribes ORDER BY loyalty_earned DESC LIMIT 50").fetchall())
        for r in rows:
            r["members"] = tribe_member_count(conn, r["tribe_id"])
            r["max_members"] = ladder_at(r["level"]).get("max_members")
    return JSONResponse({"tribes": rows})


@app.get("/api/lands")
async def api_lands(request: Request):
    uid, name, uname, _ = await _who(request)
    with db() as conn:
        u = ensure_user(conn, uid, name, uname)
        return JSONResponse({"lands": lands_state(conn), "my_tribe": u.get("tribe_id") or ""})


@app.post("/api/lands/stake")
async def api_land_stake(request: Request):
    """Stake Embertide to claim an empty land or reinforce your own."""
    uid, name, uname, _ = await _who(request)
    body = await body_of(request)
    lid = str(body.get("land_id", ""))
    amount = max(0, int(body.get("amount", 0)))
    inv = cfg().get("invasion", {})
    with db() as conn:
        u = ensure_user(conn, uid, name, uname)
        tid = u.get("tribe_id")
        if not tid:
            raise HTTPException(status_code=400, detail="join a tribe first")
        ensure_lands(conn)
        l = _row(conn.execute("SELECT * FROM lands WHERE land_id = ?", (lid,)).fetchone())
        if not l:
            raise HTTPException(status_code=404, detail="no such land")
        t = _row(conn.execute("SELECT embertide FROM tribes WHERE tribe_id = ?", (tid,)).fetchone())
        if int(t["embertide"]) < amount or amount <= 0:
            raise HTTPException(status_code=400, detail="not enough Embertide")
        cost = int(int(inv.get("base_hold_cost", 1000)) * float(age_now().get("invade_cost_multiplier", 1.0)))
        if l.get("owner_tribe") and l["owner_tribe"] != tid:
            raise HTTPException(status_code=400, detail="held by another tribe - invade instead")
        if not l.get("owner_tribe") and amount < cost:
            raise HTTPException(status_code=400, detail=f"need {cost} Embertide to claim")
        add_embertide(conn, tid, -amount)
        conn.execute("UPDATE lands SET owner_tribe = ?, staked = staked + ? WHERE land_id = ?",
                     (tid, amount, lid))
    return JSONResponse({"ok": True, **compute_state(uid, name, uname)})


@app.post("/api/lands/invade")
async def api_land_invade(request: Request):
    uid, name, uname, _ = await _who(request)
    body = await body_of(request)
    lid = str(body.get("land_id", ""))
    amount = max(0, int(body.get("amount", 0)))
    inv = cfg().get("invasion", {})
    now = _now()
    with db() as conn:
        u = ensure_user(conn, uid, name, uname)
        tid = u.get("tribe_id")
        if not tid:
            raise HTTPException(status_code=400, detail="join a tribe first")
        l = _row(conn.execute("SELECT * FROM lands WHERE land_id = ?", (lid,)).fetchone())
        if not l or not l.get("owner_tribe"):
            raise HTTPException(status_code=400, detail="nothing to invade - stake to claim")
        if l["owner_tribe"] == tid:
            raise HTTPException(status_code=400, detail="you already hold this land")
        cd = parse_iso(l.get("cooldown_until"))
        if cd and cd > now:
            raise HTTPException(status_code=400, detail="land is on cooldown")
        t = _row(conn.execute("SELECT embertide FROM tribes WHERE tribe_id = ?", (tid,)).fetchone())
        if amount <= 0 or int(t["embertide"]) < amount:
            raise HTTPException(status_code=400, detail="not enough Embertide")
        ce = parse_iso(l.get("contest_ends"))
        if l.get("attacker_tribe") and ce and ce > now:
            if l["attacker_tribe"] != tid:
                raise HTTPException(status_code=400, detail="another tribe is already invading")
            add_embertide(conn, tid, -amount)
            conn.execute("UPDATE lands SET attacker_staked = attacker_staked + ? WHERE land_id = ?",
                         (amount, lid))
        else:
            add_embertide(conn, tid, -amount)
            ends = iso(now + timedelta(hours=int(inv.get("contest_window_hours", 24))))
            conn.execute(
                "UPDATE lands SET attacker_tribe = ?, attacker_staked = ?, contest_ends = ? WHERE land_id = ?",
                (tid, amount, ends, lid))
    return JSONResponse({"ok": True, **compute_state(uid, name, uname)})


@app.get("/api/inventory")
async def api_inventory(request: Request):
    uid, name, uname, _ = await _who(request)
    with db() as conn:
        u = ensure_user(conn, uid, name, uname)
        satchel = inventory_of(conn, uid, "user")
        cache = inventory_of(conn, u["tribe_id"], "tribe") if u.get("tribe_id") else []
    return JSONResponse({"satchel": satchel, "tribe_cache": cache, "wards": int(u.get("wards", 0))})


@app.get("/api/bloodline")
async def api_bloodline(request: Request):
    uid, name, uname, _ = await _who(request)
    with db() as conn:
        ensure_user(conn, uid, name, uname)
        rows = _rows(conn.execute(
            "SELECT r.newcomer_id, r.joined_tribe, r.ts, u.name FROM referrals r LEFT JOIN users u ON u.user_id = r.newcomer_id WHERE r.referrer_id = ? ORDER BY r.ts DESC",
            (uid,)).fetchall())
    return JSONResponse({"bloodline": rows, "count": len(rows)})

# --------------------------------------------------------------------------- #
# Store (Telegram Stars) - cosmetic / convenience / social ONLY               #
# --------------------------------------------------------------------------- #
def store_item(item_id: str) -> dict:
    return next((i for i in cfg().get("store", {}).get("items", []) if i["id"] == item_id), None)


def grant_purchase(conn, uid: str, item: dict) -> None:
    kind = item.get("kind")
    if kind in ("freeze", "freeze3", "freeze7"):
        add = {"freeze": 1, "freeze3": 3, "freeze7": 7}[kind]
        conn.execute("UPDATE users SET wards = wards + ? WHERE user_id = ?", (add, uid))
    elif kind == "cosmetic_user":
        _set_cosmetic(conn, uid, "paint", item["id"])
    elif kind == "cosmetic_tribe":
        u = _row(conn.execute("SELECT tribe_id FROM users WHERE user_id = ?", (uid,)).fetchone())
        if u.get("tribe_id"):
            conn.execute("UPDATE tribes SET crest = ? WHERE tribe_id = ?", ("living", u["tribe_id"]))
            _grant(conn, u["tribe_id"], "tribe", item["id"], 1)
    elif kind == "bundle":
        conn.execute("UPDATE users SET wards = wards + 3, title = ? WHERE user_id = ?", ("Founder", uid))
        _set_cosmetic(conn, uid, "paint", "warpaint")
    _grant(conn, uid, "user", item["id"], 1)


def _set_cosmetic(conn, uid: str, key: str, val: str) -> None:
    u = _row(conn.execute("SELECT cosmetics FROM users WHERE user_id = ?", (uid,)).fetchone())
    try:
        cos = json.loads(u.get("cosmetics") or "{}")
    except Exception:
        cos = {}
    cos[key] = val
    conn.execute("UPDATE users SET cosmetics = ? WHERE user_id = ?", (json.dumps(cos), uid))


@app.get("/api/store")
async def api_store(request: Request):
    uid, name, uname, _ = await _who(request)
    with db() as conn:
        u = ensure_user(conn, uid, name, uname)
    st = cfg().get("store", {})
    return JSONResponse({"sections": st.get("sections", []), "items": st.get("items", []),
                         "wards": int(u.get("wards", 0)), "payments_live": not DEV_MODE})


@app.post("/api/store/buy_demo")
async def api_buy_demo(request: Request):
    """DEV_MODE only: grant an item without payment so the flow is testable."""
    if not DEV_MODE:
        raise HTTPException(status_code=400, detail="live payments only - use the Stars button")
    uid, name, uname, _ = await _who(request)
    body = await body_of(request)
    item = store_item(str(body.get("item_id", "")))
    if not item:
        raise HTTPException(status_code=404, detail="no such item")
    with db() as conn:
        ensure_user(conn, uid, name, uname)
        grant_purchase(conn, uid, item)
    return JSONResponse({"ok": True, **compute_state(uid, name, uname)})


def _tg_call(method: str, payload: dict) -> dict:
    url = f"{TG_API}/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def tg_call(method: str, payload: dict) -> dict:
    return await asyncio.to_thread(_tg_call, method, payload)


@app.post("/api/store/invoice")
async def api_invoice(request: Request):
    uid, name, uname, _ = await _who(request)
    if DEV_MODE:
        raise HTTPException(status_code=400, detail="no BOT_TOKEN: use demo purchase")
    body = await body_of(request)
    item = store_item(str(body.get("item_id", "")))
    if not item:
        raise HTTPException(status_code=404, detail="no such item")
    payload = json.dumps({"uid": uid, "item": item["id"],
                          "target": str(body.get("target", ""))})
    res = await tg_call("createInvoiceLink", {
        "title": item["title"][:32], "description": item.get("desc", "")[:255],
        "payload": payload, "currency": "XTR",
        "prices": [{"label": item["title"][:32], "amount": int(item["stars"])}],
    })
    if not res.get("ok"):
        raise HTTPException(status_code=502, detail="could not create invoice")
    return JSONResponse({"invoice_link": res["result"]})


@app.post("/api/telegram/webhook")
async def tg_webhook(request: Request):
    update = await body_of(request)
    # Save bot username if present (used for referral links)
    msg = update.get("message") or {}
    if msg.get("successful_payment"):
        sp = msg["successful_payment"]
        try:
            payload = json.loads(sp.get("invoice_payload", "{}"))
        except Exception:
            payload = {}
        uid = str(payload.get("uid", ""))
        item = store_item(payload.get("item", ""))
        charge = sp.get("telegram_payment_charge_id", "")
        if uid and item:
            with db() as conn:
                if not conn.execute("SELECT 1 FROM payments WHERE charge_id = ?", (charge,)).fetchone():
                    conn.execute("INSERT OR IGNORE INTO payments (charge_id, user_id, item_id, stars, ts) VALUES (?, ?, ?, ?, ?)",
                                 (charge, uid, item["id"], int(item.get("stars", 0)), iso(_now())))
                    if item.get("kind") == "rekindle" and payload.get("target"):
                        try:
                            do_rekindle(conn, uid, str(payload["target"]))
                        except Exception:
                            pass
                    else:
                        grant_purchase(conn, uid, item)
    pcq = update.get("pre_checkout_query")
    if pcq:
        await tg_call("answerPreCheckoutQuery", {"pre_checkout_query_id": pcq["id"], "ok": True})
    return JSONResponse({"ok": True})

# --------------------------------------------------------------------------- #
# Elders' Forge - admin panel (@Joeldan). initData is HMAC-verified, so the    #
# username here is trusted. Every write persists via the settings table.       #
# --------------------------------------------------------------------------- #
@app.get("/api/admin/config")
async def admin_get_config(request: Request):
    user = await get_user(request)
    require_admin(user)
    return JSONResponse({"config": cfg(), "override": get_setting("config_override", {}),
                         "bot_username": bot_username()})


@app.post("/api/admin/config")
async def admin_patch_config(request: Request):
    user = await get_user(request)
    require_admin(user)
    body = await body_of(request)
    patch = body.get("patch")
    if not isinstance(patch, dict):
        raise HTTPException(status_code=400, detail="patch must be an object")
    over = get_setting("config_override", {})
    set_setting("config_override", _deep_merge(over, patch))
    return JSONResponse({"ok": True, "config": cfg()})


@app.post("/api/admin/config/reset")
async def admin_reset_config(request: Request):
    user = await get_user(request)
    require_admin(user)
    set_setting("config_override", {})
    return JSONResponse({"ok": True, "config": cfg()})


@app.post("/api/admin/age")
async def admin_set_age(request: Request):
    user = await get_user(request)
    require_admin(user)
    body = await body_of(request)
    age_id = str(body.get("age", ""))
    if age_id not in cfg().get("age", {}).get("ages", {}):
        raise HTTPException(status_code=400, detail="unknown age")
    over = get_setting("config_override", {})
    set_setting("config_override", _deep_merge(over, {"age": {"current": age_id}}))
    return JSONResponse({"ok": True, "age": age_now()})


@app.post("/api/admin/tasks")
async def admin_tasks(request: Request):
    """Add / edit / remove a quest. body: {op: add|edit|remove, task: {...}, id}"""
    user = await get_user(request)
    require_admin(user)
    body = await body_of(request)
    op = body.get("op")
    tasks = list(cfg().get("tasks", []))
    if op in ("add", "edit"):
        task = body.get("task") or {}
        if not task.get("id") or not task.get("title"):
            raise HTTPException(status_code=400, detail="task needs id + title")
        tasks = [t for t in tasks if t["id"] != task["id"]] + [task]
    elif op == "remove":
        tasks = [t for t in tasks if t["id"] != body.get("id")]
    else:
        raise HTTPException(status_code=400, detail="bad op")
    over = get_setting("config_override", {})
    over["tasks"] = tasks
    set_setting("config_override", over)
    return JSONResponse({"ok": True, "tasks": tasks})


@app.post("/api/admin/store")
async def admin_store(request: Request):
    """Add / edit / remove a store item (incl. Star price). body: {op, item, id}"""
    user = await get_user(request)
    require_admin(user)
    body = await body_of(request)
    op = body.get("op")
    st = dict(cfg().get("store", {}))
    items = list(st.get("items", []))
    if op in ("add", "edit"):
        item = body.get("item") or {}
        if not item.get("id") or not item.get("title") or "stars" not in item:
            raise HTTPException(status_code=400, detail="item needs id, title, stars")
        item["stars"] = int(item["stars"])
        items = [i for i in items if i["id"] != item["id"]] + [item]
    elif op == "remove":
        items = [i for i in items if i["id"] != body.get("id")]
    else:
        raise HTTPException(status_code=400, detail="bad op")
    over = get_setting("config_override", {})
    over.setdefault("store", {})
    over["store"]["items"] = items
    set_setting("config_override", over)
    return JSONResponse({"ok": True, "items": items})


@app.post("/api/admin/grant")
async def admin_grant(request: Request):
    """Adjust a tribe's Loyalty/Embertide or a user's Kindle/Ember."""
    user = await get_user(request)
    require_admin(user)
    body = await body_of(request)
    with db() as conn:
        if body.get("tribe_id"):
            if "loyalty" in body:
                credit_loyalty(conn, body["tribe_id"], int(body["loyalty"]), earned=int(body["loyalty"]) > 0)
            if "embertide" in body:
                add_embertide(conn, body["tribe_id"], int(body["embertide"]))
        if body.get("user_id"):
            if "kindle" in body:
                conn.execute("UPDATE users SET kindle = kindle + ? WHERE user_id = ?",
                             (int(body["kindle"]), body["user_id"]))
            if "ember" in body:
                conn.execute("UPDATE users SET ember = ember + ? WHERE user_id = ?",
                             (int(body["ember"]), body["user_id"]))
    return JSONResponse({"ok": True})


@app.post("/api/admin/ashfall")
async def admin_run_ashfall(request: Request):
    user = await get_user(request)
    require_admin(user)
    return JSONResponse(run_ashfall(force=True))


@app.post("/api/admin/bot_username")
async def admin_bot_username(request: Request):
    user = await get_user(request)
    require_admin(user)
    body = await body_of(request)
    set_setting("bot_username", str(body.get("bot_username", "")).lstrip("@"))
    return JSONResponse({"ok": True, "bot_username": bot_username()})

# --------------------------------------------------------------------------- #
# Health, manifest, static frontend                                           #
# --------------------------------------------------------------------------- #
@app.get("/healthz")
async def healthz():
    return {"ok": True, "age": age_now().get("id"), "dev": DEV_MODE}


@app.get("/tonconnect-manifest.json")
async def ton_manifest(request: Request):
    p = FRONTEND_DIR / "tonconnect-manifest.json"
    if p.exists():
        return FileResponse(str(p), media_type="application/json")
    base = str(request.base_url).rstrip("/")
    return JSONResponse({"url": base, "name": "Tribes", "iconUrl": f"{base}/icon.png"})


def _static(name: str, media: str):
    p = FRONTEND_DIR / name
    if p.exists():
        return FileResponse(str(p), media_type=media)
    raise HTTPException(status_code=404, detail="not found")


@app.get("/styles.css")
async def _css():
    return _static("styles.css", "text/css")


@app.get("/app.js")
async def _js():
    return _static("app.js", "application/javascript")


@app.get("/")
async def index():
    return _static("index.html", "text/html")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

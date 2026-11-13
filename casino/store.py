"""Cursed Casino — база (SQLite) и все операции с балансом. Баланс — целые CRX.

Все операции синхронные и без await внутри, а процесс один, поэтому проверка и списание баланса атомарны.
"""
import json
import sqlite3
import time

from . import engine as eng

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, username TEXT, name TEXT,
    balance INTEGER NOT NULL DEFAULT 0,
    created INTEGER, last_daily INTEGER DEFAULT 0,
    ref_by INTEGER, ref_earned INTEGER DEFAULT 0,
    banned INTEGER DEFAULT 0,
    server_seed TEXT, client_seed TEXT, nonce INTEGER DEFAULT 0,
    wagered INTEGER DEFAULT 0, won INTEGER DEFAULT 0, games INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tx (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, delta INTEGER, reason TEXT, note TEXT, created INTEGER
);
CREATE INDEX IF NOT EXISTS tx_user ON tx(user_id, id);
CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, game TEXT, bet INTEGER,
    payout INTEGER DEFAULT 0, status TEXT, state TEXT, nonce INTEGER, created INTEGER
);
CREATE INDEX IF NOT EXISTS rounds_user ON rounds(user_id, id);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULTS = {"rtp": "0.96", "start_coins": "100", "min_bet": "1", "max_bet": "50000",
            "daily_scale": "1", "ref_percent": "5", "support": "", "brand": "Cursed Casino"}

_con = None


def connect(path):
    global _con
    _con = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    _con.row_factory = sqlite3.Row
    _con.execute("PRAGMA journal_mode=WAL")
    _con.executescript(SCHEMA)
    return _con


def q(sql, args=()):
    return _con.execute(sql, args)


def now():
    return int(time.time())

# ---------------------------------------------------------------- настройки

def get(key):
    r = q("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else DEFAULTS.get(key, "")


def put(key, value):
    q("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
      (key, str(value)))


def rtp():
    try:
        return min(0.99, max(0.5, float(get("rtp"))))
    except ValueError:
        return 0.96


def limits():
    try:
        return max(1, int(get("min_bet"))), max(1, int(get("max_bet")))
    except ValueError:
        return 1, 50000

# ---------------------------------------------------------------- пользователи

def user(uid):
    return q("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def touch(uid, username="", name="", ref=None):
    """Создаёт игрока при первом входе (стартовые CRX + реферер), иначе обновляет имя."""
    u = user(uid)
    if u:
        q("UPDATE users SET username=?, name=? WHERE id=?", (username or "", name or "", uid))
        return user(uid), False
    seed = eng.new_seed()
    start = int(get("start_coins") or 0)
    ref = ref if ref and ref != uid and user(ref) else None
    q("INSERT INTO users(id, username, name, balance, created, ref_by, server_seed, client_seed) VALUES(?,?,?,?,?,?,?,?)",
      (uid, username or "", name or "", start, now(), ref, seed, eng.new_seed()[:16]))
    if start:
        q("INSERT INTO tx(user_id, delta, reason, created) VALUES(?,?,?,?)", (uid, start, "start", now()))
    return user(uid), True


def find(text):
    text = str(text).strip().lstrip("@")
    if text.isdigit():
        return user(int(text))
    return q("SELECT * FROM users WHERE lower(username)=lower(?)", (text,)).fetchone()


def change(uid, delta, reason, note=""):
    """Меняет баланс. Уйти в минус нельзя."""
    u = user(uid)
    if not u:
        raise eng.GameError("Игрок не найден")
    if u["balance"] + delta < 0:
        raise eng.GameError("Недостаточно CRX")
    q("UPDATE users SET balance=balance+? WHERE id=?", (delta, uid))
    q("INSERT INTO tx(user_id, delta, reason, note, created) VALUES(?,?,?,?,?)", (uid, delta, reason, note, now()))
    return u["balance"] + delta


def give(uid, amount, paid=True, note=""):
    """Выдача баланса владельцем. paid=True — это покупка: реферер получает свой процент."""
    if amount <= 0:
        raise eng.GameError("Сумма должна быть больше нуля")
    bal = change(uid, amount, "buy" if paid else "gift", note)
    reward = 0
    u = user(uid)
    if paid and u["ref_by"]:
        reward = amount * int(get("ref_percent") or 0) // 100
        if reward > 0:
            change(u["ref_by"], reward, "ref", f"от {uid}")
            q("UPDATE users SET ref_earned=ref_earned+? WHERE id=?", (reward, u["ref_by"]))
    return bal, reward


def ban(uid, flag=True):
    q("UPDATE users SET banned=? WHERE id=?", (1 if flag else 0, uid))

# ---------------------------------------------------------------- честность

def next_nonce(uid):
    u = user(uid)
    q("UPDATE users SET nonce=nonce+1 WHERE id=?", (uid,))
    return u["server_seed"], u["client_seed"], u["nonce"]


def rng_for(uid):
    s, c, n = next_nonce(uid)
    return eng.Rng(s, c, n), n


def fair_info(uid):
    u = user(uid)
    return {"hash": eng.seed_hash(u["server_seed"]), "client_seed": u["client_seed"], "nonce": u["nonce"]}


def rotate_seed(uid, client_seed=None):
    """Раскрывает старый server_seed, ставит новый. Игрок может проверить все прошлые раунды."""
    u = user(uid)
    if open_round(uid):
        raise eng.GameError("Сначала завершите текущую игру")
    old = u["server_seed"]
    new = eng.new_seed()
    cs = (client_seed or u["client_seed"])[:32]
    q("UPDATE users SET server_seed=?, client_seed=?, nonce=0 WHERE id=?", (new, cs, uid))
    return {"revealed": old, "old_client_seed": u["client_seed"], "old_nonce": u["nonce"],
            "hash": eng.seed_hash(new), "client_seed": cs}

# ---------------------------------------------------------------- ставки

def check_bet(bet):
    try:
        bet = int(bet)
    except (TypeError, ValueError):
        raise eng.GameError("Неверная ставка")
    lo, hi = limits()
    if bet < lo or bet > hi:
        raise eng.GameError(f"Ставка — от {lo} до {hi} CRX")
    return bet


def log_round(uid, game, bet, payout, status, state, nonce):
    cur = q("INSERT INTO rounds(user_id, game, bet, payout, status, state, nonce, created) VALUES(?,?,?,?,?,?,?,?)",
            (uid, game, bet, payout, status, json.dumps(state, ensure_ascii=False), nonce, now()))
    return cur.lastrowid


def settle(uid, bet, payout):
    """Статистика игрока после раунда."""
    q("UPDATE users SET wagered=wagered+?, won=won+?, games=games+1 WHERE id=?", (bet, payout, uid))


def instant(uid, game, bet, fn):
    """Одноходовая игра: списали ставку -> посчитали результат -> начислили выигрыш."""
    bet = check_bet(bet)
    u = user(uid)
    if u["balance"] < bet:
        raise eng.GameError("Недостаточно CRX")
    if open_round(uid):
        raise eng.GameError("Сначала завершите текущую игру")
    rng, nonce = rng_for(uid)
    res = fn(bet, rng)
    q("UPDATE users SET balance=balance-? WHERE id=?", (bet, uid))
    q("INSERT INTO tx(user_id, delta, reason, note, created) VALUES(?,?,?,?,?)", (uid, -bet, "bet", game, now()))
    if res["payout"]:
        q("UPDATE users SET balance=balance+? WHERE id=?", (res["payout"], uid))
        q("INSERT INTO tx(user_id, delta, reason, note, created) VALUES(?,?,?,?,?)", (uid, res["payout"], "win", game, now()))
    settle(uid, bet, res["payout"])
    rid = log_round(uid, game, bet, res["payout"], "done", res, nonce)
    res.update(round=rid, nonce=nonce, balance=user(uid)["balance"], bet=bet)
    return res

# ---------------------------------------------------------------- игры с несколькими ходами (краш, мины)

def open_round(uid, game=None):
    sql = "SELECT * FROM rounds WHERE user_id=? AND status='open'" + (" AND game=?" if game else "")
    return q(sql + " ORDER BY id DESC LIMIT 1", (uid, game) if game else (uid,)).fetchone()


def start_round(uid, game, bet, state, nonce):
    bet = check_bet(bet)
    if user(uid)["balance"] < bet:
        raise eng.GameError("Недостаточно CRX")
    if open_round(uid):
        raise eng.GameError("Сначала завершите текущую игру")
    q("UPDATE users SET balance=balance-? WHERE id=?", (bet, uid))
    q("INSERT INTO tx(user_id, delta, reason, note, created) VALUES(?,?,?,?,?)", (uid, -bet, "bet", game, now()))
    return log_round(uid, game, bet, 0, "open", state, nonce), bet


def finish_round(r, payout, status, state):
    if payout:
        q("UPDATE users SET balance=balance+? WHERE id=?", (payout, r["user_id"]))
        q("INSERT INTO tx(user_id, delta, reason, note, created) VALUES(?,?,?,?,?)",
          (r["user_id"], payout, "win", r["game"], now()))
    settle(r["user_id"], r["bet"], payout)
    q("UPDATE rounds SET status=?, payout=?, state=? WHERE id=?", (status, payout, json.dumps(state), r["id"]))


def history(uid, limit=30):
    rows = q("SELECT id, game, bet, payout, status, created FROM rounds WHERE user_id=? AND status!='open' "
             "ORDER BY id DESC LIMIT ?", (uid, limit)).fetchall()
    return [dict(r) for r in rows]


def stats():
    r = q("SELECT COUNT(*) n, COALESCE(SUM(balance),0) bal, COALESCE(SUM(wagered),0) wag, COALESCE(SUM(won),0) won, "
          "COALESCE(SUM(games),0) g FROM users").fetchone()
    bought = q("SELECT COALESCE(SUM(delta),0) s FROM tx WHERE reason='buy'").fetchone()["s"]
    return dict(r) | {"bought": bought}

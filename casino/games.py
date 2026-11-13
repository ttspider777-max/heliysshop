"""Cursed Casino — игры поверх базы: одноходовые (монетка, дайс, лимбо, плинко, рулетка) и пошаговые (краш, мины)."""
import json
import time

from . import engine as eng
from . import store

GameError = eng.GameError

# ---------------------------------------------------------------- одноходовые

def play_coin(uid, p):
    side = p.get("side")
    return store.instant(uid, "coin", p.get("bet"), lambda bet, rng: eng.coin(bet, side, rng(), store.rtp()))


def play_dice(uid, p):
    return store.instant(uid, "dice", p.get("bet"),
                         lambda bet, rng: eng.dice(bet, p.get("chance"), p.get("mode"), rng(), store.rtp()))


def play_limbo(uid, p):
    return store.instant(uid, "limbo", p.get("bet"),
                         lambda bet, rng: eng.limbo(bet, p.get("target"), rng(), store.rtp()))


def play_plinko(uid, p):
    rows, risk = int(p.get("rows") or 0), p.get("risk")
    return store.instant(uid, "plinko", p.get("bet"), lambda bet, rng: eng.plinko(bet, rows, risk, rng, store.rtp()))


def play_roulette(uid, p):
    bets = p.get("bets") or []
    if not isinstance(bets, list):
        raise GameError("Сделайте ставку")
    total = 0
    for b in bets:
        if not isinstance(b, dict):
            raise GameError("Неверная ставка")
        try:
            b["amount"] = int(b.get("amount") or 0)
        except (TypeError, ValueError):
            raise GameError("Неверная ставка")
        total += b["amount"]
    store.check_bet(total)
    return store.instant(uid, "roulette", total, lambda bet, rng: eng.roulette(bets, rng()))


def plinko_tables():
    r = store.rtp()
    return {f"{rows}:{risk}": list(eng.plinko_table(rows, risk, r)) for rows in range(8, 17) for risk in eng.PLINKO_G}

# ---------------------------------------------------------------- краш (раунд идёт по времени на сервере)

CRASH_MAX_WAIT = 600  # сек: забытый раунд закрывается как проигрыш


def _crash_view(r, st):
    return {"round": r["id"], "bet": r["bet"], "status": r["status"], "auto": st.get("auto"), "started": st["t0"]}


def crash_start(uid, p):
    bet = store.check_bet(p.get("bet"))
    auto = p.get("auto")
    if auto not in (None, ""):
        try:
            auto = round(float(auto), 2)
        except (TypeError, ValueError):
            raise GameError("Неверный автовывод")
        if not 1.01 <= auto <= 1000:
            raise GameError("Автовывод — от 1.01 до 1000")
    else:
        auto = None
    if store.user(uid)["balance"] < bet:
        raise GameError("Недостаточно CRX")
    if store.open_round(uid):
        raise GameError("Сначала завершите текущую игру")
    rng, nonce = store.rng_for(uid)
    point = eng.crash_point(rng(), store.rtp())
    st = {"point": point, "t0": time.time(), "auto": auto}
    rid, bet = store.start_round(uid, "crash", bet, st, nonce)
    return {"round": rid, "bet": bet, "auto": auto, "balance": store.user(uid)["balance"]}


def _crash_resolve(r, now=None, cash=False):
    """Приводит раунд к текущему моменту. Возвращает (state, dict-ответ)."""
    st = json.loads(r["state"])
    now = now or time.time()
    elapsed = now - st["t0"]
    point = st["point"]
    crash_at = eng.crash_time(point)
    auto = st.get("auto")
    auto_at = eng.crash_time(auto) if auto else None
    # авто-вывод сработал раньше вылета
    if auto and auto <= point and elapsed >= auto_at:
        return _crash_close(r, st, "cashed", auto, auto_at)
    if elapsed >= crash_at:
        return _crash_close(r, st, "crashed", point, crash_at)
    if elapsed > CRASH_MAX_WAIT:
        return _crash_close(r, st, "crashed", point, crash_at)
    mult = eng.crash_mult(elapsed)
    if cash:
        mult = max(1.0, mult)
        return _crash_close(r, st, "cashed", mult, elapsed)
    return {"status": "open", "mult": mult, "elapsed": round(elapsed, 2)}


def _crash_close(r, st, status, mult, at):
    payout = eng.pay(r["bet"], mult) if status == "cashed" else 0
    st.update(final=mult, at=round(at, 2))
    store.finish_round(r, payout, status, st)
    return {"status": status, "mult": mult, "payout": payout, "point": st["point"],
            "balance": store.user(r["user_id"])["balance"], "nonce": r["nonce"]}


def crash_state(uid, p):
    r = store.open_round(uid, "crash")
    if not r:
        raise GameError("Раунд не найден")
    return _crash_resolve(r)


def crash_cash(uid, p):
    r = store.open_round(uid, "crash")
    if not r:
        raise GameError("Раунд уже завершён")
    return _crash_resolve(r, cash=True)

# ---------------------------------------------------------------- мины

def mines_start(uid, p):
    try:
        count = int(p.get("mines"))
    except (TypeError, ValueError):
        raise GameError("Выберите число мин")
    bet = store.check_bet(p.get("bet"))
    if store.user(uid)["balance"] < bet:
        raise GameError("Недостаточно CRX")
    if store.open_round(uid):
        raise GameError("Сначала завершите текущую игру")
    rng, nonce = store.rng_for(uid)
    layout = eng.mines_layout(count, rng)
    st = {"mines": layout, "count": count, "open": []}
    rid, bet = store.start_round(uid, "mines", bet, st, nonce)
    return {"round": rid, "bet": bet, "count": count, "next": eng.mines_mult(count, 1, store.rtp()),
            "balance": store.user(uid)["balance"]}


def _mines_save(r, st):
    store.q("UPDATE rounds SET state=? WHERE id=?", (json.dumps(st), r["id"]))


def mines_open(uid, p):
    r = store.open_round(uid, "mines")
    if not r:
        raise GameError("Игра не найдена")
    st = json.loads(r["state"])
    try:
        cell = int(p.get("cell"))
    except (TypeError, ValueError):
        raise GameError("Неверная клетка")
    if not 0 <= cell < eng.MINES_CELLS or cell in st["open"]:
        raise GameError("Клетка уже открыта")
    rtp = store.rtp()
    if cell in st["mines"]:
        st["hit"] = cell
        store.finish_round(r, 0, "lost", st)
        return {"status": "lost", "cell": cell, "mines": st["mines"], "payout": 0,
                "balance": store.user(uid)["balance"], "nonce": r["nonce"]}
    st["open"].append(cell)
    safe_total = eng.MINES_CELLS - st["count"]
    mult = eng.mines_mult(st["count"], len(st["open"]), rtp)
    if len(st["open"]) == safe_total:  # открыты все безопасные — забираем автоматически
        payout = eng.pay(r["bet"], mult)
        store.finish_round(r, payout, "cashed", st)
        return {"status": "cashed", "cell": cell, "mult": mult, "payout": payout, "mines": st["mines"],
                "balance": store.user(uid)["balance"], "nonce": r["nonce"]}
    _mines_save(r, st)
    return {"status": "open", "cell": cell, "mult": mult, "next": eng.mines_mult(st["count"], len(st["open"]) + 1, rtp),
            "payout_now": eng.pay(r["bet"], mult)}


def mines_cash(uid, p):
    r = store.open_round(uid, "mines")
    if not r:
        raise GameError("Игра не найдена")
    st = json.loads(r["state"])
    if not st["open"]:
        raise GameError("Откройте хотя бы одну клетку")
    mult = eng.mines_mult(st["count"], len(st["open"]), store.rtp())
    payout = eng.pay(r["bet"], mult)
    store.finish_round(r, payout, "cashed", st)
    return {"status": "cashed", "mult": mult, "payout": payout, "mines": st["mines"],
            "balance": store.user(uid)["balance"], "nonce": r["nonce"]}


def resume(uid):
    """Незавершённая игра — приложение продолжит её после перезахода."""
    r = store.open_round(uid)
    if not r:
        return None
    st = json.loads(r["state"])
    if r["game"] == "crash":
        res = _crash_resolve(r)
        if res["status"] != "open":
            return {"game": "crash", "finished": res}
        return {"game": "crash", "round": r["id"], "bet": r["bet"], "auto": st.get("auto"), **res}
    if r["game"] == "mines":
        rtp = store.rtp()
        n = len(st["open"])
        return {"game": "mines", "round": r["id"], "bet": r["bet"], "count": st["count"], "open": st["open"],
                "mult": eng.mines_mult(st["count"], n, rtp), "next": eng.mines_mult(st["count"], n + 1, rtp)}
    return None

# ---------------------------------------------------------------- ежедневный кейс

DAILY_COOLDOWN = 24 * 3600


def daily_left(u):
    return max(0, (u["last_daily"] or 0) + DAILY_COOLDOWN - store.now())


def daily(uid, p=None):
    u = store.user(uid)
    left = daily_left(u)
    if left:
        raise GameError(f"Кейс откроется через {left // 3600} ч {left % 3600 // 60} мин")
    rng, nonce = store.rng_for(uid)
    prize = eng.daily_case(rng(), int(store.get("daily_scale") or 1))
    store.q("UPDATE users SET last_daily=? WHERE id=?", (store.now(), uid))
    bal = store.change(uid, prize, "daily")
    return {"prize": prize, "balance": bal, "left": DAILY_COOLDOWN,
            "prizes": [x for x, _ in eng.DAILY_PRIZES]}

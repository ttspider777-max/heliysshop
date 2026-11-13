"""Cursed Casino — игровое ядро. Только чистая логика, без базы и сети (поэтому её легко проверять тестами).

Валюта CRX — внутриигровая, целые числа. Каждая игра берёт случайные числа u в [0, 1) из provably fair
(см. fair_float): HMAC-SHA256(server_seed, "client_seed:nonce:cursor"). Хэш server_seed игрок видит до игры,
сам seed — после смены, так что проверить честность раунда может каждый.
"""
import hashlib
import hmac
import math
import secrets
from functools import lru_cache

# ---------------------------------------------------------------- provably fair

def new_seed():
    return secrets.token_hex(32)


def seed_hash(server_seed):
    return hashlib.sha256(server_seed.encode()).hexdigest()


def fair_float(server_seed, client_seed, nonce, cursor=0):
    """Число в [0, 1), одинаково воспроизводится у игрока при проверке."""
    msg = f"{client_seed}:{nonce}:{cursor}".encode()
    digest = hmac.new(server_seed.encode(), msg, hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big") / 2 ** 64


class Rng:
    """Поток случайных чисел одного раунда: каждый вызов берёт следующий cursor."""

    def __init__(self, server_seed, client_seed, nonce):
        self.s, self.c, self.n, self.i = server_seed, client_seed, nonce, 0

    def __call__(self):
        v = fair_float(self.s, self.c, self.n, self.i)
        self.i += 1
        return v


class GameError(Exception):
    """Ошибка ввода игрока (показывается в приложении как есть)."""


def pay(bet, mult):
    return int(math.floor(bet * mult + 1e-9))

# ---------------------------------------------------------------- монетка

def coin(bet, side, u, rtp):
    if side not in ("h", "t"):
        raise GameError("Выберите орла или решку")
    flip = "h" if u < 0.5 else "t"
    mult = 2 * rtp
    win = flip == side
    return {"flip": flip, "win": win, "mult": round(mult, 4), "payout": pay(bet, mult) if win else 0}

# ---------------------------------------------------------------- дайс

def dice(bet, chance, mode, u, rtp):
    """chance — шанс выигрыша в %, 1..95. under: выпало < chance; over: выпало >= 100 - chance."""
    try:
        chance = float(chance)
    except (TypeError, ValueError):
        raise GameError("Неверный шанс")
    if not 1 <= chance <= 95 or mode not in ("under", "over"):
        raise GameError("Шанс — от 1% до 95%")
    chance = round(chance, 2)
    roll = math.floor(u * 10000) / 100
    win = roll < chance if mode == "under" else roll >= 100 - chance
    mult = rtp * 100 / chance
    return {"roll": roll, "win": win, "chance": chance, "mult": round(mult, 4), "payout": pay(bet, mult) if win else 0}

# ---------------------------------------------------------------- лимбо и краш

def crash_point(u, rtp):
    """Точка вылета: шанс дожить до x равен rtp / x."""
    return max(1.0, math.floor(100 * rtp / (1 - u)) / 100)


def limbo(bet, target, u, rtp):
    try:
        target = round(float(target), 2)
    except (TypeError, ValueError):
        raise GameError("Неверный множитель")
    if not 1.01 <= target <= 1000:
        raise GameError("Множитель — от 1.01 до 1000")
    point = crash_point(u, rtp)
    win = point >= target
    return {"point": point, "win": win, "mult": target, "payout": pay(bet, target) if win else 0}


CRASH_SPEED = 0.08   # m(t) = e^(speed * t): 10 с — x2.2, 30 с — x11


def crash_mult(elapsed):
    return math.floor(100 * math.exp(CRASH_SPEED * max(0.0, elapsed))) / 100


def crash_time(mult):
    return math.log(max(mult, 1.0)) / CRASH_SPEED

# ---------------------------------------------------------------- мины

MINES_CELLS = 25


def mines_layout(count, rng):
    if not 1 <= count <= 24:
        raise GameError("Мин — от 1 до 24")
    cells = list(range(MINES_CELLS))
    for i in range(MINES_CELLS - 1, 0, -1):  # тасование Фишера — Йейтса
        j = int(rng() * (i + 1))
        cells[i], cells[j] = cells[j], cells[i]
    return sorted(cells[:count])


def mines_mult(count, opened, rtp):
    """Множитель после opened безопасных клеток: rtp / вероятность дойти до этого шага."""
    if opened <= 0:
        return 1.0
    p = math.comb(MINES_CELLS - count, opened) / math.comb(MINES_CELLS, opened)
    return max(1.0, math.floor(100 * rtp / p) / 100)

# ---------------------------------------------------------------- плинко

PLINKO_G = {"low": 0.8, "medium": 1.7, "high": 2.6}


@lru_cache(maxsize=None)
def plinko_table(rows, risk, rtp):
    if rows not in range(8, 17) or risk not in PLINKO_G:
        raise GameError("Неверные настройки плинко")
    g, c = PLINKO_G[risk], rows / 2
    raw = [(1 + abs(i - c)) ** g for i in range(rows + 1)]
    prob = [math.comb(rows, i) / 2 ** rows for i in range(rows + 1)]
    k = rtp / sum(p * r for p, r in zip(prob, raw))
    return tuple(max(0.1, math.floor(100 * r * k) / 100) for r in raw)


def plinko(bet, rows, risk, rng, rtp):
    table = plinko_table(rows, risk, rtp)
    path = [1 if rng() >= 0.5 else 0 for _ in range(rows)]
    slot = sum(path)
    mult = table[slot]
    return {"path": path, "slot": slot, "mult": mult, "payout": pay(bet, mult), "win": mult >= 1}

# ---------------------------------------------------------------- рулетка

REDS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def roulette_color(n):
    return "green" if n == 0 else ("red" if n in REDS else "black")


def _roulette_wins(kind, n, number):
    if kind == "num":
        return n == number
    if n == 0:
        return False
    return {"red": n in REDS, "black": n not in REDS, "even": n % 2 == 0, "odd": n % 2 == 1,
            "low": n <= 18, "high": n >= 19,
            "d1": n <= 12, "d2": 13 <= n <= 24, "d3": n >= 25}.get(kind, False)


ROULETTE_MULT = {"num": 36, "red": 2, "black": 2, "even": 2, "odd": 2, "low": 2, "high": 2, "d1": 3, "d2": 3, "d3": 3}


def roulette(bets, u):
    """bets: [{"kind", "number", "amount"}]. Один спин на все ставки."""
    if not bets or len(bets) > 20:
        raise GameError("Сделайте ставку")
    n = int(u * 37)
    total_bet = total_pay = 0
    detail = []
    for b in bets:
        kind, amount = b.get("kind"), int(b.get("amount") or 0)
        number = b.get("number")
        if kind not in ROULETTE_MULT or amount < 1:
            raise GameError("Неверная ставка")
        if kind == "num" and (not isinstance(number, int) or not 0 <= number <= 36):
            raise GameError("Число — от 0 до 36")
        won = _roulette_wins(kind, n, number)
        p = amount * ROULETTE_MULT[kind] if won else 0
        total_bet += amount
        total_pay += p
        detail.append({"kind": kind, "number": number, "amount": amount, "win": won, "payout": p})
    return {"number": n, "color": roulette_color(n), "bet": total_bet, "payout": total_pay, "detail": detail,
            "win": total_pay >= total_bet}

# ---------------------------------------------------------------- ежедневный кейс

DAILY_PRIZES = [(1, 45), (3, 25), (5, 15), (10, 8), (25, 4), (50, 2), (100, 0.8), (250, 0.15), (500, 0.05)]


def daily_case(u, scale=1):
    total = sum(w for _, w in DAILY_PRIZES)
    x = u * total
    for prize, w in DAILY_PRIZES:
        x -= w
        if x < 0:
            return prize * scale
    return DAILY_PRIZES[-1][0] * scale

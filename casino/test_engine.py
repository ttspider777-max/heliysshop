"""Проверка ядра: python -m casino.test_engine (из папки heliys_shop_bot). Симулирует игры и сверяет возврат игрокам (RTP)."""
import random

from . import engine as e

RTP = 0.96
N = 400_000
rnd = random.Random(12345)
BET = 1000


def check(name, total_pay, n, expect=RTP, tol=0.02):
    got = total_pay / (n * BET)
    ok = abs(got - expect) <= tol
    print(f"{'OK ' if ok else 'ERR'} {name:<28} RTP {got:.4f} (ожидалось ~{expect})")
    assert ok, name


def sim(fn, n=N, **kw):
    return sum(fn(rnd.random()) for _ in range(n))


check("монетка", sim(lambda u: e.coin(BET, "h", u, RTP)["payout"]), N)
for ch, mode in ((50, "under"), (50, "over"), (10, "under"), (90, "over")):
    check(f"дайс {mode} {ch}%", sim(lambda u: e.dice(BET, ch, mode, u, RTP)["payout"]), N)
for tg in (1.5, 2, 10):
    check(f"лимбо x{tg}", sim(lambda u: e.limbo(BET, tg, u, RTP)["payout"]), N, tol=0.05 if tg >= 10 else 0.02)
for rows in (8, 12, 16):
    for risk in ("low", "medium", "high"):
        class R:
            def __call__(self):
                return rnd.random()
        total = sum(e.plinko(BET, rows, risk, R(), RTP)["payout"] for _ in range(200_000))
        check(f"плинко {rows} {risk}", total, 200_000, tol=0.05)
check("рулетка красное", sim(lambda u: e.roulette([{"kind": "red", "amount": BET}], u)["payout"]), N, 0.973, 0.02)
check("рулетка число", sim(lambda u: e.roulette([{"kind": "num", "number": 7, "amount": BET}], u)["payout"]), N, 0.973, 0.05)

# мины: стратегия «открыть k клеток и забрать» — вероятность дойти по формуле, RTP ≈ rtp
for mines, k in ((3, 3), (5, 2), (10, 1)):
    total = 0
    for _ in range(100_000):
        cells = set(rnd.sample(range(25), mines))
        picks = rnd.sample(range(25), k)
        if not (cells & set(picks)):
            total += e.pay(BET, e.mines_mult(mines, k, RTP))
    check(f"мины {mines} мин, {k} клеток", total, 100_000, tol=0.04)

# краш: дожить до x с вероятностью rtp / x
hits = sum(1 for _ in range(N) if e.crash_point(rnd.random(), RTP) >= 2) / N
print(f"OK  шанс дожить до x2: {hits:.4f} (ожидалось {RTP / 2:.4f})")
assert abs(hits - RTP / 2) < 0.01

# ежедневный кейс: средний приз
avg = sum(e.daily_case(rnd.random()) for _ in range(N)) / N
print(f"OK  ежедневный кейс: среднее {avg:.2f} CRX")

# provably fair воспроизводится
s, c = e.new_seed(), "client"
assert e.fair_float(s, c, 5, 0) == e.fair_float(s, c, 5, 0) and e.fair_float(s, c, 5, 0) != e.fair_float(s, c, 6, 0)
assert len(e.mines_layout(5, e.Rng(s, c, 1))) == 5
assert e.mines_layout(5, e.Rng(s, c, 1)) == e.mines_layout(5, e.Rng(s, c, 1))
print("OK  provably fair воспроизводится")

# краши мультипликатор монотонен
assert e.crash_mult(0) == 1.0 and e.crash_mult(10) > e.crash_mult(5) > 1.0
print("ВСЁ ОК")

"""Сквозная проверка API: python -m casino.test_api (из папки heliys_shop_bot). Без Telegram: initData подписывается тестовым токеном."""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from urllib.parse import urlencode

sys.argv = [sys.argv[0]]
os.environ["BOT_TOKEN"] = "123456:TESTTOKEN_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
os.environ["OWNER_IDS"] = "1"

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from . import config, engine, games, store, web  # noqa: E402


def init_data(uid, name="Tester", age=0, token=None):
    d = {"auth_date": str(int(time.time()) - age), "user": json.dumps({"id": uid, "first_name": name, "username": f"u{uid}"})}
    check = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    secret = hmac.new(b"WebAppData", (token or config.BOT_TOKEN).encode(), hashlib.sha256).digest()
    d["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(d)


async def main():
    tmp = tempfile.mkdtemp()
    store.connect(os.path.join(tmp, "t.db"))
    client = TestClient(TestServer(web.make_app()))
    await client.start_server()

    async def call(path, uid=100, body=None, hdr=None):
        h = {"X-Init-Data": init_data(uid)} if hdr is None else hdr
        r = await client.post(f"/api/{path}", json=body or {}, headers=h)
        return await r.json()

    # авторизация
    assert (await call("me", hdr={}))["ok"] is False
    assert (await call("me", hdr={"X-Init-Data": init_data(100, token="1:other")}))["ok"] is False
    assert (await call("me", hdr={"X-Init-Data": init_data(100, age=999999)}))["ok"] is False
    me = await call("me")
    assert me["ok"] and me["balance"] == 100, me
    print("OK  авторизация, стартовые 100 CRX")

    # ставки: лимиты и нехватка
    for bad in (0, -5, 10 ** 9, "abc", None, 101):
        r = await call("coin", body={"bet": bad, "side": "h"})
        assert r["ok"] is False, (bad, r)
    assert (await call("me"))["balance"] == 100
    print("OK  неверные ставки отклоняются, баланс цел")

    # одноходовые игры: баланс всегда сходится
    start = 100
    for path, body in (("coin", {"bet": 5, "side": "h"}), ("dice", {"bet": 5, "chance": 50, "mode": "over"}),
                       ("limbo", {"bet": 5, "target": 2}), ("plinko", {"bet": 5, "rows": 12, "risk": "high"}),
                       ("roulette", {"bets": [{"kind": "red", "amount": 5}, {"kind": "num", "number": 7, "amount": 5}]})):
        before = (await call("me"))["balance"]
        r = await call(path, body=body)
        assert r["ok"], (path, r)
        assert r["balance"] == before - r["bet"] + r["payout"], (path, r, before)
    print("OK  монетка/дайс/лимбо/плинко/рулетка: баланс сходится")

    # честность: результат раунда воспроизводится по seed после смены
    fair = (await call("me"))["fair"]
    r = await call("coin", body={"bet": 1, "side": "h"})
    rot = await call("fair/rotate", body={})
    assert rot["ok"] and engine.seed_hash(rot["revealed"]) == fair["hash"]
    u = engine.fair_float(rot["revealed"], rot["old_client_seed"], r["nonce"], 0)
    assert engine.coin(1, "h", u, store.rtp())["flip"] == r["flip"]
    print("OK  provably fair: раунд проверяется по раскрытому seed")

    # мины
    store.give(100, 1000, paid=False)
    r = await call("mines/start", body={"bet": 10, "mines": 3})
    assert r["ok"], r
    assert (await call("mines/start", body={"bet": 10, "mines": 3}))["ok"] is False  # две игры сразу нельзя
    assert (await call("coin", body={"bet": 1, "side": "h"}))["ok"] is False
    rnd = json.loads(store.open_round(100)["state"])
    safe = [c for c in range(25) if c not in rnd["mines"]]
    assert (await call("mines/cash", body={}))["ok"] is False  # без открытых клеток
    o = await call("mines/open", body={"cell": safe[0]})
    assert o["ok"] and o["status"] == "open", o
    assert (await call("mines/open", body={"cell": safe[0]}))["ok"] is False
    bal_before = (await call("me"))["balance"]
    c = await call("mines/cash", body={})
    assert c["ok"] and c["status"] == "cashed" and c["balance"] == bal_before + c["payout"] > bal_before, c
    r = await call("mines/start", body={"bet": 10, "mines": 24})
    one = rnd2 = json.loads(store.open_round(100)["state"])
    mine = rnd2["mines"][0]
    lost = await call("mines/open", body={"cell": mine})
    assert lost["status"] == "lost" and lost["payout"] == 0 and store.open_round(100) is None
    print("OK  мины: старт, открытие, вывод, проигрыш, защита от двух игр")

    # краш: проигрыш по времени, ручной вывод, автовывод
    r = await call("crash/start", body={"bet": 10})
    assert r["ok"], r
    row = store.open_round(100)
    st = json.loads(row["state"])
    st["point"] = 5.0
    st["t0"] = time.time() - engine.crash_time(2.0)
    store.q("UPDATE rounds SET state=? WHERE id=?", (json.dumps(st), row["id"]))
    c = await call("crash/cash", body={})
    assert c["ok"] and c["status"] == "cashed" and 1.99 <= c["mult"] <= 2.1, c
    r = await call("crash/start", body={"bet": 10})
    row = store.open_round(100)
    st = json.loads(row["state"])
    st["point"] = 1.5
    st["t0"] = time.time() - engine.crash_time(1.5) - 1
    store.q("UPDATE rounds SET state=? WHERE id=?", (json.dumps(st), row["id"]))
    c = await call("crash/cash", body={})
    assert c["status"] == "crashed" and c["payout"] == 0, c  # не успел
    r = await call("crash/start", body={"bet": 10, "auto": 2})
    row = store.open_round(100)
    st = json.loads(row["state"])
    st["point"] = 9.0
    st["t0"] = time.time() - engine.crash_time(2.0) - 2
    store.q("UPDATE rounds SET state=? WHERE id=?", (json.dumps(st), row["id"]))
    s = await call("crash/state", body={})
    assert s["status"] == "cashed" and s["mult"] == 2.0 and s["payout"] == 20, s
    print("OK  краш: ручной вывод, вылет, автовывод")

    # ежедневный кейс раз в сутки
    d = await call("daily")
    assert d["ok"] and d["prize"] > 0, d
    assert (await call("daily"))["ok"] is False
    print("OK  ежедневный кейс: раз в сутки")

    # выдача баланса и реферал
    store.touch(200, "ref", "Ref")
    store.touch(201, "kid", "Kid", ref=200)
    b200 = store.user(200)["balance"]
    bal, reward = store.give(201, 1000, paid=True)
    assert reward == 50 and store.user(200)["balance"] == b200 + 50
    bal, reward = store.give(201, 1000, paid=False)
    assert reward == 0
    try:
        store.change(201, -10 ** 9, "x")
        raise SystemExit("ERR: ушли в минус")
    except engine.GameError:
        pass
    print("OK  выдача CRX, реферал 5%, минус невозможен")

    # бан
    store.ban(100)
    assert (await call("me"))["ok"] is False
    print("OK  бан")

    # страница
    r = await client.get("/app")
    assert r.status == 200 and "Cursed" in await r.text()
    await client.close()
    print("ВСЁ ОК")


if __name__ == "__main__":
    asyncio.run(main())

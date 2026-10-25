import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, services

STATIC = Path(__file__).resolve().parent.parent / "static"
COOKIE = "gl_session"
SESSION_TTL = 30 * 86400
_starts: dict[str, list[float]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    tasks = [asyncio.create_task(services.expiry_watcher())]
    if services.bot:
        from .bot import dp

        tasks.append(asyncio.create_task(dp.start_polling(services.bot, handle_signals=False)))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def current_user(gl_session: str | None = Cookie(default=None)):
    if not gl_session:
        raise HTTPException(401)
    s = db.one("SELECT * FROM sessions WHERE token=?", (gl_session,))
    if not s or db.now() - s["created"] > SESSION_TTL:
        raise HTTPException(401)
    return db.one("SELECT * FROM users WHERE id=?", (s["user_id"],))


class StartIn(BaseModel):
    username: str
    phone: str = ""


@app.post("/api/auth/start")
async def auth_start(body: StartIn, request: Request):
    ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0]
    hits = [t for t in _starts.get(ip, []) if db.now() - t < 600]
    if len(hits) >= 10:
        raise HTTPException(429, "Слишком много попыток, подождите несколько минут")
    _starts[ip] = hits + [db.now()]

    username = body.username.strip().lstrip("@").lower()
    if not (5 <= len(username) <= 32) or not username.replace("_", "").isalnum():
        raise HTTPException(400, "Некорректный Telegram username")

    u = db.one("SELECT * FROM users WHERE username=?", (username,))
    if u and u["verified"]:
        pass  # вход
    else:
        phone = db.norm_phone(body.phone)
        if len(phone) != 11 or not phone.startswith("7"):
            raise HTTPException(400, "Укажите номер в формате +7XXXXXXXXXX")
        taken = db.one("SELECT id FROM users WHERE phone=? AND verified=1", (phone,))
        if taken:
            raise HTTPException(400, "Этот номер уже зарегистрирован")
        if u:
            db.ex("UPDATE users SET phone=? WHERE id=?", (phone, u["id"]))
        else:
            db.ex(
                "INSERT INTO users(username, phone, created) VALUES(?,?,?)",
                (username, phone, db.now()),
            )
        u = db.one("SELECT * FROM users WHERE username=?", (username,))

    token = secrets.token_urlsafe(16)
    db.ex("INSERT INTO tokens(token, user_id, created) VALUES(?,?,?)", (token, u["id"], db.now()))
    link = f"https://t.me/{config.BOT_USERNAME}?start={token}"
    return {"token": token, "link": link, "mode": "login" if u["verified"] else "register"}


@app.get("/api/auth/poll")
async def auth_poll(token: str, response: Response):
    t = db.one("SELECT * FROM tokens WHERE token=?", (token,))
    if not t or db.now() - t["created"] > 15 * 60:
        return {"status": "expired"}
    if not t["confirmed"]:
        return {"status": "waiting"}
    sess = secrets.token_urlsafe(32)
    db.ex("INSERT INTO sessions(token, user_id, created) VALUES(?,?,?)", (sess, t["user_id"], db.now()))
    db.ex("DELETE FROM tokens WHERE token=?", (token,))
    response.set_cookie(
        COOKIE, sess, max_age=SESSION_TTL, httponly=True, samesite="lax",
        secure=config.SITE_URL.startswith("https"),
    )
    return {"status": "ok"}


@app.post("/api/auth/logout")
async def logout(response: Response, gl_session: str | None = Cookie(default=None)):
    if gl_session:
        db.ex("DELETE FROM sessions WHERE token=?", (gl_session,))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/plans")
async def plans():
    return [{"months": m, "price": p} for m, p in sorted(config.PRICES.items())]


@app.get("/api/me")
async def me(u=Depends(current_user)):
    orders = db.q("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 5", (u["id"],))
    return {
        "username": u["username"],
        "phone": u["phone"],
        "expires_at": u["expires_at"],
        "active": u["expires_at"] > db.now(),
        "sub_url": services.sub_url(u["sub_id"]),
        "orders": [
            {"id": o["id"], "months": o["months"], "amount": o["amount"], "status": o["status"]}
            for o in orders
        ],
    }


class OrderIn(BaseModel):
    months: int


@app.post("/api/orders")
async def create_order(body: OrderIn, u=Depends(current_user)):
    if body.months not in config.PRICES:
        raise HTTPException(400, "Неизвестный тариф")
    amount = config.PRICES[body.months]
    oid = db.ex(
        "INSERT INTO orders(user_id, months, amount, created) VALUES(?,?,?,?)",
        (u["id"], body.months, amount, db.now()),
    )
    return {"id": oid, "amount": amount, "comment": f"GOL-{oid}", "details": config.PAY_DETAILS}


@app.post("/api/orders/{oid}/paid")
async def order_paid(oid: int, u=Depends(current_user)):
    from .bot import pay_keyboard

    o = db.one("SELECT * FROM orders WHERE id=? AND user_id=?", (oid, u["id"]))
    if not o or o["status"] != "pending":
        raise HTTPException(400, "Заказ недоступен")
    db.ex("UPDATE orders SET status='review' WHERE id=?", (oid,))
    await services.notify_admins(
        f"💸 Заказ GOL-{oid}\n@{u['username']} · {o['months']} мес. · {o['amount']} ₽\n"
        "Проверьте поступление и подтвердите:",
        reply_markup=pay_keyboard(oid),
    )
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


app.mount("/", StaticFiles(directory=STATIC), name="static")

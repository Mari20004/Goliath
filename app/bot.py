import html
import time

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from . import config, db, services

router = Router()
dp = Dispatcher()
dp.include_router(router)

TOKEN_TTL = 15 * 60
MENU = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Моя подписка")]], resize_keyboard=True)
ASK_CONTACT = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)


def is_admin(m: Message) -> bool:
    return m.from_user.id in config.ADMIN_IDS


def fmt_date(ts: int) -> str:
    return time.strftime("%d.%m.%Y", time.localtime(ts)) if ts else "—"


def uname(m: Message) -> str:
    return (m.from_user.username or "").lower()


# ---------- подтверждение регистрации / входа ----------

@router.message(CommandStart())
async def start(m: Message, command: CommandObject):
    token = command.args
    if not token:
        await m.answer(
            "Goliath VPN. Регистрация и продление — на сайте. "
            "Здесь я напомню об окончании подписки.",
            reply_markup=MENU,
        )
        return

    t = db.one("SELECT * FROM tokens WHERE token=?", (token,))
    if not t or db.now() - t["created"] > TOKEN_TTL:
        await m.answer("Ссылка устарела. Начните заново на сайте.")
        return
    u = db.one("SELECT * FROM users WHERE id=?", (t["user_id"],))

    if not m.from_user.username:
        await m.answer("У вашего аккаунта Telegram не задан username. Задайте его в настройках и повторите.")
        return
    if uname(m) != u["username"]:
        await m.answer(
            f"На сайте указан @{u['username']}, а вы пишете из @{uname(m)}. "
            "Откройте бота с нужного аккаунта."
        )
        return

    if u["verified"]:  # вход
        if u["tg_id"] != m.from_user.id:
            await m.answer("Этот аккаунт привязан к другому Telegram.")
            return
        db.ex("UPDATE tokens SET confirmed=1 WHERE token=?", (token,))
        await m.answer("✅ Вход подтверждён. Вернитесь на сайт.", reply_markup=MENU)
        return

    # регистрация: просим контакт
    db.ex("UPDATE tokens SET tg_id=? WHERE token=?", (m.from_user.id, token))
    await m.answer(
        "Чтобы подтвердить номер телефона, нажмите кнопку ниже.", reply_markup=ASK_CONTACT
    )


@router.message(F.contact)
async def got_contact(m: Message):
    c = m.contact
    if c.user_id != m.from_user.id:
        await m.answer("Нужно поделиться именно своим номером.", reply_markup=ASK_CONTACT)
        return
    t = db.one(
        "SELECT * FROM tokens WHERE tg_id=? AND confirmed=0 ORDER BY created DESC LIMIT 1",
        (m.from_user.id,),
    )
    if not t or db.now() - t["created"] > TOKEN_TTL:
        await m.answer("Нет активной регистрации. Начните на сайте.", reply_markup=MENU)
        return
    u = db.one("SELECT * FROM users WHERE id=?", (t["user_id"],))
    if db.norm_phone(c.phone_number) != u["phone"]:
        await m.answer("Номер не совпадает с указанным на сайте.", reply_markup=ReplyKeyboardRemove())
        return
    other = db.one("SELECT id FROM users WHERE tg_id=? AND id!=?", (m.from_user.id, u["id"]))
    if other:
        await m.answer("Этот Telegram уже привязан к другому аккаунту.", reply_markup=ReplyKeyboardRemove())
        return
    db.ex("UPDATE users SET tg_id=?, verified=1 WHERE id=?", (m.from_user.id, u["id"]))
    db.ex("UPDATE tokens SET confirmed=1 WHERE token=?", (t["token"],))
    await m.answer("✅ Готово! Вернитесь на сайт — вход выполнится автоматически.", reply_markup=MENU)


# ---------- пользователь ----------

@router.message(Command("status"))
@router.message(F.text == "Моя подписка")
async def status(m: Message):
    u = db.one("SELECT * FROM users WHERE tg_id=? AND verified=1", (m.from_user.id,))
    if not u:
        await m.answer("Вы ещё не зарегистрированы. Сделайте это на сайте.")
        return
    active = u["expires_at"] > db.now()
    link = services.sub_url(u["sub_id"])
    text = f"Статус: {'активна ✅' if active else 'не активна ⛔'}\nДо: {fmt_date(u['expires_at'])}"
    if link:
        text += f"\nСсылка: {link}"
    await m.answer(text)


# ---------- админ ----------

def find_user(ref: str):
    ref = ref.lstrip("@").lower()
    if ref.isdigit():
        return db.one("SELECT * FROM users WHERE tg_id=? OR id=?", (int(ref), int(ref)))
    return db.one("SELECT * FROM users WHERE username=?", (ref,))


@router.message(Command("admin"))
async def admin_help(m: Message):
    if not is_admin(m):
        return
    await m.answer(
        "/users — последние пользователи\n"
        "/msg @user текст — написать пользователю\n"
        "/all текст — рассылка всем\n"
        "/grant @user месяцы — выдать/продлить\n"
        "/import @user subId ГГГГ-ММ-ДД — добавить уже выданную вручную подписку"
    )


@router.message(Command("users"))
async def users(m: Message):
    if not is_admin(m):
        return
    rows = db.q("SELECT * FROM users ORDER BY id DESC LIMIT 30")
    if not rows:
        await m.answer("Пока никого.")
        return
    lines = [
        f"{'✅' if r['verified'] else '…'} @{r['username']} · {r['phone'] or '—'} · до {fmt_date(r['expires_at'])}"
        for r in rows
    ]
    await m.answer("\n".join(lines))


@router.message(Command("msg"))
async def msg(m: Message, command: CommandObject):
    if not is_admin(m):
        return
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) < 2:
        await m.answer("Формат: /msg @username текст")
        return
    u = find_user(parts[0])
    if not u or not u["tg_id"]:
        await m.answer("Пользователь не найден или не подтвердил Telegram.")
        return
    ok = await services.send(u["tg_id"], parts[1])
    await m.answer("Отправлено ✅" if ok else "Не удалось отправить (бот заблокирован?)")


@router.message(Command("all"))
async def broadcast(m: Message, command: CommandObject):
    if not is_admin(m) or not command.args:
        return
    sent = 0
    for u in db.q("SELECT tg_id FROM users WHERE verified=1 AND tg_id IS NOT NULL"):
        sent += await services.send(u["tg_id"], command.args)
    await m.answer(f"Доставлено: {sent}")


@router.message(Command("grant"))
async def grant(m: Message, command: CommandObject):
    if not is_admin(m):
        return
    parts = (command.args or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await m.answer("Формат: /grant @username месяцы")
        return
    u = find_user(parts[0])
    if not u:
        await m.answer("Пользователь не найден.")
        return
    exp = await services.activate(u["id"], int(parts[1]))
    await services.send(u["tg_id"], f"✅ Подписка активна до {fmt_date(exp)}.")
    await m.answer(f"Готово, до {fmt_date(exp)}")


@router.message(Command("import"))
async def import_user(m: Message, command: CommandObject):
    if not is_admin(m):
        return
    parts = (command.args or "").split()
    if len(parts) != 3:
        await m.answer("Формат: /import @username subId ГГГГ-ММ-ДД")
        return
    try:
        exp = int(time.mktime(time.strptime(parts[2], "%Y-%m-%d")))
    except ValueError:
        await m.answer("Дата в формате ГГГГ-ММ-ДД.")
        return
    name = parts[0].lstrip("@").lower()
    u = db.one("SELECT * FROM users WHERE username=?", (name,))
    if u:
        db.ex("UPDATE users SET sub_id=?, expires_at=? WHERE id=?", (parts[1], exp, u["id"]))
    else:
        db.ex(
            "INSERT INTO users(username, sub_id, expires_at, created) VALUES(?,?,?,?)",
            (name, parts[1], exp, db.now()),
        )
    await m.answer(f"Импортирован @{name}. Пусть зарегистрируется на сайте с этим же username.")


@router.callback_query(F.data.startswith("pay:"))
async def pay_decision(cb: CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        await cb.answer("Нет доступа", show_alert=True)
        return
    _, decision, oid = cb.data.split(":")
    o = db.one("SELECT * FROM orders WHERE id=?", (int(oid),))
    if not o or o["status"] not in ("review", "pending"):
        await cb.answer("Заказ уже обработан")
        return
    u = db.one("SELECT * FROM users WHERE id=?", (o["user_id"],))
    if decision == "ok":
        try:
            exp = await services.activate(u["id"], o["months"])
        except Exception as e:
            await cb.answer(f"Ошибка 3x-ui: {e}", show_alert=True)
            return
        db.ex("UPDATE orders SET status='paid' WHERE id=?", (o["id"],))
        await services.send(u["tg_id"], f"✅ Оплата получена. Подписка активна до {fmt_date(exp)}.")
        result = f"✅ Подтверждён, до {fmt_date(exp)}"
    else:
        db.ex("UPDATE orders SET status='rejected' WHERE id=?", (o["id"],))
        await services.send(u["tg_id"], f"Оплата заказа GOL-{o['id']} не найдена. Напишите нам, если это ошибка.")
        result = "❌ Отклонён"
    await cb.message.edit_text(f"{cb.message.text}\n\n{result}")
    await cb.answer()


def pay_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Оплачено", callback_data=f"pay:ok:{order_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"pay:no:{order_id}"),
        ]]
    )


# ---------- сообщения пользователей -> админам ----------

@router.message(F.text & ~F.text.startswith("/"))
async def forward_to_admins(m: Message):
    if is_admin(m):
        return
    u = db.one("SELECT * FROM users WHERE tg_id=?", (m.from_user.id,))
    who = f"@{u['username']}" if u else f"@{m.from_user.username or m.from_user.id}"
    await services.notify_admins(
        f"✉️ {who}:\n{html.escape(m.text)}\n\nОтветить: /msg {who} текст", parse_mode="HTML"
    )
    await m.answer("Передал администратору.")

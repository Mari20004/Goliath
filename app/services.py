"""Бизнес-логика: активация подписки, уведомления."""
import asyncio
import secrets
import string

from aiogram import Bot

from . import config, db
from .xui import xui

bot: Bot | None = Bot(config.BOT_TOKEN) if config.BOT_TOKEN else None

DAY = 86400


def sub_url(sub_id: str | None) -> str | None:
    return f"{config.SUB_BASE}/{sub_id}" if sub_id and config.SUB_BASE else None


def new_sub_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(16))


async def send(chat_id: int | None, text: str, **kw) -> bool:
    if not bot or not chat_id:
        return False
    try:
        await bot.send_message(chat_id, text, **kw)
        return True
    except Exception:
        return False


async def notify_admins(text: str, **kw) -> None:
    for admin in config.ADMIN_IDS:
        await send(admin, text, **kw)


async def activate(user_id: int, months: int) -> int:
    """Выдаёт/продлевает подписку на N месяцев, возвращает новый срок (unix)."""
    u = db.one("SELECT * FROM users WHERE id=?", (user_id,))
    days = 365 if months == 12 else months * 30
    base = max(db.now(), u["expires_at"])
    new_exp = base + days * DAY
    sub_id = u["sub_id"]

    if sub_id and await xui.set_expiry(sub_id, new_exp * 1000):
        pass
    else:
        sub_id = sub_id or new_sub_id()
        await xui.create(u["username"], sub_id, new_exp * 1000, u["tg_id"])

    db.ex(
        "UPDATE users SET sub_id=?, expires_at=?, notified='' WHERE id=?",
        (sub_id, new_exp, user_id),
    )
    return new_exp


async def expiry_watcher() -> None:
    """Раз в час напоминает об окончании подписки (за 3 дня, за 1 день, в день окончания)."""
    while True:
        try:
            now = db.now()
            for u in db.q("SELECT * FROM users WHERE verified=1 AND expires_at>0 AND tg_id IS NOT NULL"):
                left = u["expires_at"] - now
                stage = "expired" if left <= 0 else "1d" if left <= DAY else "3d" if left <= 3 * DAY else ""
                if not stage or stage == u["notified"]:
                    continue
                texts = {
                    "3d": "⏳ Ваша подписка Goliath заканчивается через 3 дня. Продлить можно на сайте.",
                    "1d": "⚠️ Подписка Goliath закончится менее чем через сутки.",
                    "expired": "⛔ Подписка Goliath закончилась. Продлите её на сайте, чтобы вернуть доступ.",
                }
                if await send(u["tg_id"], texts[stage]):
                    db.ex("UPDATE users SET notified=? WHERE id=?", (stage, u["id"]))
        except Exception:
            pass
        await asyncio.sleep(3600)

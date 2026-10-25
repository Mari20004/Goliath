import os


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


BOT_TOKEN = env("BOT_TOKEN")
BOT_USERNAME = env("BOT_USERNAME").lstrip("@")
ADMIN_IDS = {int(x) for x in env("ADMIN_IDS").replace(" ", "").split(",") if x}

SITE_URL = env("SITE_URL", "http://localhost:8000").rstrip("/")
DB_PATH = env("DB_PATH", "/data/goliath.db")

# 3x-ui: XUI_URL вместе с секретным путём панели, например https://host:2053/abcd
XUI_URL = env("XUI_URL").rstrip("/")
XUI_USER = env("XUI_USER")
XUI_PASS = env("XUI_PASS")
XUI_VERIFY_TLS = env("XUI_VERIFY_TLS", "true").lower() == "true"
XUI_INBOUND_IDS = [int(x) for x in env("XUI_INBOUND_IDS", "1").replace(" ", "").split(",") if x]
XUI_FLOW = env("XUI_FLOW", "xtls-rprx-vision")  # пусто, если inbound без flow
LIMIT_IP = int(env("LIMIT_IP", "3"))  # устройств на подписку, 0 = без лимита
TRAFFIC_GB = int(env("TRAFFIC_GB", "0"))  # 0 = безлимит

# База подписки: https://submainstem.mooo.com  -> ссылка = SUB_BASE/<subId>
SUB_BASE = env("SUB_BASE").rstrip("/")

# Тарифы: "месяцы:цена,месяцы:цена"
PRICES = {}
for part in env("PRICES", "1:199,3:549,12:1990").split(","):
    m, p = part.split(":")
    PRICES[int(m)] = int(p)

PAY_DETAILS = env("PAY_DETAILS", "СБП: +7 000 000-00-00 (банк — укажите в .env)")

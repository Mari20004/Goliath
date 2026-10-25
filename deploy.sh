#!/usr/bin/env bash
# Goliath VPN — установка одной командой (Ubuntu / Debian).
# Запуск:  bash deploy.sh
set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!  %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null || die "запустите от root или установите sudo"
  SUDO="sudo"
fi

# ---------- 1. Docker ----------
if ! command -v docker >/dev/null 2>&1; then
  say "Устанавливаю Docker"
  command -v curl >/dev/null || { $SUDO apt-get update -y && $SUDO apt-get install -y curl ca-certificates; }
  curl -fsSL https://get.docker.com | $SUDO sh
fi
$SUDO docker compose version >/dev/null 2>&1 || die "не найден docker compose (плагин). Установите docker-compose-plugin."
DC="$SUDO docker compose"

# ---------- 2. Настройки ----------
ask() { # ask VAR "Вопрос" "по умолчанию" [secret]
  local var="$1" prompt="$2" def="${3:-}" secret="${4:-}" val=""
  while true; do
    if [ -n "$secret" ]; then
      read -r -s -p "$prompt: " val; echo
    else
      read -r -p "$prompt${def:+ [$def]}: " val
    fi
    val="${val:-$def}"
    [ -z "$val" ] && { warn "Значение обязательно"; continue; }
    case "$val" in *"'"*) warn "Символ ' не поддерживается, уберите его"; continue;; esac
    printf -v "$var" '%s' "$val"
    return
  done
}

REUSE=""
if [ -f .env ]; then
  read -r -p "Файл .env уже есть. Использовать его без вопросов? [Y/n]: " REUSE
  REUSE="${REUSE:-Y}"
fi

if [[ "${REUSE}" =~ ^[Yy]$ ]]; then
  say "Использую существующий .env"
  set -a; . ./.env; set +a
else
  say "Настройка. Ответы запишутся в .env"

  echo "Домен сайта должен уже указывать (A-запись) на IP этого сервера."
  ask DOMAIN "Домен сайта (например goliath.example.com)"

  echo; echo "Telegram: создайте бота у @BotFather и скопируйте токен."
  while true; do
    ask BOT_TOKEN "Токен бота" "" secret
    RESP="$(curl -sS -m 15 "https://api.telegram.org/bot${BOT_TOKEN}/getMe" || true)"
    if printf '%s' "$RESP" | grep -q '"ok":true'; then
      BOT_USERNAME="$(printf '%s' "$RESP" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')"
      echo "Бот найден: @${BOT_USERNAME}"; break
    fi
    warn "Токен не принят Telegram, попробуйте ещё раз"
  done
  echo "Ваш числовой Telegram id можно узнать у бота @userinfobot."
  ask ADMIN_IDS "Ваш Telegram id (несколько — через запятую)"

  echo; echo "3x-ui: адрес панели вместе с секретным путём, например https://1.2.3.4:2053/abcd"
  ask XUI_URL "Адрес панели 3x-ui"
  XUI_URL="${XUI_URL%/}"
  ask XUI_USER "Логин панели"
  ask XUI_PASS "Пароль панели" "" secret
  XUI_VERIFY_TLS="true"
  case "$XUI_URL" in https://*)
    read -r -p "У панели самоподписанный сертификат? [y/N]: " SS
    [[ "${SS:-N}" =~ ^[Yy]$ ]] && XUI_VERIFY_TLS="false";;
  esac

  CURL_TLS=""; [ "$XUI_VERIFY_TLS" = "false" ] && CURL_TLS="-k"
  JAR="$(mktemp)"
  say "Проверяю вход в 3x-ui"
  LOGIN="$(curl -sS $CURL_TLS -m 20 -c "$JAR" \
    --data-urlencode "username=${XUI_USER}" --data-urlencode "password=${XUI_PASS}" \
    "${XUI_URL}/login" || true)"
  if printf '%s' "$LOGIN" | grep -q '"success":true'; then
    echo "Вход в панель успешен."
    if command -v python3 >/dev/null; then
      echo "Найденные inbound'ы (id — название — протокол — порт):"
      curl -sS $CURL_TLS -m 20 -b "$JAR" "${XUI_URL}/panel/api/inbounds/list" | python3 -c '
import sys, json
try:
    for i in json.load(sys.stdin)["obj"]:
        print("  ", i["id"], "—", i.get("remark") or "без названия", "—", i["protocol"], "—", i["port"])
except Exception:
    print("   (не удалось получить список)")'
    fi
  else
    warn "Не удалось войти в 3x-ui (проверьте адрес, секретный путь, логин и пароль)."
    read -r -p "Продолжить всё равно? [y/N]: " GO
    [[ "${GO:-N}" =~ ^[Yy]$ ]] || { rm -f "$JAR"; exit 1; }
  fi
  rm -f "$JAR"

  ask XUI_INBOUND_IDS "id inbound'ов для клиентов (через запятую)" "1"
  ask XUI_FLOW_IN "Flow (xtls-rprx-vision для VLESS Reality, '-' если не нужен)" "xtls-rprx-vision"
  XUI_FLOW="$XUI_FLOW_IN"; [ "$XUI_FLOW" = "-" ] && XUI_FLOW=""
  ask LIMIT_IP "Устройств на подписку (0 — без лимита)" "3"
  ask TRAFFIC_GB "Лимит трафика в ГБ (0 — безлимит)" "0"
  ask SUB_BASE "База ссылки-подписки" "https://submainstem.mooo.com"
  SUB_BASE="${SUB_BASE%/}"

  echo; echo "Тарифы и оплата"
  ask PRICES "Цены (месяцы:рубли через запятую)" "1:199,3:549,12:1990"
  ask PAY_DETAILS "Реквизиты для СБП (текст, который увидит клиент)" "СБП: +7 900 000-00-00, Иван И., Т-Банк"

  umask 077
  cat > .env <<EOF
DOMAIN='${DOMAIN}'
SITE_URL='https://${DOMAIN}'
BOT_TOKEN='${BOT_TOKEN}'
BOT_USERNAME='${BOT_USERNAME}'
ADMIN_IDS='${ADMIN_IDS}'
XUI_URL='${XUI_URL}'
XUI_USER='${XUI_USER}'
XUI_PASS='${XUI_PASS}'
XUI_VERIFY_TLS='${XUI_VERIFY_TLS}'
XUI_INBOUND_IDS='${XUI_INBOUND_IDS}'
XUI_FLOW='${XUI_FLOW}'
LIMIT_IP='${LIMIT_IP}'
TRAFFIC_GB='${TRAFFIC_GB}'
SUB_BASE='${SUB_BASE}'
PRICES='${PRICES}'
PAY_DETAILS='${PAY_DETAILS}'
EOF
  chmod 600 .env
  say ".env сохранён"
fi

# ---------- 3. Проверки сети ----------
PUBLIC_IP="$(curl -4 -sS -m 8 https://ifconfig.me || true)"
DOMAIN_IP="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1; exit}' || true)"
if [ -n "$PUBLIC_IP" ] && [ -n "$DOMAIN_IP" ] && [ "$PUBLIC_IP" != "$DOMAIN_IP" ]; then
  warn "Домен $DOMAIN указывает на $DOMAIN_IP, а IP сервера — $PUBLIC_IP. HTTPS не выпустится, пока A-запись не исправлена."
elif [ -z "$DOMAIN_IP" ]; then
  warn "Домен $DOMAIN пока не резолвится. Добавьте A-запись на $PUBLIC_IP."
fi

for p in 80 443; do
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$p$"; then
    warn "Порт $p уже занят другим сервисом — Caddy может не запуститься. Освободите его или уберите сервис caddy из docker-compose.yml."
  fi
done
if command -v ufw >/dev/null && $SUDO ufw status 2>/dev/null | grep -q "Status: active"; then
  say "Открываю порты 80 и 443 в ufw"
  $SUDO ufw allow 80/tcp >/dev/null; $SUDO ufw allow 443/tcp >/dev/null
fi

# ---------- 4. Запуск ----------
say "Собираю и запускаю контейнеры"
mkdir -p data
$DC up -d --build

say "Жду, пока приложение поднимется"
OK=""
for _ in $(seq 1 30); do
  if $DC exec -T app python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/plans').status==200 else 1)" >/dev/null 2>&1; then
    OK=1; break
  fi
  sleep 2
done
if [ -z "$OK" ]; then
  $DC logs --tail 40 app || true
  die "приложение не запустилось, лог выше. Пришлите его мне."
fi

say "Готово!"
cat <<EOF
  Сайт:          https://${DOMAIN}   (сертификат Caddy выпустит за 1–2 минуты)
  Бот:           откройте @${BOT_USERNAME:-ваш_бот} и отправьте /admin
  Логи:          sudo docker compose logs -f app
  Обновление:    замените файлы и снова выполните  bash deploy.sh  (ответьте Y на «использовать .env»)
  Бэкап:         папка ./data (там вся база)

Первые шаги:
  1. Откройте сайт и зарегистрируйтесь со своим аккаунтом — проверьте цепочку «сайт → бот → кабинет».
  2. Выдайте себе подписку командой /grant @ваш_username 1 и убедитесь, что ссылка работает в клиенте.
  3. Существующих клиентов переносите командой /import @username subId ГГГГ-ММ-ДД.
EOF

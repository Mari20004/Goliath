const $ = (s) => document.querySelector(s);
const MONTH_WORD = (m) => (m === 1 ? "месяц" : m < 5 ? "месяца" : "месяцев");
let me = null;
let pollTimer = null;
let plans = [];

async function api(path, opts = {}) {
  const r = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  let data = null;
  try { data = await r.json(); } catch (_) {}
  if (!r.ok) throw Object.assign(new Error((data && data.detail) || "Ошибка"), { status: r.status });
  return data;
}

const fmtDate = (ts) => (ts ? new Date(ts * 1000).toLocaleDateString("ru-RU") : "—");
const STATUS = { pending: "ожидает оплаты", review: "на проверке", paid: "оплачен", rejected: "отклонён" };

function openDlg(sel) { $(sel).showModal(); }
document.addEventListener("click", (e) => {
  if (e.target.matches("[data-close]")) {
    const d = e.target.closest("dialog");
    if (d) { d.close(); stopPoll(); }
  }
  if (e.target.matches("[data-open-auth]")) openAuth();
});

/* ---------- тарифы ---------- */
async function loadPlans() {
  plans = await api("/api/plans");
  const base = plans[0].price / plans[0].months;
  const list = $("#planList");
  list.innerHTML = "";
  plans.forEach((p, i) => {
    const card = document.createElement("div");
    card.className = "plan" + (p.months === 12 ? " best" : "");
    const perMonth = Math.round(p.price / p.months);
    const save = Math.round((1 - perMonth / base) * 100);

    const tag = document.createElement("div");
    tag.className = "tag";
    tag.textContent = p.months === 12 ? "Выгоднее всего" : "";
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = `${p.months} ${MONTH_WORD(p.months)}`;
    const price = document.createElement("div");
    price.className = "price";
    price.textContent = p.price + " ";
    const cur = document.createElement("small");
    cur.textContent = "₽";
    price.appendChild(cur);
    const per = document.createElement("div");
    per.className = "per";
    per.textContent = p.months > 1 ? `${perMonth} ₽/мес` + (save > 0 ? ` · −${save}%` : "") : "Без обязательств";
    const btn = document.createElement("button");
    btn.className = "btn" + (p.months === 12 ? "" : " ghost");
    btn.textContent = "Купить";
    btn.onclick = () => buy(p.months);

    card.append(tag, name, price, per, btn);
    list.appendChild(card);
  });
}

async function buy(months) {
  if (!me) { openAuth(); return; }
  try {
    const o = await api("/api/orders", { method: "POST", body: JSON.stringify({ months }) });
    $("#payId").textContent = o.comment;
    $("#payAmount").textContent = o.amount;
    $("#payDetails").textContent = o.details;
    $("#payComment").textContent = o.comment;
    $("#payDone").hidden = true;
    $("#paidBtn").hidden = false;
    $("#paidBtn").onclick = async () => {
      await api(`/api/orders/${o.id}/paid`, { method: "POST" });
      $("#payDone").hidden = false;
      $("#paidBtn").hidden = true;
      refreshMe();
    };
    openDlg("#payDlg");
  } catch (e) { alert(e.message); }
}

/* ---------- авторизация ---------- */
function openAuth() {
  $("#authForm").hidden = false;
  $("#authWait").hidden = true;
  $("#authErr").hidden = true;
  openDlg("#authDlg");
}
function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

$("#authBtn").onclick = () => (me ? $("#account").scrollIntoView() : openAuth());

$("#authForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("#authErr");
  err.hidden = true;
  $("#authSubmit").disabled = true;
  try {
    const r = await api("/api/auth/start", {
      method: "POST",
      body: JSON.stringify({ username: $("#fUser").value, phone: $("#fPhone").value }),
    });
    $("#botLink").href = r.link;
    $("#authHint").textContent = r.mode === "login"
      ? "Откройте бота и нажмите Start — вход подтвердится автоматически."
      : "Откройте бота, нажмите Start и поделитесь номером телефона для подтверждения.";
    $("#authForm").hidden = true;
    $("#authWait").hidden = false;
    window.open(r.link, "_blank", "noopener");
    stopPoll();
    pollTimer = setInterval(async () => {
      try {
        const s = await api(`/api/auth/poll?token=${encodeURIComponent(r.token)}`);
        if (s.status === "ok") { stopPoll(); $("#authDlg").close(); await refreshMe(); }
        if (s.status === "expired") { stopPoll(); openAuth(); }
      } catch (_) {}
    }, 2000);
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  } finally { $("#authSubmit").disabled = false; }
});

$("#logoutBtn").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); me = null; render(); };

/* ---------- кабинет ---------- */
async function refreshMe() {
  try { me = await api("/api/me"); } catch (_) { me = null; }
  render();
}

function render() {
  $("#account").hidden = !me;
  $("#authBtn").textContent = me ? "Кабинет" : "Войти";
  if (!me) return;
  $("#accUser").textContent = "@" + me.username;
  $("#accStatus").textContent = me.active ? "активна" : "не активна";
  $("#accStatus").style.color = me.active ? "var(--accent)" : "var(--danger)";
  $("#accExp").textContent = fmtDate(me.expires_at);
  $("#subBox").hidden = !me.sub_url;
  if (me.sub_url) $("#subUrl").value = me.sub_url;
  $("#ordersBox").hidden = !me.orders.length;
  const ul = $("#orders");
  ul.innerHTML = "";
  me.orders.forEach((o) => {
    const li = document.createElement("li");
    const a = document.createElement("span");
    a.textContent = `GOL-${o.id} · ${o.months} ${MONTH_WORD(o.months)} · ${o.amount} ₽`;
    const b = document.createElement("span");
    b.textContent = STATUS[o.status] || o.status;
    li.append(a, b);
    ul.appendChild(li);
  });
}

$("#copyBtn").onclick = async () => {
  try { await navigator.clipboard.writeText($("#subUrl").value); } catch (_) { $("#subUrl").select(); document.execCommand("copy"); }
  $("#copyBtn").textContent = "Скопировано";
  setTimeout(() => ($("#copyBtn").textContent = "Копировать"), 1500);
};

loadPlans();
refreshMe();

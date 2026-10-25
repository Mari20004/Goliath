"""Минимальный клиент API 3x-ui (классический /panel/api/inbounds/*).

Подписка на сайте = клиенты с одним и тем же subId во всех inbound'ах из XUI_INBOUND_IDS.
Продление находит клиентов по subId, поэтому работает и для тех, кого вы выдали вручную.
"""
import json
import uuid

import httpx

from . import config


class XUI:
    def __init__(self) -> None:
        self.http = httpx.AsyncClient(
            base_url=config.XUI_URL, verify=config.XUI_VERIFY_TLS, timeout=20
        )
        self.logged_in = False

    async def _login(self) -> None:
        r = await self.http.post(
            "/login", data={"username": config.XUI_USER, "password": config.XUI_PASS}
        )
        if r.status_code != 200 or not r.json().get("success"):
            raise RuntimeError("3x-ui: не удалось войти (проверьте XUI_URL/XUI_USER/XUI_PASS)")
        self.logged_in = True

    async def _req(self, method: str, path: str, **kw) -> dict:
        for attempt in (1, 2):
            if not self.logged_in:
                await self._login()
            r = await self.http.request(method, path, **kw)
            # без сессии 3x-ui отвечает 404
            if r.status_code == 404 and attempt == 1:
                self.logged_in = False
                continue
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                raise RuntimeError(f"3x-ui: {data.get('msg')}")
            return data
        raise RuntimeError("3x-ui: недоступен")

    async def inbounds(self) -> list[dict]:
        return (await self._req("GET", "/panel/api/inbounds/list"))["obj"]

    async def find_by_sub(self, sub_id: str) -> list[tuple[int, dict]]:
        found = []
        for ib in await self.inbounds():
            for c in json.loads(ib["settings"]).get("clients", []):
                if c.get("subId") == sub_id:
                    found.append((ib["id"], c))
        return found

    async def create(self, username: str, sub_id: str, expiry_ms: int, tg_id: int | None) -> None:
        for ib_id in config.XUI_INBOUND_IDS:
            client = {
                "id": str(uuid.uuid4()),
                "email": f"{username}_{ib_id}",
                "flow": config.XUI_FLOW,
                "limitIp": config.LIMIT_IP,
                "totalGB": config.TRAFFIC_GB * 1024**3,
                "expiryTime": expiry_ms,
                "enable": True,
                "tgId": str(tg_id or ""),
                "subId": sub_id,
                "comment": "goliath-site",
                "reset": 0,
            }
            await self._req(
                "POST",
                "/panel/api/inbounds/addClient",
                data={"id": ib_id, "settings": json.dumps({"clients": [client]})},
            )

    async def set_expiry(self, sub_id: str, expiry_ms: int) -> int:
        """Ставит новый срок всем клиентам с этим subId и включает их. Возвращает число клиентов."""
        clients = await self.find_by_sub(sub_id)
        for ib_id, c in clients:
            c["expiryTime"] = expiry_ms
            c["enable"] = True
            cid = c.get("id") or c.get("password") or c.get("email")
            await self._req(
                "POST",
                f"/panel/api/inbounds/updateClient/{cid}",
                data={"id": ib_id, "settings": json.dumps({"clients": [c]})},
            )
        return len(clients)


xui = XUI()

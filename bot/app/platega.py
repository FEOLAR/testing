"""Platega (app.platega.io): приём оплаты картами и СБП.

- Счёт: POST /transaction/process (конкретный способ, PLATEGA_METHOD: 2 — СБП, 10/11 — карты)
  или POST /v2/transaction/process (PLATEGA_METHOD=0 — клиент сам выбирает способ на странице Platega).
- Авторизация — заголовки X-MerchantId и X-Secret.
- Об оплате Platega сообщает POST-запросом на callback-адрес из личного кабинета, с теми же заголовками
  X-MerchantId / X-Secret (подписи тела нет — сверяем секрет). На всякий случай бот ещё и сам опрашивает
  статус неоплаченных счетов (GET /transaction/{id}), так что оплата пройдёт и без callback.
"""
from __future__ import annotations

import hmac

import httpx

from .config import settings

PAID = {"CONFIRMED"}
FAILED = {"CANCELED", "EXPIRED", "FAILED"}


class PlategaError(Exception):
    pass


class Platega:
    def __init__(self) -> None:
        self.http = httpx.AsyncClient(
            base_url=settings.platega_url.rstrip("/"),
            timeout=25,
            headers={"X-MerchantId": settings.platega_merchant_id, "X-Secret": settings.platega_secret,
                     "Content-Type": "application/json"},
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _req(self, method: str, url: str, **kw) -> dict:
        r = await self.http.request(method, url, **kw)
        if r.status_code >= 400:
            raise PlategaError(f"{method} {url} -> {r.status_code}: {r.text[:400]}")
        try:
            return r.json()
        except ValueError as err:
            raise PlategaError(f"{method} {url}: не JSON: {r.text[:200]}") from err

    async def create(self, rub: int, description: str, payload: str, user_id: int, return_url: str) -> dict:
        """Создаёт счёт. Возвращает {"id": transactionId, "url": ссылка на оплату}."""
        body = {
            "paymentDetails": {"amount": rub, "currency": "RUB"},
            "description": description[:250],
            "return": return_url,
            "failedUrl": return_url,
            "payload": payload,
            "metadata": {"userId": str(user_id)},
        }
        if settings.platega_method:
            body["paymentMethod"] = settings.platega_method
            data = await self._req("POST", "/transaction/process", json=body)
            url = data.get("redirect") or data.get("url")
        else:
            data = await self._req("POST", "/v2/transaction/process", json=body)
            url = data.get("url") or data.get("redirect")
        tid = data.get("transactionId") or data.get("id")
        if not tid or not url:
            raise PlategaError(f"неожиданный ответ: {str(data)[:300]}")
        return {"id": str(tid), "url": url}

    async def status(self, transaction_id: str) -> str:
        """PENDING | CONFIRMED | CANCELED | EXPIRED | FAILED | CHARGEBACKED"""
        data = await self._req("GET", f"/transaction/{transaction_id}")
        return str(data.get("status") or "").upper()


def callback_authentic(headers) -> bool:
    """Callback настоящий, если в заголовках наши X-MerchantId и X-Secret (сравнение за постоянное время)."""
    low = {str(k).lower(): str(v) for k, v in headers.items()}
    merchant = low.get("x-merchantid") or low.get("x-merchant-id") or ""
    secret = low.get("x-secret") or ""
    ok_m = hmac.compare_digest(merchant, settings.platega_merchant_id)
    ok_s = hmac.compare_digest(secret, settings.platega_secret)
    return bool(settings.platega_secret) and ok_m and ok_s


platega = Platega()

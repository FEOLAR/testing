"""Crypto Pay API (@CryptoBot). Оплаты проверяются опросом — вебхук и открытый порт не нужны."""
from __future__ import annotations

import httpx

from .config import settings


class CryptoPayError(Exception):
    pass


class CryptoPay:
    def __init__(self) -> None:
        host = "testnet-pay.crypt.bot" if settings.cryptopay_testnet else "pay.crypt.bot"
        self.http = httpx.AsyncClient(
            base_url=f"https://{host}/api",
            timeout=20,
            headers={"Crypto-Pay-API-Token": settings.cryptopay_token},
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _call(self, method: str, **params) -> dict | list:
        r = await self.http.post(f"/{method}", json=params)
        data = r.json()
        if not data.get("ok"):
            raise CryptoPayError(f"{method}: {data.get('error')}")
        return data["result"]

    async def create_invoice(self, rub: int, description: str, payload: str) -> dict:
        """Счёт в рублях, клиент платит любой из разрешённых монет по курсу CryptoBot."""
        return await self._call(
            "createInvoice",
            currency_type="fiat",
            fiat="RUB",
            amount=str(rub),
            accepted_assets=settings.cryptopay_assets,
            description=description[:1024],
            payload=payload,
            expires_in=3600,
            allow_comments=False,
            allow_anonymous=True,
        )

    async def get_invoices(self, invoice_ids: list[str]) -> list[dict]:
        if not invoice_ids:
            return []
        res = await self._call("getInvoices", invoice_ids=",".join(invoice_ids), count=1000)
        return res.get("items", []) if isinstance(res, dict) else res


crypto = CryptoPay()

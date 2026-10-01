from dataclasses import dataclass
from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class Plan:
    code: str
    days: int
    rub: int
    stars: int

    @property
    def title(self) -> str:
        names = {30: "1 месяц", 90: "3 месяца", 180: "6 месяцев", 365: "12 месяцев"}
        return names.get(self.days, f"{self.days} дн.")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    admin_ids: str = ""
    support_username: str = ""
    brand_name: str = "VPN"
    miniapp_url: str = ""
    webapp_port: int = 8080

    panel_url: str = "http://remnawave:3000"
    panel_token: str
    panel_squad_uuids: str = ""
    device_limit: int = 3
    traffic_limit_gb: int = 0

    plans: str = "30:199:150,90:549:400,180:999:750,365:1790:1350"
    trial_days: int = 3
    referral_bonus_days: int = 7

    cryptopay_token: str = ""
    cryptopay_testnet: bool = False
    cryptopay_assets: str = "USDT,TON"

    database_url: str
    redis_url: str = ""

    @cached_property
    def admins(self) -> set[int]:
        return {int(x) for x in self.admin_ids.replace(" ", "").split(",") if x}

    @cached_property
    def squads(self) -> list[str]:
        return [x.strip() for x in self.panel_squad_uuids.split(",") if x.strip()]

    @cached_property
    def plan_list(self) -> list[Plan]:
        out = []
        for chunk in self.plans.split(","):
            days, rub, stars = (int(v) for v in chunk.strip().split(":"))
            out.append(Plan(code=f"d{days}", days=days, rub=rub, stars=stars))
        return out

    def plan(self, code: str) -> Plan | None:
        return next((p for p in self.plan_list if p.code == code), None)

    @property
    def crypto_enabled(self) -> bool:
        return bool(self.cryptopay_token)


settings = Settings()

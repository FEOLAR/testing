"""Тестовый профиль Happ с блокировкой рекламы и трекеров = профиль v3 (happ-routing.json) + BlockSites.

python3 infra/mk-adblock.py  →  infra/happ-routing-adblock.json и .txt (ссылка happ://routing/onadd/...).
Профиль называется иначе, чем основной, поэтому не затирает «WhiteHoleVPN» и легко откатывается.
Сборка ссылки — как в happ-routing.txt: компактный JSON (ensure_ascii=False) → base64.
"""
import base64
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "WhiteHole AdBlock test"

# Только реклама и счётчики, без которых приложения работают.
# НЕ блокируем: startup.mobile.yandex.net (запуск SDK Яндекса — без него приложения Яндекса глючат),
# redirect.appmetrica.yandex.com (переходы по ссылкам), strm.yandex.ru (видео Кинопоиска/Дзена),
# imasdk.googleapis.com, любые youtube.com / googlevideo.com / ytimg.com.
BLOCK = [
    # Яндекс: рекламная сеть, баннеры, AdFox, Метрика, телеметрия AppMetrica, рекламный SDK
    "full:an.yandex.ru",
    "full:yabs.yandex.ru",
    "domain:adfox.ru",
    "full:adfox.yandex.ru",
    "full:mc.yandex.ru",
    "full:mc.yandex.com",
    "full:report.appmetrica.yandex.net",
    "full:mobile.yandexadexchange.net",
    "full:adsdk.yandex.ru",
    # VK / Mail.ru: реклама myTarget и счётчик top.mail.ru
    "full:ad.mail.ru",
    "full:top-fwz1.mail.ru",
    # Google: реклама на сайтах и в приложениях, Firebase/Google Analytics в приложениях
    "domain:doubleclick.net",
    "domain:googleadservices.com",
    "domain:googlesyndication.com",
    "domain:googletagservices.com",
    "full:adservice.google.com",
    "domain:app-measurement.com",
]


def main() -> None:
    profile = json.loads((HERE / "happ-routing.json").read_text(encoding="utf-8"))
    assert profile.get("RouteOrder") == "block-proxy-direct", "блок должен проверяться первым"
    profile["Name"] = NAME
    profile["BlockSites"] = BLOCK
    for d in BLOCK:  # не задеть YouTube
        assert "youtube" not in d and "googlevideo" not in d and "ytimg" not in d, d
    (HERE / "happ-routing-adblock.json").write_text(json.dumps(profile, ensure_ascii=False, indent=1) + "\n",
                                                   encoding="utf-8")
    raw = json.dumps(profile, ensure_ascii=False, separators=(",", ":")).encode()
    link = "happ://routing/onadd/" + base64.b64encode(raw).decode()
    (HERE / "happ-routing-adblock.txt").write_text(link + "\n", encoding="utf-8")
    # ссылка «вернуть основной профиль и включить его»
    main_raw = json.dumps(json.loads((HERE / "happ-routing.json").read_text(encoding="utf-8")),
                          ensure_ascii=False, separators=(",", ":")).encode()
    (HERE / "happ-routing-onadd.txt").write_text(
        "happ://routing/onadd/" + base64.b64encode(main_raw).decode() + "\n", encoding="utf-8")
    # копии для бота: страницы /miniapp/routing/adblock и /miniapp/routing/main открывают ссылку в Happ
    web = HERE.parent / "bot" / "app" / "web" / "routing"
    web.mkdir(parents=True, exist_ok=True)
    (web / "adblock.txt").write_text(link + "\n", encoding="utf-8")
    (web / "main.txt").write_text((HERE / "happ-routing-onadd.txt").read_text(encoding="utf-8"), encoding="utf-8")
    print(len(link), "символов в ссылке")


if __name__ == "__main__":
    main()

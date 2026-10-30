"""Профили платформ Android TV: как определить, какой домашний экран у ТВ,
что можно безопасно отключить и что нельзя трогать никогда.

Уровни уверенности (confidence):
  verified  — проверено владельцем на реальном ТВ (Tuvio, Яндекс ТВ, Android 11).
              Только такие пакеты отключаются «по умолчанию».
  reported  — многократно описано в открытых источниках как безопасное для
              `pm disable-user --user 0` и обратимое через `pm enable`.
              Показываются галочками, ВЫКЛЮЧЕННЫМИ по умолчанию.
  home      — родной домашний экран. Отключается только по явной галочке,
              если после установки он всё равно перехватывает «Домой».

Источники (исследование, на реальных ТВ этих марок не проверено):
  [freya]   https://freya.cat/blog/post/2025-03-11 — Google TV: launcherx + setupwraith
  [cobanov] https://tv.cobanov.dev/en/prompt.txt — списки «не трогать» (Google, TCL),
            launcherx / tvlauncher / setupwraith — только после смены лаунчера
  [habr]    https://habr.com/ru/articles/1044486/ — Xiaomi PatchWall: com.mitv.tvhome.atv,
            .mitvplus, .michannel, com.xiaomi.mitv.updateservice, tvrecommendations
  [bhupixb] https://bhupixb.github.io/blog/11-minimal-mitv-launcher/ — Mi TV:
            tvrecommendations, leanbacklauncher.recommendations, tvlauncher, откат через pm enable
  [piunika] https://piunikaweb.com/2021/06/28/how-to-remove-new-ads-from-nvidia-shield-other-android-tv-devices/
            — com.google.android.leanbacklauncher.recommendations
  [sber]    https://developers.sber.ru/docs/ru/salute-tv/vendor-sdk/launching-the-app — пакеты
            ru.sberdevices.* на устройствах Салют ТВ (списка рекламных пакетов нет → ничего не отключаем)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

LAUNCHER_PKG = "space.whitehole.tv"


@dataclass(frozen=True)
class Pkg:
    name: str
    desc: str
    confidence: str          # verified / reported / home
    source: str = ""
    warning: str = ""


@dataclass(frozen=True)
class Profile:
    id: str
    title: str
    detect_packages: tuple = ()          # точные имена
    detect_prefixes: tuple = ()          # префиксы имён пакетов
    home_packages: tuple = ()            # родные домашние экраны
    default_disable: tuple = ()          # Pkg, confidence=verified — отключаются по кнопке
    extra: tuple = ()                    # Pkg — галочки, выключены по умолчанию
    never: tuple = ()                    # доп. пакеты/фрагменты, которые нельзя трогать
    home_warning: str = ""               # предупреждение при отключении родного экрана


# Никогда не трогаем ни на одной платформе (подстроки имени пакета).
GLOBAL_NEVER = (
    "com.google.android.gms", "com.google.android.gsf", "com.android.vending",
    "com.google.android.katniss",          # голосовой поиск / микрофон пульта [habr]
    "inputmethod",                          # клавиатуры [freya][cobanov]
    "com.android.location.fused",           # bootloop [cobanov]
    "com.google.android.tv.remote.service",  # пульт [cobanov]
    "settings", "setupwizard", "systemui", "packageinstaller", "webview",
    "tvinput", "tvprovider", "bluetooth", "permissioncontroller",
    "com.yandex.tv.services", "alice",      # сервисы Яндекс ТВ и Алиса
    "ru.sberdevices.services",              # сервисы Салют ТВ
    LAUNCHER_PKG, "su.happ.proxyutility",
)

YANDEX = Profile(
    id="yandex",
    title="Яндекс ТВ",
    detect_packages=("com.yandex.tv.home",),
    home_packages=("com.yandex.tv.home",),
    default_disable=(
        Pkg("com.yandex.tv.home", "Домашний экран Яндекс ТВ с рекламой", "verified", "владелец, Tuvio TD75UFBHH13"),
        Pkg("com.yandex.launcher.updaterapp", "Автообновление домашнего экрана Яндекса", "verified",
            "владелец, Tuvio TD75UFBHH13"),
        Pkg("com.yandex.android.advid", "Рекламный идентификатор Яндекса", "verified", "владелец, Tuvio TD75UFBHH13"),
    ),
)

SBER = Profile(
    id="sber",
    title="Салют ТВ (Сбер)",
    detect_prefixes=("ru.sberdevices.",),
    # Пакет родного лаунчера Салют ТВ публично не задокументирован — определяем
    # домашний экран на самом ТВ (resolve-activity), список отключения пустой. [sber]
)

PATCHWALL = Profile(
    id="patchwall",
    title="Xiaomi PatchWall",
    detect_prefixes=("com.mitv.tvhome",),
    home_packages=("com.mitv.tvhome.atv", "com.mitv.tvhome"),
    extra=(
        Pkg("com.mitv.tvhome.mitvplus", "Канал рекомендаций Xiaomi (Mi TV+)", "reported", "habr"),
        Pkg("com.mitv.tvhome.michannel", "Канал рекомендаций Xiaomi", "reported", "habr"),
        Pkg("com.xiaomi.mitv.updateservice", "Служба обновлений Xiaomi (будит ТВ ночью). "
            "Обновления прошивки перестанут приходить, пока не вернёшь", "reported", "habr"),
        Pkg("com.google.android.tvrecommendations", "Рекламные рекомендации Google на главном экране",
            "reported", "habr, bhupixb"),
    ),
    never=("com.mitv.livetv", "com.droidlogic.tvinput", "com.droidlogic.droidlivetv"),
    home_warning="Кнопка PatchWall на пульте перестанет работать, пока не вернёшь как было.",
)

GOOGLE_TV = Profile(
    id="googletv",
    title="Google TV",
    detect_packages=("com.google.android.apps.tv.launcherx",),
    home_packages=("com.google.android.apps.tv.launcherx",),
    extra=(
        Pkg("com.google.android.tungsten.setupwraith", "Служба, которая возвращает домашний экран Google TV "
            "после перезагрузки. Отключать только вместе с домашним экраном Google TV", "reported",
            "freya, cobanov",
            "Отключай, только если после перезагрузки снова появляется Google TV."),
    ),
    home_warning="Вместе с домашним экраном Google TV пропадут его функции: рекомендации, профили, "
                 "«Продолжить просмотр», а на телевизорах иногда — переключение входов HDMI с главного "
                 "экрана. Всё возвращается кнопкой «Вернуть как было».",
)

ANDROID_TV = Profile(
    id="androidtv",
    title="Android TV",
    detect_packages=("com.google.android.tvlauncher", "com.google.android.leanbacklauncher"),
    home_packages=("com.google.android.tvlauncher", "com.google.android.leanbacklauncher"),
    extra=(
        Pkg("com.google.android.tvrecommendations", "Рекламные рекомендации Google на главном экране",
            "reported", "habr, bhupixb"),
        Pkg("com.google.android.leanbacklauncher.recommendations", "Рекомендации старого домашнего экрана "
            "Android TV", "reported", "piunika, bhupixb"),
    ),
    home_warning="Пропадут рекомендации и каналы родного домашнего экрана Android TV. "
                 "Всё возвращается кнопкой «Вернуть как было».",
)

BOX = Profile(
    id="box",
    title="Android-приставка",
    detect_packages=("com.android.launcher3", "com.android.launcher", "com.droidlogic.mboxlauncher",
                     "com.amlogic.mboxlauncher", "com.android.tv.launcher"),
    detect_prefixes=("com.droidlogic.", "com.amlogic."),
    home_packages=("com.droidlogic.mboxlauncher", "com.amlogic.mboxlauncher", "com.android.launcher3",
                   "com.android.launcher", "com.android.tv.launcher"),
    home_warning="Родной экран приставки перестанет открываться, пока не вернёшь как было.",
)

GENERIC = Profile(id="generic", title="Android")

# Порядок важен: сначала самые специфичные оболочки.
PROFILES = (YANDEX, SBER, PATCHWALL, GOOGLE_TV, ANDROID_TV, BOX)
ALL_PROFILES = PROFILES + (GENERIC,)

# Марки: только дополнительные «не трогать» и название для экрана.
BRAND_NEVER = {
    # [cobanov]: входы, обновления, Wi-Fi, пульт
    "tcl": ("com.tcl.suspension", "com.tcl.ttvs", "com.tcl.tv", "com.tcl.tvinput", "com.tcl.providers.config",
            "com.tcl.initsetup", "com.tcl.tcl_bt_rcu_service", "com.tcl.autopair"),
}
BRAND_NAMES = {
    "tcl": "TCL", "haier": "Haier", "philips": "Philips", "tpvision": "Philips", "sony": "Sony",
    "hisense": "Hisense", "xiaomi": "Xiaomi", "sber": "Сбер", "salute": "Сбер", "tuvio": "Tuvio",
    "nvidia": "NVIDIA", "realme": "realme", "kivi": "KIVI", "yandex": "Яндекс",
}


def brand_key(manufacturer: str, brand: str, packages: Iterable[str] = ()) -> str:
    text = f"{manufacturer} {brand}".lower()
    for key in BRAND_NAMES:
        if key in text:
            return key
    if any(p.startswith("com.tcl.") for p in packages):
        return "tcl"
    return ""


def detect_profile(packages: "set[str]") -> Profile:
    for prof in PROFILES:
        if any(p in packages for p in prof.detect_packages):
            return prof
        if prof.detect_prefixes and any(p.startswith(pref) for p in packages for pref in prof.detect_prefixes):
            return prof
    return GENERIC


def profile_by_id(pid: str) -> Profile:
    for p in ALL_PROFILES:
        if p.id == pid:
            return p
    return GENERIC


def never_list(profile: Profile, brand: str = "") -> tuple:
    return GLOBAL_NEVER + profile.never + BRAND_NEVER.get(brand, ())


def is_never(pkg: str, profile: Profile, brand: str = "") -> bool:
    """True, если пакет трогать нельзя. Явно разрешённые профилем (default/extra/home) проверяются
    отдельно: is_never смотрит только запреты."""
    low = pkg.lower()
    for m in never_list(profile, brand):
        if low == m or m in low:
            return True
    return False


@dataclass
class Choice:
    """Пакет, который можно предложить к отключению на конкретном ТВ."""
    pkg: Pkg
    checked: bool
    already_disabled: bool = False


def choices_for(profile: Profile, packages: "set[str]", disabled: "set[str]", brand: str = "",
                stock_home: Optional[str] = None) -> "list[Choice]":
    """Что показать на шаге «Убрать рекламу». Только пакеты, которые реально есть на ТВ."""
    res: list = []
    seen: set = set()

    def add(p: Pkg, checked: bool) -> None:
        if p.name in seen or p.name not in packages or is_never(p.name, profile, brand):
            return
        seen.add(p.name)
        res.append(Choice(p, checked and p.name not in disabled, p.name in disabled))

    for p in profile.default_disable:
        add(p, True)
    homes = list(profile.home_packages)
    if stock_home and stock_home not in homes and stock_home != LAUNCHER_PKG:
        homes.append(stock_home)
    for h in homes:
        warn = "Отключай, только если «Домой» всё ещё открывает его, а не WhiteHole."
        if profile.home_warning:
            warn += " " + profile.home_warning
        add(Pkg(h, "Родной домашний экран", "home", "", warn), False)
    for p in profile.extra:
        add(p, False)
    return res


def allowed_packages(profile: Profile, packages: "set[str]", brand: str = "",
                     stock_home: Optional[str] = None) -> "set[str]":
    return {c.pkg.name for c in choices_for(profile, packages, set(), brand, stock_home)}


def all_known_packages() -> "set[str]":
    """Все пакеты из всех профилей — для отката без резервной копии."""
    s: set = set()
    for prof in ALL_PROFILES:
        s.update(p.name for p in prof.default_disable)
        s.update(p.name for p in prof.extra)
        s.update(prof.home_packages)
    return s

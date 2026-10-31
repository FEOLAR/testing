"""Каталог приложений для ТВ: только официальные источники.

Способы установки (в порядке, указанном в catalog.json):
  direct_apk   — фиксированная ссылка на APK на сайте разработчика (хост должен быть в allowed_hosts);
  index_apk    — свежая версия из официального каталога загрузок разработчика (листинг каталога:
                 mirrors.kodi.tv, download.videolan.org), под процессор ТВ;
  github_release — последний релиз на GitHub самого разработчика (через GitHub API);
  store        — открыть страницу приложения в магазине на ТВ (Google Play / RuStore / любой,
                 кто понимает market://); «Установить» пользователь нажимает на телевизоре.
Никаких зеркал APK. Каталог можно обновлять без пересборки: программа берёт свежий catalog.json
из релиза tv-setup-latest, при неудаче — встроенную копию.
"""
from __future__ import annotations

import json
import re
import shlex
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

CATALOG_URL = "https://github.com/FEOLAR/testing/releases/download/tv-setup-latest/catalog.json"
GITHUB_API = "https://api.github.com/repos/{repo}/releases/latest"

PLAY_PKG = "com.android.vending"
METHOD_TYPES = ("direct_apk", "index_apk", "github_release", "store")
STORES = ("play", "rustore", "market")
FORBIDDEN_HOSTS = ("apkmirror", "apkpure", "uptodown", "apkcombo", "aptoide", "apkmonk", "malavida",
                   "softonic", "4pda", "trashbox")
ABI_FALLBACK = {"arm64-v8a": ["arm64-v8a", "armeabi-v7a"], "armeabi-v7a": ["armeabi-v7a"],
                "x86_64": ["x86_64", "x86"], "x86": ["x86"]}


class CatalogError(ValueError):
    pass


@dataclass
class Method:
    type: str
    data: dict

    def get(self, key, default=None):
        return self.data.get(key, default)


@dataclass
class App:
    id: str
    name: str
    category: str
    package: str
    description: str
    methods: "list[Method]"
    alt_packages: "list[str]" = field(default_factory=list)
    detect_uri: str = ""
    verified: bool = False
    source: str = ""
    icon: str = ""

    @property
    def packages(self) -> "list[str]":
        return [p for p in [self.package, *self.alt_packages] if p]

    @property
    def store_only(self) -> bool:
        return all(m.type == "store" for m in self.methods)


@dataclass
class Catalog:
    categories: "list[tuple[str, str]]"
    apps: "list[App]"
    origin: str = ""

    def in_category(self, cat: str) -> "list[App]":
        return [a for a in self.apps if a.category == cat]

    def by_id(self, app_id: str) -> Optional[App]:
        return next((a for a in self.apps if a.id == app_id), None)


def _check_url(url: str, allowed_hosts: "list[str]", what: str) -> None:
    u = urllib.parse.urlparse(url.replace("{abi}", "abi"))
    if u.scheme != "https":
        raise CatalogError(f"{what}: только https ({url})")
    host = (u.hostname or "").lower()
    if any(b in host for b in FORBIDDEN_HOSTS):
        raise CatalogError(f"{what}: зеркала APK запрещены ({host})")
    if not allowed_hosts or not any(host == h or host.endswith("." + h) for h in allowed_hosts):
        raise CatalogError(f"{what}: хост {host} не в allowed_hosts {allowed_hosts}")


def parse_catalog(data: "dict | str", origin: str = "") -> Catalog:
    if isinstance(data, str):
        data = json.loads(data)
    cats = [(c["id"], c["name"]) for c in data.get("categories", [])]
    cat_ids = {c for c, _ in cats}
    apps: list = []
    seen: set = set()
    for raw in data.get("apps", []):
        aid = raw.get("id") or ""
        if not aid or aid in seen:
            raise CatalogError(f"повтор или пустой id: {aid!r}")
        seen.add(aid)
        if raw.get("category") not in cat_ids:
            raise CatalogError(f"{aid}: неизвестная категория {raw.get('category')!r}")
        if not raw.get("package") and not raw.get("detect_uri"):
            raise CatalogError(f"{aid}: нужен package или detect_uri")
        methods = []
        for m in raw.get("methods", []):
            t = m.get("type")
            if t not in METHOD_TYPES:
                raise CatalogError(f"{aid}: неизвестный способ {t!r}")
            if t == "direct_apk":
                _check_url(m.get("url", ""), m.get("allowed_hosts", []), aid)
            elif t == "index_apk":
                _check_url(m.get("index_url", ""), m.get("allowed_hosts", []), aid)
                if not (m.get("file_pattern") or m.get("file_template")):
                    raise CatalogError(f"{aid}: index_apk без file_pattern/file_template")
            elif t == "github_release":
                if not re.match(r"^[\w.-]+/[\w.-]+$", m.get("repo", "")) or not m.get("asset_pattern"):
                    raise CatalogError(f"{aid}: github_release без repo/asset_pattern")
            elif t == "store":
                bad = [s for s in m.get("stores", []) if s not in STORES]
                if bad or not m.get("stores"):
                    raise CatalogError(f"{aid}: неизвестные магазины {bad}")
            methods.append(Method(t, dict(m)))
        if not methods:
            raise CatalogError(f"{aid}: нет способов установки")
        apps.append(App(id=aid, name=raw.get("name", aid), category=raw["category"], package=raw.get("package", ""),
                        description=raw.get("description", ""), methods=methods,
                        alt_packages=list(raw.get("alt_packages", [])), detect_uri=raw.get("detect_uri", ""),
                        verified=bool(raw.get("verified")), source=raw.get("source", ""), icon=raw.get("icon", "")))
    if not apps:
        raise CatalogError("пустой каталог")
    return Catalog(cats, apps, origin)


def load_catalog(bundled_path, fetch: Optional[Callable[[str], bytes]] = None,
                 log: Callable[[str], None] = lambda m: None) -> Catalog:
    """Свежий каталог из релиза, при любой ошибке — встроенный."""
    if fetch is not None:
        try:
            cat = parse_catalog(fetch(CATALOG_URL).decode("utf-8"), "релиз tv-setup-latest")
            log(f"Каталог приложений: из релиза ({len(cat.apps)} шт.)")
            return cat
        except Exception as e:
            log(f"Каталог из релиза не загрузился ({e!r}) — беру встроенный")
    with open(bundled_path, encoding="utf-8") as f:
        cat = parse_catalog(f.read(), "встроенный")
    log(f"Каталог приложений: встроенный ({len(cat.apps)} шт.)")
    return cat


def http_get(url: str, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "WhiteHoleSetup",
                                               "Accept": "application/vnd.github+json, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------------------------------------------------------------- ссылки на APK

def _vkey(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v))


def abis_for(device_abi: str, supported: "list[str]") -> "list[str]":
    order = ABI_FALLBACK.get(device_abi, [device_abi] if device_abi else ["armeabi-v7a"])
    res = [a for a in order if a in supported] if supported else order
    return res


def resolve_index_apk(m: Method, device_abi: str, fetch: Callable[[str], bytes]) -> "tuple[str, str]":
    """Возвращает (url, abi). Листинг каталога загрузок разработчика → самая новая стабильная версия."""
    last_err: Optional[Exception] = None
    for abi in abis_for(device_abi, m.get("abis", [])):
        try:
            base = m.get("index_url").replace("{abi}", abi)
            version = ""
            if m.get("dir_pattern"):
                html = fetch(base).decode("utf-8", "replace")
                dirs = re.findall(m.get("dir_pattern"), html)
                if not dirs:
                    raise CatalogError(f"в {base} не нашлось версий")
                version = max(set(dirs), key=_vkey)
                base = base + version + "/"
            if m.get("file_template"):
                url = base + m.get("file_template").format(version=version, abi=abi)
            else:
                html = fetch(base).decode("utf-8", "replace")
                pat = m.get("file_pattern").replace("{abi}", re.escape(abi))
                found = {(mm.group(0), mm.group(1)) for mm in re.finditer(pat, html)}
                if not found:
                    raise CatalogError(f"в {base} нет APK для {abi}")
                name, _ = max(found, key=lambda x: _vkey(x[1]))
                url = base + name
            _check_url(url, m.get("allowed_hosts", []), "index_apk")
            return url, abi
        except Exception as e:
            last_err = e
    raise CatalogError(f"не нашёл APK: {last_err}")


def resolve_github_release(m: Method, device_abi: str, fetch: Callable[[str], bytes]) -> "tuple[str, str]":
    rel = json.loads(fetch(GITHUB_API.format(repo=m.get("repo"))).decode("utf-8"))
    assets = rel.get("assets", [])
    for abi in abis_for(device_abi, m.get("abis", [])) + [""]:
        pat = m.get("asset_pattern").replace("{abi}", re.escape(abi) if abi else ".*")
        for a in assets:
            if re.fullmatch(pat, a.get("name", "")):
                url = a["browser_download_url"]
                _check_url(url, ["github.com"] + m.get("allowed_hosts", []), "github_release")
                return url, abi
    raise CatalogError(f"в последнем релизе {m.get('repo')} нет подходящего APK")


def resolve_apk_url(m: Method, device_abi: str, fetch: Callable[[str], bytes]) -> "tuple[str, str]":
    if m.type == "direct_apk":
        _check_url(m.get("url"), m.get("allowed_hosts", []), "direct_apk")
        return m.get("url"), ""
    if m.type == "index_apk":
        return resolve_index_apk(m, device_abi, fetch)
    if m.type == "github_release":
        return resolve_github_release(m, device_abi, fetch)
    raise CatalogError(f"{m.type} — не APK")


# ---------------------------------------------------------------- магазины

def store_uri(store: str, pkg: str) -> str:
    if store == "rustore":
        # https://www.rustore.ru/help/sdk/rustore-deeplinks — «rustore://apps.rustore.ru/app/{packageName}»
        return f"rustore://apps.rustore.ru/app/{pkg}"
    return f"market://details?id={pkg}"


def store_command(store: str, pkg: str) -> str:
    """Команда для `adb shell`: открыть страницу приложения в магазине."""
    if not re.fullmatch(r"[A-Za-z0-9_.]+", pkg):
        raise CatalogError(f"странное имя пакета {pkg!r}")
    cmd = f"am start -a android.intent.action.VIEW -d {shlex.quote(store_uri(store, pkg))}"
    if store == "play":
        cmd += f" -p {PLAY_PKG}"
    return cmd


STORE_NAMES = {"play": "Google Play", "rustore": "RuStore", "market": "магазине приложений"}  # «в …»


@dataclass
class Plan:
    """Как будем ставить приложение на конкретном ТВ."""
    kind: str                 # apk / store / none
    method: Optional[Method] = None
    store: str = ""
    reason: str = ""

    @property
    def label(self) -> str:
        if self.kind == "apk":
            return "Установить"
        if self.kind == "store":
            return "Открыть в " + {"market": "магазине"}.get(self.store, STORE_NAMES.get(self.store, "магазине"))
        return "Недоступно"


def choose_plan(app: App, stores: "set[str]") -> Plan:
    """Первый подходящий способ из списка. stores — какие магазины есть на ТВ (play/rustore/market)."""
    for m in app.methods:
        if m.type == "store":
            for s in m.get("stores", []):
                if s in stores:
                    return Plan("store", m, s)
        else:
            return Plan("apk", m)
    needs = [s for m in app.methods if m.type == "store" for s in m.get("stores", [])]
    if "rustore" in needs:
        reason = "Нужен магазин RuStore — поставь его в разделе «Магазины»."
    elif "play" in needs:
        reason = "Есть только в Google Play, а его на этом телевизоре нет."
    else:
        reason = "На телевизоре нет магазина приложений."
    return Plan("none", None, "", reason)

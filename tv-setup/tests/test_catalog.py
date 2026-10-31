"""Каталог приложений: разбор, выбор способа, ссылки, команды магазинов (adb подменён)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_core import SERIAL, FakeTV, make_engine  # noqa: E402
from whitehole_setup import catalog as appcat  # noqa: E402
from whitehole_setup.core import SetupError  # noqa: E402

CATALOG = Path(__file__).resolve().parents[1] / "catalog.json"

KODI_HTML = """<html><a href="kodi-20.5-Nexus-arm64-v8a.apk">x</a>
<a href="kodi-21.2-Omega-arm64-v8a.apk">x</a><a href="kodi-21.10-Omega-arm64-v8a.apk">x</a>
<a href="kodi-22.0-Piers_alpha1-arm64-v8a.apk">beta</a></html>"""
KODI_ARM_HTML = '<a href="kodi-21.2-Omega-armeabi-v7a.apk">x</a><a href="kodi-21.1-Omega-armeabi-v7a.apk">x</a>'
VLC_ROOT = '<a href="3.5.4/">3.5.4/</a><a href="3.6.5/">3.6.5/</a><a href="3.10.0/">3.10.0/</a><a href="last/">'
VLC_BASE = "https://download.videolan.org/pub/videolan/vlc-android/"
# в самой новой папке ещё нет сборки под armeabi-v7a — берём предыдущую версию
VLC_PAGES = {VLC_BASE: VLC_ROOT,
             VLC_BASE + "3.10.0/": '<a href="VLC-Android-3.10.0-arm64-v8a.apk">x</a>',
             VLC_BASE + "3.6.5/": '<a href="VLC-Android-3.6.5-arm64-v8a.apk">x</a>'
                                  '<a href="VLC-Android-3.6.5-armeabi-v7a.apk">x</a>'}


def fake_http(pages):
    def get(url):
        if url not in pages:
            raise OSError(f"404 {url}")
        v = pages[url]
        return v.encode() if isinstance(v, str) else v
    return get


def raw_catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- разбор

def test_bundled_catalog_is_valid():
    cat = appcat.parse_catalog(CATALOG.read_text(encoding="utf-8"))
    assert {c for c, _ in cat.categories} == {"movies", "video", "music", "tools", "stores"}
    ids = [a.id for a in cat.apps]
    assert len(ids) == len(set(ids))
    for a in cat.apps:
        assert a.description and a.source.startswith("https://")
        for m in a.methods:
            if m.type != "store":
                assert m.get("source", a.source).startswith("https://")
    assert cat.by_id("netflix").store_only and cat.by_id("kinopoisk").store_only
    assert not cat.by_id("kodi").store_only and not cat.by_id("vlc").store_only
    assert "smarttube" not in json.dumps(raw_catalog()).lower()


@pytest.mark.parametrize("url,hosts", [
    ("https://www.apkmirror.com/x.apk", ["apkmirror.com"]),
    ("https://apkpure.com/x.apk", ["apkpure.com"]),
    ("http://telegram.org/dl/android/apk", ["telegram.org"]),
    ("https://evil.example.com/kodi.apk", ["mirrors.kodi.tv"]),
])
def test_rejects_mirrors_http_and_foreign_hosts(url, hosts):
    data = raw_catalog()
    data["apps"][0]["methods"] = [{"type": "direct_apk", "url": url, "allowed_hosts": hosts}]
    with pytest.raises(appcat.CatalogError):
        appcat.parse_catalog(data)


def test_rejects_bad_entries():
    for patch in ({"category": "nope"}, {"methods": []}, {"methods": [{"type": "torrent"}]},
                  {"methods": [{"type": "store", "stores": ["aptoide"]}]}, {"package": "", "detect_uri": ""}):
        data = raw_catalog()
        data["apps"][0].update(patch)
        with pytest.raises(appcat.CatalogError):
            appcat.parse_catalog(data)


def test_load_catalog_prefers_release_and_falls_back():
    data = raw_catalog()
    data["apps"] = data["apps"][:2]
    logs = []
    cat = appcat.load_catalog(CATALOG, fetch=lambda url: json.dumps(data).encode(), log=logs.append)
    assert len(cat.apps) == 2 and "релиз" in cat.origin

    def broken(url):
        raise OSError("нет сети")
    cat = appcat.load_catalog(CATALOG, fetch=broken, log=logs.append)
    assert len(cat.apps) == len(raw_catalog()["apps"]) and cat.origin == "встроенный"
    cat = appcat.load_catalog(CATALOG, fetch=lambda url: b"{not json", log=logs.append)
    assert cat.origin == "встроенный"


# ---------------------------------------------------------------- выбор способа

def test_choose_plan_by_available_stores():
    cat = appcat.load_catalog(CATALOG)
    kp, nf, kodi = cat.by_id("kinopoisk"), cat.by_id("netflix"), cat.by_id("kodi")
    assert appcat.choose_plan(kp, {"rustore", "play"}).store == "rustore"
    assert appcat.choose_plan(kp, {"play"}).store == "play"
    assert appcat.choose_plan(kp, {"market"}).store == "market"
    p = appcat.choose_plan(kp, set())
    assert p.kind == "none" and "RuStore" in p.reason
    assert appcat.choose_plan(nf, {"rustore"}).kind == "none"
    assert "Google Play" in appcat.choose_plan(nf, {"rustore"}).reason
    assert appcat.choose_plan(kodi, set()).kind == "apk"
    assert appcat.choose_plan(kp, {"rustore"}).label == "Открыть в RuStore"


def test_store_commands():
    assert appcat.store_command("play", "ru.kinopoisk.tv") == (
        "am start -a android.intent.action.VIEW -d 'market://details?id=ru.kinopoisk.tv' -p com.android.vending")
    assert appcat.store_command("rustore", "com.vk.tv") == (
        "am start -a android.intent.action.VIEW -d rustore://apps.rustore.ru/app/com.vk.tv")
    assert appcat.store_command("market", "a.b") == (
        "am start -a android.intent.action.VIEW -d 'market://details?id=a.b'")
    with pytest.raises(appcat.CatalogError):
        appcat.store_command("play", "a.b; reboot")


# ---------------------------------------------------------------- ссылки на APK

def test_kodi_index_latest_stable_for_abi():
    cat = appcat.load_catalog(CATALOG)
    m = cat.by_id("kodi").methods[0]
    base = "https://mirrors.kodi.tv/releases/android/"
    http = fake_http({base + "arm64-v8a/": KODI_HTML, base + "arm/": KODI_ARM_HTML})
    url, abi = appcat.resolve_apk_url(m, "arm64-v8a", http)
    assert url == base + "arm64-v8a/kodi-21.10-Omega-arm64-v8a.apk" and abi == "arm64-v8a"
    url, abi = appcat.resolve_apk_url(m, "armeabi-v7a", http)
    assert url == base + "arm/kodi-21.2-Omega-armeabi-v7a.apk"   # у Kodi 32-бит лежит в «arm»


def test_index_abi_fallback_to_32bit():
    cat = appcat.load_catalog(CATALOG)
    m = cat.by_id("kodi").methods[0]
    base = "https://mirrors.kodi.tv/releases/android/"
    url, abi = appcat.resolve_apk_url(m, "arm64-v8a", fake_http({base + "arm/": KODI_ARM_HTML}))
    assert abi == "armeabi-v7a"


def test_vlc_dir_and_template():
    cat = appcat.load_catalog(CATALOG)
    m = cat.by_id("vlc").methods[0]
    url, abi = appcat.resolve_apk_url(m, "armeabi-v7a", fake_http(VLC_PAGES))
    assert url == VLC_BASE + "3.6.5/VLC-Android-3.6.5-armeabi-v7a.apk"
    url, abi = appcat.resolve_apk_url(m, "arm64-v8a", fake_http(VLC_PAGES))
    assert url == VLC_BASE + "3.10.0/VLC-Android-3.10.0-arm64-v8a.apk"


def test_github_release_asset_selection():
    m = appcat.Method("github_release", {"repo": "dev/app", "asset_pattern": "app-tv-{abi}\\.apk"})
    api = {"assets": [{"name": "app-tv-armeabi-v7a.apk", "browser_download_url": "https://github.com/dev/app/r/v7.apk"},
                      {"name": "app-tv-arm64-v8a.apk", "browser_download_url": "https://github.com/dev/app/r/v8.apk"}]}
    http = fake_http({appcat.GITHUB_API.format(repo="dev/app"): json.dumps(api)})
    assert appcat.resolve_apk_url(m, "arm64-v8a", http) == ("https://github.com/dev/app/r/v8.apk", "arm64-v8a")
    api["assets"][1]["browser_download_url"] = "https://apkpure.com/x.apk"
    http = fake_http({appcat.GITHUB_API.format(repo="dev/app"): json.dumps(api)})
    with pytest.raises(appcat.CatalogError):
        appcat.resolve_apk_url(m, "arm64-v8a", http)


# ---------------------------------------------------------------- движок + adb

def tv_with_stores(play=False, rustore=False):
    tv = FakeTV(props={"ro.product.cpu.abi": "arm64-v8a"})
    tv.uri_handlers = {}
    tv.packages.discard("com.android.vending")
    if play:
        tv.packages.add("com.android.vending")
        tv.uri_handlers["market"] = "com.android.vending/.AssetBrowserActivity"
    if rustore:
        tv.uri_handlers["rustore"] = "ru.vk.store.tv/.MainActivity"
        tv.uri_handlers.setdefault("market", "ru.vk.store.tv/.MainActivity")
    return tv


def test_catalog_status_detects_stores_and_installed(tmp_path):
    tv = tv_with_stores(rustore=True)
    tv.packages.add("ru.kinopoisk")  # стоит мобильная версия — тоже считается
    eng = make_engine(tmp_path, tv)
    cat = appcat.load_catalog(CATALOG)
    status, stores = eng.catalog_status(eng.device_info(SERIAL, "device"), cat)
    assert stores == {"rustore", "market"}
    assert status["kinopoisk"][0] is True
    assert status["rustore"][0] is True               # RuStore определяется по rustore:// обработчику
    assert status["okko"][1].store == "rustore"
    assert status["netflix"][1].kind == "none"
    assert status["vlc"][1].kind == "apk"


def test_install_store_app_opens_store(tmp_path):
    tv = tv_with_stores(play=True)
    eng = make_engine(tmp_path, tv)
    cat = appcat.load_catalog(CATALOG)
    msg = eng.install_catalog_app(eng.device_info(SERIAL, "device"), cat.by_id("youtube"), {"play", "market"})
    assert "нажми «Установить»" in msg
    assert appcat.store_command("play", "com.google.android.youtube.tv") in tv.shell_cmds()


def test_install_direct_apk_vlc(tmp_path):
    tv = tv_with_stores()
    eng = make_engine(tmp_path, tv)
    base = VLC_BASE
    eng.http_get = fake_http(VLC_PAGES)
    urls = []
    orig = eng.downloader
    eng.downloader = lambda url, dest, progress: (urls.append(url), orig(url, dest, progress))[1]
    cat = appcat.load_catalog(CATALOG)
    msg = eng.install_catalog_app(eng.device_info(SERIAL, "device"), cat.by_id("vlc"), set())
    assert msg == "✓ VLC установлен"
    assert urls == [base + "3.10.0/VLC-Android-3.10.0-arm64-v8a.apk"]
    assert any(c[2:3] == ["install"] and c[-1].endswith("vlc-arm64-v8a.apk") for c in tv.calls if len(c) > 2)


def test_install_apk_fails_then_falls_back_to_store(tmp_path):
    tv = tv_with_stores(play=True)
    eng = make_engine(tmp_path, tv)
    eng.http_get = fake_http({})  # официальный листинг недоступен
    cat = appcat.load_catalog(CATALOG)
    msg = eng.install_catalog_app(eng.device_info(SERIAL, "device"), cat.by_id("kodi"), {"play", "market"})
    assert "Google Play" in msg


def test_install_impossible_explains(tmp_path):
    tv = tv_with_stores()
    eng = make_engine(tmp_path, tv)
    cat = appcat.load_catalog(CATALOG)
    with pytest.raises(SetupError) as e:
        eng.install_catalog_app(eng.device_info(SERIAL, "device"), cat.by_id("okko"), set())
    assert "RuStore" in e.value.message

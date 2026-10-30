"""Определение платформы, профили и смена домашнего экрана на разных ТВ (adb подменён)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_core import SERIAL, YANDEX_PKGS, FakeTV, make_engine  # noqa: E402
from whitehole_setup import profiles  # noqa: E402
from whitehole_setup.core import SetupError  # noqa: E402

WH = "space.whitehole.tv"
COMMON = {"com.google.android.gms", "com.google.android.gsf", "com.android.vending", "com.google.android.katniss",
          "com.android.tv.settings", "com.google.android.inputmethod.latin"}

GOOGLE_TV_TCL = COMMON | {"com.google.android.apps.tv.launcherx", "com.google.android.tungsten.setupwraith",
                          "com.tcl.tvinput", "com.tcl.suspension", "com.tcl.ttvs", "com.tcl.android.launcher"}
ANDROID_TV_SONY = COMMON | {"com.google.android.tvlauncher", "com.google.android.tvrecommendations",
                            "com.sony.dtv.tvx"}
PATCHWALL = COMMON | {"com.mitv.tvhome.atv", "com.mitv.tvhome.mitvplus", "com.mitv.tvhome.michannel",
                      "com.mitv.livetv", "com.xiaomi.mitv.updateservice", "com.google.android.tvlauncher"}
SBER = {"ru.sberdevices.services", "ru.sberdevices.tvlauncher", "com.android.tv.settings"}
BOX = COMMON | {"com.droidlogic.mboxlauncher", "com.droidlogic.tvinput"}
PHONE = {"com.android.launcher3", "com.android.settings", "com.google.android.gms"}

CASES = [
    # пакеты, props, ожидаемый профиль, марка, is_tv
    (YANDEX_PKGS, {}, "yandex", "tuvio", True),
    (GOOGLE_TV_TCL, {"ro.product.manufacturer": "TCL", "ro.product.brand": "TCL", "ro.product.model": "55C745"},
     "googletv", "tcl", True),
    (ANDROID_TV_SONY, {"ro.product.manufacturer": "Sony", "ro.product.model": "BRAVIA 4K VH2"},
     "androidtv", "sony", True),
    (PATCHWALL, {"ro.product.manufacturer": "Xiaomi", "ro.product.model": "MiTV-MSSP2"}, "patchwall", "xiaomi", True),
    (SBER, {"ro.product.manufacturer": "SberDevices", "ro.product.model": "SBDV-00006"}, "sber", "sber", True),
    (BOX, {"ro.product.manufacturer": "Amlogic", "ro.product.brand": "Amlogic", "ro.product.model": "X96 Max"}, "box", "", True),
]


@pytest.mark.parametrize("pkgs,props,pid,brand,is_tv", CASES)
def test_detect_platform(tmp_path, pkgs, props, pid, brand, is_tv):
    tv = FakeTV(packages=pkgs, props=props)
    eng = make_engine(tmp_path, tv)
    d = eng.device_info(SERIAL, "device")
    assert d.profile_id == pid
    assert d.brand_key == brand
    assert d.is_tv is is_tv
    assert d.current_home.endswith("/.HomeActivity")
    assert d.profile.title in d.platform_line and "Android 11" in d.platform_line


def test_platform_line_yandex(tmp_path):
    eng = make_engine(tmp_path, FakeTV())
    d = eng.device_info(SERIAL, "device")
    assert d.platform_line == "Яндекс ТВ · Android 11 · Tuvio TD75UFBHH13"


def test_phone_is_not_tv(tmp_path):
    tv = FakeTV(packages=PHONE, leanback=False, props={"ro.product.manufacturer": "samsung"})
    d = make_engine(tmp_path, tv).device_info(SERIAL, "device")
    assert d.is_tv is False and d.profile_id == "generic"


def test_profiles_never_conflict():
    """Ничего из списков отключения не попадает под «не трогать» (иначе профиль сам себе противоречит)."""
    for prof in profiles.ALL_PROFILES:
        for p in list(prof.default_disable) + list(prof.extra):
            assert not profiles.is_never(p.name, prof), p.name
        for h in prof.home_packages:
            assert not profiles.is_never(h, prof), h
    for name in ("com.google.android.gms", "com.android.vending", "com.google.android.katniss",
                 "com.google.android.inputmethod.latin", "com.android.tv.settings", "com.yandex.tv.services",
                 "com.yandex.tv.alice", "ru.sberdevices.services", "space.whitehole.tv"):
        assert profiles.is_never(name, profiles.GENERIC)
    for tcl in profiles.BRAND_NEVER["tcl"]:
        assert profiles.is_never(tcl, profiles.GOOGLE_TV, "tcl")


def test_only_yandex_has_verified_defaults():
    for prof in profiles.ALL_PROFILES:
        for p in prof.default_disable:
            assert p.confidence == "verified" and prof.id == "yandex"
        for p in prof.extra:
            assert p.confidence == "reported" and p.source


def test_choices_google_tv_tcl(tmp_path):
    tv = FakeTV(packages=GOOGLE_TV_TCL | {WH}, props={"ro.product.manufacturer": "TCL"})
    eng = make_engine(tmp_path, tv)
    st = eng.ads_status(eng.device_info(SERIAL, "device"))
    names = {c.pkg.name: c for c in st.choices}
    assert set(names) == {"com.google.android.apps.tv.launcherx", "com.google.android.tungsten.setupwraith"}
    assert not any(c.checked for c in st.choices)  # всё только по явной галочке
    assert "Google TV" in names["com.google.android.apps.tv.launcherx"].pkg.warning


def test_choices_only_present_packages(tmp_path):
    tv = FakeTV(packages={"com.google.android.tvlauncher", WH} | COMMON)  # без tvrecommendations
    eng = make_engine(tmp_path, tv)
    st = eng.ads_status(eng.device_info(SERIAL, "device"))
    assert [c.pkg.name for c in st.choices] == ["com.google.android.tvlauncher"]


def test_choices_patchwall_skip_livetv(tmp_path):
    tv = FakeTV(packages=PATCHWALL | {WH})
    eng = make_engine(tmp_path, tv)
    st = eng.ads_status(eng.device_info(SERIAL, "device"))
    names = [c.pkg.name for c in st.choices]
    assert "com.mitv.livetv" not in names
    assert {"com.mitv.tvhome.atv", "com.mitv.tvhome.mitvplus", "com.mitv.tvhome.michannel",
            "com.xiaomi.mitv.updateservice"} <= set(names)


def test_sber_offers_only_detected_home(tmp_path):
    tv = FakeTV(packages=SBER | {WH})
    eng = make_engine(tmp_path, tv)
    d = eng.device_info(SERIAL, "device")
    st = eng.ads_status(d)
    assert [c.pkg.name for c in st.choices] == ["ru.sberdevices.tvlauncher"]
    assert st.choices[0].pkg.confidence == "home" and not st.choices[0].checked


def test_install_switches_home_google_tv(tmp_path):
    tv = FakeTV(packages=GOOGLE_TV_TCL)
    eng = make_engine(tmp_path, tv)
    d = eng.device_info(SERIAL, "device")
    done = eng.install_all(d)
    assert "WhiteHole теперь домашний экран" in done
    assert d.current_home == "space.whitehole.tv/.MainActivity"
    data = json.loads(eng.backup_path(d).read_text(encoding="utf-8"))
    assert data["previous_home"] == "com.google.android.apps.tv.launcherx/.HomeActivity"
    assert data["disabled"] == [] and data["platform"] == "googletv"


def test_stock_home_wins_then_disable_and_restore(tmp_path):
    tv = FakeTV(packages=GOOGLE_TV_TCL, stock_wins=True)
    eng = make_engine(tmp_path, tv)
    d = eng.device_info(SERIAL, "device")
    done = eng.install_all(d)
    assert any("перехватывает" in x for x in done)
    # явная галочка: отключить домашний экран Google TV
    res = eng.remove_ads(d, ["com.google.android.apps.tv.launcherx"])
    assert res == ["com.google.android.apps.tv.launcherx"]
    assert tv.effective_home() == "space.whitehole.tv/.MainActivity"
    eng.restore(d)
    assert tv.disabled == set()
    assert tv.home == "com.google.android.apps.tv.launcherx/.HomeActivity"
    assert d.current_home == "com.google.android.apps.tv.launcherx/.HomeActivity"


def test_chooser_when_home_ambiguous(tmp_path):
    tv = FakeTV(packages=ANDROID_TV_SONY, stock_wins=True, home="")
    eng = make_engine(tmp_path, tv)
    d = eng.device_info(SERIAL, "device")
    res = eng.switch_home(d)
    assert res.status in ("chooser", "stock")


def test_old_android_manual_home(tmp_path):
    tv = FakeTV(packages=BOX, sdk=23, props={"ro.build.version.release": "6.0.1"})
    eng = make_engine(tmp_path, tv)
    d = eng.device_info(SERIAL, "device")
    res = eng.switch_home(d)
    assert res.status == "manual" and "Всегда" in res.message
    assert not any(c.startswith("cmd package set-home-activity") for c in tv.shell_cmds())


def test_remove_ads_rejects_forbidden(tmp_path):
    tv = FakeTV(packages=GOOGLE_TV_TCL | {WH}, props={"ro.product.manufacturer": "TCL"})
    eng = make_engine(tmp_path, tv)
    d = eng.device_info(SERIAL, "device")
    for bad in ("com.google.android.gms", "com.tcl.tvinput", "com.google.android.katniss", "com.tcl.android.launcher"):
        with pytest.raises(SetupError) as e:
            eng.remove_ads(d, [bad])
        assert e.value.kind == "forbidden"
    assert not tv.disabled


def test_restore_android_tv_without_backup(tmp_path):
    tv = FakeTV(packages=ANDROID_TV_SONY | {WH})
    tv.disabled = {"com.google.android.tvlauncher", "com.google.android.tvrecommendations", "com.sony.dtv.tvx"}
    eng = make_engine(tmp_path, tv)
    d = eng.device_info(SERIAL, "device")
    eng.restore(d)
    # включены только известные пакеты; чужие (отключённые самим пользователем) не трогаем
    assert tv.disabled == {"com.sony.dtv.tvx"}
    assert tv.home == "com.google.android.tvlauncher/.HomeActivity"


def test_restore_patchwall_from_backup(tmp_path):
    tv = FakeTV(packages=PATCHWALL)
    eng = make_engine(tmp_path, tv)
    d = eng.device_info(SERIAL, "device")
    eng.install_all(d)
    eng.remove_ads(d, ["com.mitv.tvhome.mitvplus", "com.mitv.tvhome.atv"])
    assert tv.disabled == {"com.mitv.tvhome.mitvplus", "com.mitv.tvhome.atv"}
    eng.restore(d, uninstall_launcher=True)
    assert tv.disabled == set()
    assert tv.home.startswith("com.google.android.tvlauncher/") or tv.home.startswith("com.mitv.tvhome")
    assert WH not in tv.packages

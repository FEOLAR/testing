import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from whitehole_setup import core  # noqa: E402
from whitehole_setup.core import (  # noqa: E402
    Adb, DeviceInfo, Engine, SetupError, build_happ_link, classify_connect, happ_intent_command,
    normalize_ip, parse_devices, parse_packages, scan_hosts, subnet_hosts,
)

SERIAL = "192.168.3.19:5555"
YANDEX_PKGS = {
    "com.yandex.tv.home", "com.yandex.launcher.updaterapp", "com.yandex.android.advid",
    "com.yandex.tv.services", "com.yandex.tv.alice", "com.android.tv.settings", "com.yandex.tv.setupwizard",
    "com.android.vending",
}


class FakeTV:
    """Имитация adb + телевизора: отвечает на команды как настоящий adb."""

    def __init__(self, packages=None, state="device", connect_out="connected to " + SERIAL):
        self.packages = set(packages if packages is not None else YANDEX_PKGS)
        self.disabled = set()
        self.state = state
        self.connect_out = connect_out
        self.calls = []
        self.home = None
        self.props = {"ro.product.model": "TD75UFBHH13", "ro.product.manufacturer": "Tuvio",
                      "ro.build.version.release": "11", "ro.serialno": "ABC123"}

    def __call__(self, args, timeout):
        a = args[1:]
        self.calls.append(a)
        if a[0] == "connect":
            return 0, self.connect_out
        if a[0] == "devices":
            body = f"{SERIAL}\t{self.state}" if self.state else ""
            return 0, "List of devices attached\n" + body
        if a[0] in ("start-server", "kill-server"):
            return 0, ""
        if a[0] == "-s" and a[2] == "install":
            apk = a[-1]
            self.packages.add("space.whitehole.tv" if "whitehole" in apk else "su.happ.proxyutility")
            return 0, "Performing Streamed Install\nSuccess"
        if a[0] == "-s" and a[2] == "uninstall":
            self.packages.discard(a[3])
            return 0, "Success"
        if a[0] == "-s" and a[2] == "shell":
            return self.shell(a[3])
        return 1, "unknown"

    def shell(self, cmd):
        if cmd.startswith("getprop "):
            return 0, self.props.get(cmd.split()[1], "")
        if cmd == "pm list packages":
            return 0, "\n".join("package:" + p for p in sorted(self.packages))
        if cmd == "pm list packages -d":
            return 0, "\n".join("package:" + p for p in sorted(self.disabled))
        if cmd.startswith("pm disable-user --user 0 "):
            p = cmd.split()[-1]
            self.disabled.add(p)
            return 0, f"Package {p} new state: disabled-user"
        if cmd.startswith("pm enable "):
            p = cmd.split()[-1]
            self.disabled.discard(p)
            return 0, f"Package {p} new state: enabled"
        if cmd.startswith("cmd package set-home-activity "):
            self.home = cmd.split()[-1]
            return 0, "Success"
        if cmd.startswith("cmd package resolve-activity"):
            return 0, "priority=0 preferredOrder=0\ncom.yandex.tv.home/.HomeActivity"
        if cmd.startswith("am start"):
            return 0, "Starting: Intent { ... }"
        if cmd.startswith("input keyevent"):
            return 0, ""
        return 1, "unknown shell"

    def shell_cmds(self):
        return [c[3] for c in self.calls if c[0] == "-s" and c[2] == "shell"]


def make_engine(tmp_path, tv):
    def fake_download(url, dest, progress):
        dest.write_bytes(b"PK\x03\x04fake")
        progress(1.0, "1 МБ")
        return dest

    adb = Adb("adb", runner=tv)
    return Engine(adb, data_dir=tmp_path, downloader=fake_download, sleep=lambda s: None)


def dev(tv_engine):
    return tv_engine.device_info(SERIAL, "device")


# ------------------------------------------------------------ парсеры

def test_parse_devices():
    out = "* daemon started successfully\nList of devices attached\n192.168.3.19:5555\tdevice\nXYZ\tunauthorized\n"
    assert parse_devices(out) == {"192.168.3.19:5555": "device", "XYZ": "unauthorized"}


def test_parse_packages():
    assert parse_packages("package:a.b\r\npackage:c.d\nfoo") == {"a.b", "c.d"}


@pytest.mark.parametrize("out,res", [
    ("connected to 192.168.3.19:5555", "ok"),
    ("already connected to 192.168.3.19:5555", "ok"),
    ("failed to authenticate to 192.168.3.19:5555", "unauthorized"),
    ("failed to connect to '192.168.3.19:5555': Connection refused", "refused"),
    ("cannot connect to 192.168.3.19:5555: No connection could be made because the target machine "
     "actively refused it. (10061)", "refused"),
    ("cannot connect to 192.168.3.19:5555: A connection attempt failed (10060)", "unreachable"),
    ("failed to connect to '1.2.3.4:5555': Connection timed out", "unreachable"),
    ("something odd", "error"),
])
def test_classify_connect(out, res):
    assert classify_connect(out) == res


def test_normalize_ip():
    assert normalize_ip(" 192.168.3.19 ") == "192.168.3.19:5555"
    assert normalize_ip("192,168,3,19:5556") == "192.168.3.19:5556"
    with pytest.raises(SetupError):
        normalize_ip("tv.local")
    with pytest.raises(SetupError):
        normalize_ip("192.168.3.300")


def test_subnet_hosts():
    hosts = subnet_hosts(["192.168.3.7"])
    assert len(hosts) == 253 and "192.168.3.7" not in hosts
    assert hosts[0] == "192.168.3.1" and hosts[-1] == "192.168.3.254"


def test_scan_hosts_uses_probe():
    opened = {"192.168.3.19", "192.168.3.5"}
    seen = []
    res = scan_hosts(subnet_hosts(["192.168.3.7"]), probe=lambda ip, port, t: ip in opened,
                     progress=lambda f, t: seen.append(f))
    assert res == ["192.168.3.5", "192.168.3.19"]
    assert seen[-1] == 1.0


def test_default_runner_runs_process():
    code, out = core.default_runner([sys.executable, "-c", "print('hello')"], 10)
    assert code == 0 and out == "hello"


def test_default_runner_missing_binary():
    code, out = core.default_runner(["/nonexistent/adb"], 5)
    assert code == -2


# ------------------------------------------------------------ подключение

def test_discover_connects_and_reads_model(tmp_path):
    tv = FakeTV()
    eng = make_engine(tmp_path, tv)
    devs = eng.discover(local_ips=["192.168.3.7"], scanner=lambda hosts, progress: ["192.168.3.19"])
    assert len(devs) == 1
    d = devs[0]
    assert d.model == "TD75UFBHH13" and d.manufacturer == "Tuvio" and d.hw_serial == "ABC123"
    assert d.title == "Tuvio TD75UFBHH13 (192.168.3.19)"
    assert ["connect", SERIAL] in tv.calls


def test_connect_refused(tmp_path):
    tv = FakeTV(connect_out="cannot connect to 192.168.3.19:5555: ... (10061)")
    with pytest.raises(SetupError) as e:
        make_engine(tmp_path, tv).connect(SERIAL)
    assert e.value.kind == "refused"


def test_connect_unauthorized_then_wait(tmp_path):
    tv = FakeTV(state="unauthorized", connect_out="failed to authenticate to " + SERIAL)
    eng = make_engine(tmp_path, tv)
    d = eng.connect(SERIAL)
    assert d.state == "unauthorized" and d.model == ""
    n = {"i": 0}

    def sleep(_):
        n["i"] += 1
        if n["i"] == 2:
            tv.state = "device"
    eng.sleep = sleep
    d = eng.wait_authorized(SERIAL, timeout=60)
    assert d.state == "device" and d.model == "TD75UFBHH13"


def test_wait_authorized_timeout(tmp_path):
    tv = FakeTV(state="unauthorized")
    eng = make_engine(tmp_path, tv)
    t = {"now": 0.0}
    eng.clock = lambda: t["now"]

    def sleep(s):
        t["now"] += 10
    eng.sleep = sleep
    with pytest.raises(SetupError) as e:
        eng.wait_authorized(SERIAL, timeout=60)
    assert e.value.kind == "unauthorized"


# ------------------------------------------------------------ установка

def test_install_all_fresh(tmp_path):
    tv = FakeTV()
    eng = make_engine(tmp_path, tv)
    done = eng.install_all(dev(eng))
    installs = [c[-1] for c in tv.calls if len(c) > 2 and c[2] == "install"]
    assert [Path(p).name for p in installs] == ["whitehole-tv.apk", "Happ.apk"]
    assert all(c[3] == "-r" for c in tv.calls if len(c) > 2 and c[2] == "install")
    assert tv.home == "space.whitehole.tv/.MainActivity"
    assert "Happ установлен" in done


def test_install_skips_existing_happ(tmp_path):
    tv = FakeTV(packages=YANDEX_PKGS | {"su.happ.proxyutility"})
    eng = make_engine(tmp_path, tv)
    eng.install_all(dev(eng))
    installs = [Path(c[-1]).name for c in tv.calls if len(c) > 2 and c[2] == "install"]
    assert installs == ["whitehole-tv.apk"]
    eng.install_all(dev(eng), reinstall_happ=True)
    installs = [Path(c[-1]).name for c in tv.calls if len(c) > 2 and c[2] == "install"]
    assert installs.count("Happ.apk") == 1


def test_install_failure_message(tmp_path):
    tv = FakeTV()

    def runner(args, timeout):
        if "install" in args:
            return 1, "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: signatures do not match]"
        return tv(args, timeout)
    eng = make_engine(tmp_path, tv)
    eng.adb.runner = runner
    with pytest.raises(SetupError) as e:
        eng.install_all(dev(eng))
    assert "другой подписью" in e.value.message


def test_download_fallback_to_cache(tmp_path):
    tv = FakeTV()
    eng = make_engine(tmp_path, tv)
    (tmp_path / "whitehole-tv.apk").write_bytes(b"PK old")
    (tmp_path / "Happ.apk").write_bytes(b"PK old")

    def broken(url, dest, progress):
        raise OSError("no internet")
    eng.downloader = broken
    eng.install_all(dev(eng))  # не падает, ставит из кэша
    eng2 = make_engine(tmp_path / "empty", FakeTV())
    (tmp_path / "empty").mkdir()
    eng2.downloader = broken
    with pytest.raises(SetupError) as e:
        eng2.install_all(dev(eng2))
    assert e.value.kind == "download"


def test_download_real_function(tmp_path):
    class Resp:
        headers = {"Content-Length": "6"}

        def __init__(self):
            self.data = [b"PK\x03\x04", b"zz", b""]

        def read(self, n):
            return self.data.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    prog = []
    p = core.download("https://x/y.apk", tmp_path / "y.apk", lambda f, t: prog.append(f),
                      opener=lambda req, timeout: Resp())
    assert p.read_bytes() == b"PK\x03\x04zz" and prog[-1] == 1.0

    class Html(Resp):
        def __init__(self):
            self.data = [b"<html>", b""]
    with pytest.raises(SetupError):
        core.download("https://x/z.apk", tmp_path / "z.apk", opener=lambda req, timeout: Html())
    assert not (tmp_path / "z.apk").exists()


# ------------------------------------------------------------ Happ

def test_build_happ_link():
    url = "https://sub.example.com/abc?x=1&y=2#WhiteHole"
    assert build_happ_link("  " + url + "\n") == "happ://add/" + url
    assert build_happ_link("happ://crypt5/AAAA") == "happ://crypt5/AAAA"
    for bad in ["", "vless://x", "https://a b", "https://a';reboot;'", "https://a\"b"]:
        with pytest.raises(SetupError):
            build_happ_link(bad)


def test_happ_intent_command_is_quoted():
    link = "happ://add/https://s.example.com/a?x=1&y=2"
    cmd = happ_intent_command(link)
    assert cmd == ("am start -a android.intent.action.VIEW -d "
                   "'happ://add/https://s.example.com/a?x=1&y=2' su.happ.proxyutility")


def test_send_subscription(tmp_path):
    tv = FakeTV(packages=YANDEX_PKGS | {"su.happ.proxyutility"})
    eng = make_engine(tmp_path, tv)
    eng.send_subscription(dev(eng), "https://s.example.com/sub/123")
    assert any(c == happ_intent_command("happ://add/https://s.example.com/sub/123")
               for c in tv.shell_cmds())


def test_send_subscription_without_happ(tmp_path):
    eng = make_engine(tmp_path, FakeTV())
    with pytest.raises(SetupError) as e:
        eng.send_subscription(dev(eng), "https://s.example.com/sub/123")
    assert e.value.kind == "no_happ"


# ------------------------------------------------------------ реклама

def test_ad_list_never_touches_forbidden():
    for p in core.YANDEX_AD_PACKAGES:
        for m in ("com.yandex.tv.services", "alice", "settings", "setupwizard"):
            assert m not in p


def test_remove_ads_requires_launcher(tmp_path):
    tv = FakeTV()
    eng = make_engine(tmp_path, tv)
    with pytest.raises(SetupError) as e:
        eng.remove_ads(dev(eng))
    assert e.value.kind == "no_launcher"
    assert not any("disable" in c for c in tv.shell_cmds())


def test_remove_ads_writes_backup_first_and_disables_only_list(tmp_path):
    tv = FakeTV(packages=(YANDEX_PKGS | {"space.whitehole.tv"}) - {"com.yandex.android.advid"})
    eng = make_engine(tmp_path, tv)
    d = dev(eng)
    order = []
    orig = tv.shell

    def spy(cmd):
        if cmd.startswith("pm disable-user"):
            order.append(("disable", eng.backup_path(d).exists()))
        return orig(cmd)
    tv.shell = spy
    done = eng.remove_ads(d)
    assert set(done) == {"com.yandex.tv.home", "com.yandex.launcher.updaterapp"}
    assert order and all(b for _, b in order)  # бэкап уже был на диске
    disabled_cmds = [c for c in tv.shell_cmds() if c.startswith("pm disable")]
    assert all(c.startswith("pm disable-user --user 0 ") for c in disabled_cmds)
    assert tv.disabled == {"com.yandex.tv.home", "com.yandex.launcher.updaterapp"}
    bp = eng.backup_path(d)
    assert bp.name == "backup-TD75UFBHH13-ABC123.json"
    data = json.loads(bp.read_text(encoding="utf-8"))
    assert data["disabled"] == ["com.yandex.launcher.updaterapp", "com.yandex.tv.home"]
    assert data["serial"] == "ABC123"
    assert tv.home == "space.whitehole.tv/.MainActivity"


def test_remove_ads_not_yandex(tmp_path):
    tv = FakeTV(packages={"space.whitehole.tv", "com.google.android.tvlauncher"})
    eng = make_engine(tmp_path, tv)
    with pytest.raises(SetupError) as e:
        eng.remove_ads(dev(eng))
    assert e.value.kind == "not_yandex"


def test_restore_from_backup(tmp_path):
    tv = FakeTV(packages=YANDEX_PKGS | {"space.whitehole.tv"})
    eng = make_engine(tmp_path, tv)
    d = dev(eng)
    eng.remove_ads(d)
    assert tv.disabled
    done = eng.restore(d, uninstall_launcher=True)
    assert tv.disabled == set()
    assert tv.home == "com.yandex.tv.home/.HomeActivity"
    assert "space.whitehole.tv" not in tv.packages
    assert "Лаунчер WhiteHole удалён" in done
    assert not eng.backup_path(d).exists()
    assert eng.backup_path(d).with_name("backup-TD75UFBHH13-ABC123.restored.json").exists()


def test_restore_without_backup_uses_known_list(tmp_path):
    tv = FakeTV(packages=YANDEX_PKGS | {"space.whitehole.tv"})
    tv.disabled = {"com.yandex.tv.home", "com.yandex.android.advid"}
    eng = make_engine(tmp_path, tv)
    eng.restore(dev(eng))
    enabled = [c for c in tv.shell_cmds() if c.startswith("pm enable")]
    assert sorted(enabled) == sorted("pm enable " + p for p in core.YANDEX_AD_PACKAGES)
    assert "space.whitehole.tv" in tv.packages  # без галочки не удаляем


def test_find_adb_from_bin(tmp_path, monkeypatch):
    monkeypatch.setattr(core.shutil, "which", lambda name: "/usr/bin/adb")
    assert core.find_adb() in ("/usr/bin/adb", str(Path(core.__file__).resolve().parents[1] / "bin" / "adb"))
    monkeypatch.setattr(core.sys, "_MEIPASS", str(tmp_path), raising=False)
    (tmp_path / "adb").mkdir()
    exe = "adb.exe" if core.os.name == "nt" else "adb"
    (tmp_path / "adb" / exe).write_text("")
    assert core.find_adb() == str(tmp_path / "adb" / exe)


def test_no_adb_error():
    with pytest.raises(SetupError) as e:
        Adb(None).devices()
    assert e.value.kind == "no_adb"


def test_device_title_dedup():
    assert DeviceInfo(SERIAL, model="Xiaomi Mi Box", manufacturer="Xiaomi").title == "Xiaomi Mi Box (192.168.3.19)"
    assert DeviceInfo("USB123").title == "Телевизор (USB123)"

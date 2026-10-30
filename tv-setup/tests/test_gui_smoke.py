"""Смоук-тест окна: нужен дисплей (на Linux — xvfb-run). Без него тест пропускается."""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if os.name != "nt" and not os.environ.get("DISPLAY"):
    pytest.skip("нет дисплея", allow_module_level=True)
ctk = pytest.importorskip("customtkinter")

from test_core import FakeTV, make_engine  # noqa: E402
from whitehole_setup import gui  # noqa: E402


def pump(app, cond=lambda: False, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


def patch_scan(eng, probe=lambda ip: ip == "192.168.3.19"):
    from whitehole_setup import netscan
    orig = eng.discover

    def discover(**kw):
        kw.setdefault("probe", probe)
        kw.setdefault("plan", lambda: ([("192.168.3.0/24", netscan.Iface("Wi-Fi", "192.168.3.7", True, True))],
                                       ["192.168.3.19"]))
        return orig(**kw)
    eng.discover = discover


def buttons_enabled(app):
    return all(b.cget("state") == "normal" for b in app._action_buttons + list(app.step_buttons.values()))


@pytest.fixture
def quiet_boxes(monkeypatch):
    errors = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: errors.append(a))
    return errors


def test_busy_released_after_crash_in_scan(tmp_path, quiet_boxes):
    eng = make_engine(tmp_path, FakeTV())

    def boom(**kw):
        raise RuntimeError("сеть сломалась")
    eng.discover = boom
    app = gui.App(engine=eng, start_adb=False)
    try:
        app.on_scan()
        assert pump(app, lambda: not app._busy)
        assert buttons_enabled(app)
        assert "IP" in app.find_msg.cget("text")       # подсказка про ручной ввод
    finally:
        app.on_close()


def test_busy_released_on_setup_error_and_os_error(tmp_path, quiet_boxes):
    eng = make_engine(tmp_path, FakeTV())
    app = gui.App(engine=eng, start_adb=False)
    try:
        for exc in (gui.SetupError("нет", "x"), OSError("socket"), KeyboardInterrupt()):
            def work(e=exc):
                raise e
            app.run_task(work)
            assert pump(app, lambda: not app._busy)
            assert buttons_enabled(app)
    finally:
        app.on_close()


def test_watchdog_releases_hung_task(tmp_path, quiet_boxes):
    import threading
    eng = make_engine(tmp_path, FakeTV())
    app = gui.App(engine=eng, start_adb=False)
    stop = threading.Event()
    timed_out = []
    try:
        app.run_task(lambda: stop.wait(30), watchdog_s=0.5, on_timeout=lambda: timed_out.append(1))
        assert app._busy
        assert pump(app, lambda: not app._busy, 5)
        assert timed_out and buttons_enabled(app)
        stop.set()
        pump(app, timeout=0.3)
        assert not app._busy  # поздний результат зависшей задачи ничего не ломает
    finally:
        stop.set()
        app.on_close()


def test_scan_cancel_and_manual_ip_always_usable(tmp_path, quiet_boxes):
    import threading
    import time as _t
    tv = FakeTV(listed=False)
    eng = make_engine(tmp_path, tv)
    started = threading.Event()

    def slow_probe(ip):
        started.set()
        _t.sleep(0.5)
        return False
    patch_scan(eng, slow_probe)
    eng.clock = _t.monotonic
    app = gui.App(engine=eng, start_adb=False)
    try:
        app.on_scan()
        assert pump(app, lambda: started.is_set())
        assert app.btn_cancel.winfo_manager() == "pack"
        assert app.btn_manual.cget("state") == "normal" and app.ip_entry.cget("state") == "normal"
        app.ip_entry.insert(0, "192.168.3.19")
        app.on_manual()  # во время поиска — отменяет поиск и подключается
        assert pump(app, lambda: app.device is not None and not app._busy, 10)
        assert app.device.serial == "192.168.3.19:5555"
        assert buttons_enabled(app) and not app.btn_cancel.winfo_manager()
    finally:
        app.on_close()


def test_scan_shows_known_device_immediately(tmp_path, quiet_boxes):
    tv = FakeTV(listed=True)  # ТВ уже в `adb devices`
    eng = make_engine(tmp_path, tv)
    patch_scan(eng, lambda ip: False)
    app = gui.App(engine=eng, start_adb=False)
    try:
        app.on_scan()
        assert pump(app, lambda: app.device is not None and not app._busy, 10)
        assert app.device.profile_id == "yandex"
    finally:
        app.on_close()


def test_scan_nothing_found_focuses_manual(tmp_path, quiet_boxes):
    tv = FakeTV(listed=False)
    eng = make_engine(tmp_path, tv)
    patch_scan(eng, lambda ip: False)
    app = gui.App(engine=eng, start_adb=False)
    try:
        app.on_scan()
        assert pump(app, lambda: not app._busy, 10)
        assert "Настройки → Сеть" in app.find_msg.cget("text")
        assert buttons_enabled(app)
    finally:
        app.on_close()


def test_window_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    tv = FakeTV(packages=FakeTV().packages, listed=False)
    eng = make_engine(tmp_path, tv)
    patch_scan(eng)
    app = gui.App(engine=eng, start_adb=True)
    try:
        pump(app, lambda: not app._busy)
        for key, *_ in gui.STEPS:
            app.show_step(key)
            pump(app, lambda: not app._busy)
        app.show_step("find")
        app.on_scan()
        assert pump(app, lambda: app.device is not None)
        assert "TD75UFBHH13" in app.device_label.cget("text")

        app.show_step("install")
        app.on_install()
        assert pump(app, lambda: "install" in app.done)

        app.show_step("sub")
        app.sub_entry.insert(0, "https://s.example.com/sub/1")
        app.on_sub()
        assert pump(app, lambda: "sub" in app.done)

        app.show_step("ads")
        pump(app, lambda: not app._busy)
        app.on_ads()
        assert pump(app, lambda: "ads" in app.done)
        assert tv.disabled

        app.show_step("restore")
        app.on_restore()
        assert pump(app, lambda: "restore" in app.done)
        assert not tv.disabled

        app.toggle_log()
        app.update()
        assert "adb" in app.log_box.get("1.0", "end")
        app.show_help()
        app.update()
    finally:
        app.on_close()
    assert ["kill-server"] in tv.calls


def test_window_google_tv_optin(tmp_path, monkeypatch):
    from test_platforms import GOOGLE_TV_TCL
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    tv = FakeTV(packages=GOOGLE_TV_TCL, stock_wins=True, props={"ro.product.manufacturer": "TCL"})
    eng = make_engine(tmp_path, tv)
    app = gui.App(engine=eng, start_adb=False)
    try:
        app._device_ready(eng.device_info("192.168.3.19:5555", "device"))
        assert "Google TV" in app.device_label.cget("text")
        app.on_install()
        assert pump(app, lambda: "install" in app.done)
        assert "перехватывает" in app.install_msg.cget("text")
        app.show_step("ads")
        assert pump(app, lambda: bool(app._ads_choices) and not app._busy)
        assert app.selected_ads() == []          # ничего не отмечено по умолчанию
        app.on_ads()
        pump(app, lambda: not app._busy, 1)
        assert not tv.disabled
        app._ads_vars["com.google.android.apps.tv.launcherx"].set(True)
        app.on_ads()
        assert pump(app, lambda: "ads" in app.done)
        assert tv.disabled == {"com.google.android.apps.tv.launcherx"}
    finally:
        app.on_close()

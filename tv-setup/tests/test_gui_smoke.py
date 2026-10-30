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


def test_window_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    tv = FakeTV(packages=FakeTV().packages)
    eng = make_engine(tmp_path, tv)
    import whitehole_setup.core as core
    monkeypatch.setattr(core, "local_ipv4_addresses", lambda: ["192.168.3.7"])
    eng_discover = eng.discover
    eng.discover = lambda progress: eng_discover(progress=progress, local_ips=["192.168.3.7"],
                                                 scanner=lambda hosts, progress: ["192.168.3.19"])
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

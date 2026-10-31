"""Точка входа WhiteHole Setup.

  python main.py                 — окно программы
  python main.py --selftest FILE — без окна: проверить, что adb внутри exe работает,
                                   записать отчёт в FILE (используется в CI)
"""
import sys


def selftest(out_path: str) -> int:
    from whitehole_setup import VERSION, core

    lines = [f"WhiteHole Setup {VERSION}"]
    adb_path = core.find_adb()
    lines.append(f"adb: {adb_path}")
    lines.append(f"icon: {core.resource_path('assets', 'icon.ico').exists()}")
    lines.append(f"logo: {core.resource_path('assets', 'logo.png').exists()}")
    try:
        from whitehole_setup import catalog as appcat
        cat = appcat.load_catalog(core.resource_path("catalog.json"))
        lines.append(f"catalog: ok, {len(cat.apps)} apps")
    except Exception as e:  # pragma: no cover
        lines.append(f"catalog: {e!r}")
        return_code_catalog = 1
    else:
        return_code_catalog = 0
    code = 1
    if adb_path:
        rc, out = core.default_runner([adb_path, "version"], 30)
        lines.append(out)
        code = 0 if rc == 0 and "Android Debug Bridge" in out and not return_code_catalog else 1
    try:
        import customtkinter  # noqa: F401
        from whitehole_setup import gui  # noqa: F401
        lines.append("gui import: ok")
    except Exception as e:  # pragma: no cover
        lines.append(f"gui import: {e!r}")
        code = 1
    lines.append(f"local ips: {core.local_ipv4_addresses()}")
    lines.append("RESULT: " + ("OK" if code == 0 else "FAIL"))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return code


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        return selftest(sys.argv[2])
    from whitehole_setup.gui import main as gui_main

    gui_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())

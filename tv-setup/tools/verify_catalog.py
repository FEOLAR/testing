"""Проверка catalog.json в CI: каждая прямая ссылка на APK должна существовать на официальном сервере.

  python tools/verify_catalog.py [catalog.json]

Для direct_apk / index_apk / github_release вычисляет итоговую ссылку (для arm64-v8a и armeabi-v7a),
делает HEAD-запрос и печатает аннотации GitHub Actions (::notice / ::error). Код выхода 1 — если
хоть одна ссылка не работает. Страницы-источники («source») проверяются мягко (::warning).
"""
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from whitehole_setup import catalog as appcat  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (WhiteHoleSetup catalog check)"}


def head(url: str) -> "tuple[int, int, str]":
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, int(r.headers.get("Content-Length") or 0), r.geturl()
    except urllib.error.HTTPError as e:
        if e.code in (403, 405):  # некоторые серверы не любят HEAD — пробуем GET первых байт
            req = urllib.request.Request(url, headers={**UA, "Range": "bytes=0-1"})
            with urllib.request.urlopen(req, timeout=30) as r:
                total = r.headers.get("Content-Range", "").rsplit("/", 1)[-1]
                return r.status, int(total) if total.isdigit() else 0, r.geturl()
        raise


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "catalog.json"
    cat = appcat.parse_catalog(path.read_text(encoding="utf-8"), str(path))
    bad = 0
    for app in cat.apps:
        apk_methods = [m for m in app.methods if m.type != "store"]
        abis = ["arm64-v8a", "armeabi-v7a"] if any(m.type != "direct_apk" for m in apk_methods) else [""]
        for abi in abis if apk_methods else []:
            # Для каждого ABI должен сработать хотя бы один способ; запасные, что не сработали, — ::warning.
            good = False
            problems = []
            for m in apk_methods:
                try:
                    url, got = appcat.resolve_apk_url(m, abi, appcat.http_get)
                    code, size, final = head(url)
                    host = urllib.parse.urlparse(final).hostname
                    if code in (200, 206) and size > 500_000:
                        print(f"::notice title=catalog {app.id} {abi or 'universal'}::{url} -> {code}, "
                              f"{size / 1048576:.1f} MB, итог: {host}")
                        good = True
                        break
                    problems.append(f"{url} -> {code}, {size} B")
                except Exception as e:
                    problems.append(f"{m.type}: {e}")
            for pr in problems:
                print(f"::{'warning' if good else 'error'} title=catalog {app.id} {abi or 'universal'}::{pr}")
            bad += 0 if good else 1
        if app.source.startswith("https://"):
            try:
                src = urllib.parse.quote(app.source, safe=":/?=&%#")
                code, _, _ = head(src)
                if code >= 400:
                    print(f"::warning title=source {app.id}::{app.source} -> {code}")
            except Exception as e:
                print(f"::warning title=source {app.id}::{app.source} -> {e!r}")
    print(f"Итого ошибок: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

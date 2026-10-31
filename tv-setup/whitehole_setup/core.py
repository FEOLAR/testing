"""Вся логика WhiteHole Setup без GUI: adb, поиск ТВ в сети, загрузка APK,
установка, отправка подписки в Happ, отключение рекламы Яндекс ТВ и откат.

Модуль не импортирует tkinter — его можно тестировать на любой ОС
(см. tests/test_core.py, subprocess и сеть там подменяются).
"""
from __future__ import annotations

import concurrent.futures as futures
import datetime as _dt
import ipaddress
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from . import netscan, profiles

# ---------------------------------------------------------------- константы

ADB_PORT = 5555

LAUNCHER_PKG = "space.whitehole.tv"
LAUNCHER_ACTIVITY = "space.whitehole.tv/.MainActivity"
LAUNCHER_BASE = "https://github.com/FEOLAR/testing/releases/download/tv-launcher-latest/"
LAUNCHER_URL = LAUNCHER_BASE + "whitehole-tv.apk"   # универсальный APK
# Отдельные APK под процессор (если они есть в релизе) — меньше и быстрее ставятся.
LAUNCHER_ABI_ASSETS = {
    "arm64-v8a": "whitehole-tv-arm64-v8a.apk",
    "armeabi-v7a": "whitehole-tv-armeabi-v7a.apk",
}
# Встроенный VPN лаунчера рассчитан на Android 7+ (SDK 24); на более старых ставим Happ.
HAPP_MIN_SDK_WITHOUT = 24

HAPP_PKG = "su.happ.proxyutility"
HAPP_URL = "https://github.com/Happ-proxy/happ-android/releases/latest/download/Happ.apk"

YANDEX_HOME_PKG = "com.yandex.tv.home"
# Проверенный владельцем список для Яндекс ТВ (Tuvio). Остальные платформы — в profiles.py.
YANDEX_AD_PACKAGES = tuple(p.name for p in profiles.YANDEX.default_disable)

SUPPORT_URL = "https://t.me/WhiteHoleVPNbot"

ProgressCb = Callable[[Optional[float], str], None]
LogCb = Callable[[str], None]


def _noop_log(_msg: str) -> None:
    pass


def _noop_progress(_frac: Optional[float], _text: str) -> None:
    pass


class SetupError(Exception):
    """Ошибка с дружелюбным текстом для пользователя.

    kind — машинный код (refused, unreachable, unauthorized, ...),
    details — технические подробности для панели «Подробности».
    """

    def __init__(self, message: str, kind: str = "error", details: str = ""):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.details = details


# ---------------------------------------------------------------- пути

def app_data_dir() -> Path:
    """%LOCALAPPDATA%\\WhiteHoleSetup (на других ОС — ~/.cache/WhiteHoleSetup)."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        d = Path(base) / "WhiteHoleSetup"
    else:
        d = Path.home() / ".cache" / "WhiteHoleSetup"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resource_path(*parts: str) -> Path:
    """Путь к файлу внутри exe (PyInstaller: sys._MEIPASS) или рядом с исходниками."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base).joinpath(*parts)
    return Path(__file__).resolve().parents[1].joinpath(*parts)


def find_adb() -> Optional[str]:
    """adb.exe из exe → tv-setup/bin/ → PATH."""
    exe = "adb.exe" if os.name == "nt" else "adb"
    if getattr(sys, "_MEIPASS", None):
        p = Path(sys._MEIPASS) / "adb" / exe  # type: ignore[attr-defined]
        if p.exists():
            return str(p)
    p = Path(__file__).resolve().parents[1] / "bin" / exe
    if p.exists():
        return str(p)
    return shutil.which("adb")


# ---------------------------------------------------------------- запуск adb

Runner = Callable[[list, float], "tuple[int, str]"]


def default_runner(args: list, timeout: float) -> "tuple[int, str]":
    """Запускает процесс без окна консоли, stdout+stderr пишутся во временный файл.

    Файл вместо pipe — специально: `adb start-server` порождает фоновый сервер,
    и если он унаследует pipe, чтение «до конца» зависло бы.
    """
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    with tempfile.TemporaryFile() as out:
        try:
            proc = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=out,
                                  stderr=subprocess.STDOUT, timeout=timeout, **kwargs)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = -1
        except OSError as e:
            return -2, f"не удалось запустить {args[0]}: {e}"
        out.seek(0)
        text = _decode(out.read())
    if code == -1:
        text += "\n[таймаут]"
    return code, text.replace("\r\n", "\n").strip()


def _decode(raw: bytes) -> str:
    """adb пишет UTF-8, а ipconfig/arp на русской Windows — в OEM-кодировке (cp866)."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for enc in (("oem",) if os.name == "nt" else ()) + ("cp866",):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


@dataclass
class DeviceInfo:
    serial: str                # как его знает adb: "192.168.3.19:5555" или серийник USB
    state: str = "device"      # device / unauthorized / offline
    model: str = ""
    manufacturer: str = ""
    android: str = ""
    hw_serial: str = ""        # ro.serialno — не меняется при смене IP
    brand: str = ""            # ro.product.brand
    sdk: int = 0               # ro.build.version.sdk
    profile_id: str = ""       # yandex / googletv / androidtv / patchwall / sber / box / generic
    brand_key: str = ""        # tcl / xiaomi / ... (для списков «не трогать»)
    is_tv: bool = True         # есть feature android.software.leanback (или известная ТВ-оболочка)
    home_apps: "list[str]" = field(default_factory=list)   # пакеты, умеющие быть домашним экраном
    current_home: str = ""     # компонент, который сейчас открывается по «Домой»
    abi: str = ""              # ro.product.cpu.abi (arm64-v8a / armeabi-v7a / x86…)
    has_happ: bool = False
    has_launcher: bool = False

    @property
    def needs_happ(self) -> bool:
        """На Android < 7 встроенный VPN WhiteHole не работает — нужен Happ."""
        return bool(self.sdk) and self.sdk < HAPP_MIN_SDK_WITHOUT

    @property
    def profile(self) -> "profiles.Profile":
        return profiles.profile_by_id(self.profile_id) if self.profile_id else profiles.GENERIC

    @property
    def platform_line(self) -> str:
        """«Яндекс ТВ · Android 11 · Tuvio TD75UFBHH13»."""
        parts = [self.profile.title if self.profile_id else ""]
        if self.android:
            parts.append(f"Android {self.android}")
        name = self.title.rsplit(" (", 1)[0]
        if name != "Телевизор":
            parts.append(name)
        return " · ".join(p for p in parts if p)

    @property
    def ip(self) -> str:
        return self.serial.split(":")[0] if re.match(r"^\d+\.\d+\.\d+\.\d+:\d+$", self.serial) else ""

    @property
    def title(self) -> str:
        name = " ".join(x for x in (self.manufacturer.strip(), self.model.strip()) if x)
        if self.manufacturer and self.model.lower().startswith(self.manufacturer.lower()):
            name = self.model
        if not name:
            name = "Телевизор"
        return f"{name} ({self.ip or self.serial})"


class Adb:
    def __init__(self, path: Optional[str], runner: Runner = default_runner, log: LogCb = _noop_log):
        self.path = path
        self.runner = runner
        self.log = log

    def run(self, args: list, timeout: float = 20) -> "tuple[int, str]":
        if not self.path:
            raise SetupError("Не нашёл adb. Перекачай программу WhiteHole Setup — похоже, файл повреждён.",
                             "no_adb")
        self.log("> adb " + " ".join(args))
        code, out = self.runner([self.path, *args], timeout)
        if out:
            self.log(out if len(out) < 4000 else out[:4000] + "\n…")
        return code, out

    def start_server(self) -> None:
        self.run(["start-server"], timeout=30)

    def kill_server(self) -> None:
        self.run(["kill-server"], timeout=10)

    def devices(self) -> "dict[str, str]":
        _, out = self.run(["devices"], timeout=8)
        return parse_devices(out)

    def state(self, serial: str) -> Optional[str]:
        return self.devices().get(serial)

    def connect(self, serial: str) -> str:
        """Возвращает: ok / unauthorized / refused / unreachable / error."""
        _, out = self.run(["connect", serial], timeout=5)
        return classify_connect(out)

    def disconnect(self, serial: str) -> None:
        self.run(["disconnect", serial], timeout=10)

    def shell(self, serial: str, cmd: str, timeout: float = 30) -> "tuple[int, str]":
        return self.run(["-s", serial, "shell", cmd], timeout=timeout)

    def getprop(self, serial: str, name: str) -> str:
        _, out = self.shell(serial, f"getprop {name}", timeout=10)
        line = out.strip().splitlines()
        return line[0].strip() if line else ""

    def packages(self, serial: str, disabled_only: bool = False) -> "set[str]":
        cmd = "pm list packages -d" if disabled_only else "pm list packages"
        code, out = self.shell(serial, cmd, timeout=30)
        if code != 0 and "package:" not in out:
            raise SetupError("Не получилось прочитать список приложений на телевизоре.", "adb", out)
        return parse_packages(out)

    def install(self, serial: str, apk: str) -> None:
        code, out = self.run(["-s", serial, "install", "-r", apk], timeout=600)
        if "Success" in out:
            return
        raise SetupError(explain_install_failure(out), "install", out)


# ---------------------------------------------------------------- парсеры

def parse_devices(out: str) -> "dict[str, str]":
    res: dict = {}
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            res[parts[0]] = parts[1]
    return res


def parse_packages(out: str) -> "set[str]":
    return {ln.strip()[8:].strip() for ln in out.splitlines() if ln.strip().startswith("package:")}


def classify_connect(out: str) -> str:
    low = out.lower()
    if "failed to authenticate" in low or "unauthorized" in low:
        return "unauthorized"
    if "refused" in low or "10061" in low:
        return "refused"
    if any(x in low for x in ("timed out", "10060", "no route", "unreachable", "10065", "10051",
                              "[таймаут]")):
        return "unreachable"
    if "connected to" in low and "failed" not in low and "cannot" not in low:
        return "ok"
    return "error"


def explain_install_failure(out: str) -> str:
    codes = {
        "INSTALL_FAILED_UPDATE_INCOMPATIBLE": "На телевизоре уже стоит версия этого приложения с другой подписью. "
                                              "Удали её на ТВ (или кнопкой «Вернуть как было» с галочкой "
                                              "«удалить лаунчер») и попробуй ещё раз.",
        "INSTALL_FAILED_INSUFFICIENT_STORAGE": "На телевизоре мало свободного места. Удали ненужные приложения "
                                               "и попробуй ещё раз.",
        "INSTALL_FAILED_VERSION_DOWNGRADE": "На телевизоре стоит более новая версия, чем скачанная.",
        "INSTALL_FAILED_OLDER_SDK": "Телевизор слишком старый для этого приложения (нужен Android поновее).",
        "INSTALL_FAILED_NO_MATCHING_ABIS": "Это приложение не подходит к процессору телевизора.",
        "INSTALL_PARSE_FAILED": "Скачанный файл повреждён. Попробуй ещё раз — я скачаю его заново.",
        "INSTALL_FAILED_USER_RESTRICTED": "Телевизор запретил установку. Разреши на ТВ установку по USB/ADB "
                                         "(в «Для разработчиков») и попробуй снова.",
        "INSTALL_FAILED_VERIFICATION_FAILURE": "Телевизор не дал установить приложение (проверка Google Play Защиты). "
                                               "Отключи проверку приложений по ADB в «Для разработчиков».",
    }
    for code, text in codes.items():
        if code in out:
            return text
    if "device offline" in out or "not found" in out:
        return "Связь с телевизором пропала. Проверь, что он включён, и найди его заново."
    return "Не получилось установить приложение. Подробности — в разделе «Подробности»."


# ---------------------------------------------------------------- сеть

def _is_private_v4(ip: str) -> bool:
    try:
        a = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return a.is_private and not a.is_loopback and not a.is_link_local


def local_ipv4_addresses() -> "list[str]":
    """Локальные IPv4 компьютера (частные сети, без 127.x и 169.254.x)."""
    found: list = []
    try:
        import psutil  # type: ignore

        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET and _is_private_v4(a.address):
                    found.append(a.address)
    except Exception:
        pass
    # Запасной путь: адрес, через который ушёл бы трафик наружу (пакеты не отправляются).
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            found.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            found.append(ip)
    except OSError:
        pass
    res: list = []
    for ip in found:
        if _is_private_v4(ip) and ip not in res:
            res.append(ip)
    # Виртуальные адаптеры (VirtualBox/Hyper-V/WSL) обычно 192.168.56.x / 172.x — ставим их в конец.
    res.sort(key=lambda ip: (ip.startswith("192.168.56.") or ip.startswith("172."), ip))
    return res


def subnet_hosts(local_ips: Iterable[str]) -> "list[str]":
    """Все адреса /24 вокруг каждого локального IP (кроме самого IP)."""
    hosts: list = []
    own = set(local_ips)
    for ip in own:
        net = ipaddress.IPv4Network(ip + "/24", strict=False)
        for h in net.hosts():
            s = str(h)
            if s not in own and s not in hosts:
                hosts.append(s)
    return hosts


def probe_port(ip: str, port: int = ADB_PORT, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def scan_hosts(hosts: "list[str]", port: int = ADB_PORT, timeout: float = 0.3, workers: int = 128,
               probe: Callable[[str, int, float], bool] = probe_port,
               progress: ProgressCb = _noop_progress) -> "list[str]":
    found: list = []
    total = max(len(hosts), 1)
    done = 0
    lock = threading.Lock()
    with futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(probe, h, port, timeout): h for h in hosts}
        for f in futures.as_completed(futs):
            with lock:
                done += 1
                if f.result():
                    found.append(futs[f])
                if done % 16 == 0 or done == total:
                    progress(done / total, f"Проверено адресов: {done} из {total}")
    found.sort(key=lambda s: tuple(int(x) for x in s.split(".")))
    return found


def normalize_ip(text: str) -> str:
    t = text.strip().replace(",", ".").replace(" ", "")
    if ":" in t:
        host, _, port = t.partition(":")
    else:
        host, port = t, str(ADB_PORT)
    try:
        ipaddress.IPv4Address(host)
        p = int(port)
        if not 0 < p < 65536:
            raise ValueError
    except ValueError:
        raise SetupError("Это не похоже на IP-адрес. Пример: 192.168.1.50", "bad_ip")
    return f"{host}:{p}"


# ---------------------------------------------------------------- загрузка

def download(url: str, dest: Path, progress: ProgressCb = _noop_progress, timeout: float = 30,
             opener: Callable = urllib.request.urlopen) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "WhiteHoleSetup"})
    with opener(req, timeout=timeout) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            mb = got / 1048576
            if total:
                progress(got / total, f"{mb:.1f} из {total / 1048576:.1f} МБ")
            else:
                progress(None, f"{mb:.1f} МБ")
    with open(tmp, "rb") as f:
        magic = f.read(2)
    if magic != b"PK":  # файл закрыт — на Windows открытый файл не удалить
        tmp.unlink(missing_ok=True)
        raise SetupError("Скачался не тот файл (не APK). Проверь интернет и попробуй ещё раз.", "download")
    os.replace(tmp, dest)
    return dest


# ---------------------------------------------------------------- Happ

def build_happ_link(text: str) -> str:
    """Ссылка подписки → диплинк Happ.

    Формат «happ://add/<ссылка подписки>» — так же его делает наш бот
    (bot/app/web/index.html: happ: u => 'happ://add/' + u). Схема описана в
    https://rusolv.com/en/blog/how-to-setup-happ («happ://add/...» — схема Happ для
    добавления подписки) и упоминается в https://github.com/Omegaplexx/Happwner
    (перехват интентов happ://add и happ://crypt*). В официальной документации
    https://www.happ.su/main/ru/faq/adding-configuration-subscription диплинк указан
    как способ добавления подписки, но без точного синтаксиса.
    Готовые happ://... (например, зашифрованные happ://crypt5/...) передаём как есть.
    """
    t = text.strip()
    if not t:
        raise SetupError("Вставь ссылку на подписку из бота (раздел «Моя подписка»).", "bad_link")
    if re.search(r"[\s\"'`\\<>]", t) or any(ord(c) < 32 for c in t):
        raise SetupError("В ссылке есть пробелы или лишние символы. Скопируй её из бота целиком ещё раз.",
                         "bad_link")
    low = t.lower()
    if low.startswith("happ://"):
        return t
    if low.startswith("https://") or low.startswith("http://"):
        return "happ://add/" + t
    raise SetupError("Это не похоже на ссылку подписки. Она начинается с https:// — "
                     "скопируй её в боте в разделе «Моя подписка».", "bad_link")


def happ_intent_command(link: str) -> str:
    # adb shell склеивает аргументы в одну строку для sh на ТВ, поэтому
    # ссылку экранируем одинарными кавычками (shlex.quote), чтобы & ? # не ломали команду.
    return f"am start -a android.intent.action.VIEW -d {shlex.quote(link)} {HAPP_PKG}"


def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "tv"


def parse_home_component(out: str) -> str:
    """Последняя строка вида pkg/.Activity из `resolve-activity --brief`."""
    for line in reversed(out.splitlines()):
        line = line.strip()
        if re.match(r"^[A-Za-z0-9_.]+/[A-Za-z0-9_.$]+$", line):
            return line
    return ""


def parse_query_activities(out: str) -> "list[str]":
    res: list = []
    for line in out.splitlines():
        m = re.match(r"^\s*([A-Za-z0-9_.]+)/[A-Za-z0-9_.$]+\s*$", line)
        if m and m.group(1) not in res:
            res.append(m.group(1))
    return res


RESOLVER_PKGS = ("android", "com.android.internal.app")


# ---------------------------------------------------------------- сценарии

@dataclass
class AdsStatus:
    profile_id: str
    profile_title: str
    launcher_installed: bool
    choices: "list[profiles.Choice]" = field(default_factory=list)

    # совместимость со старым кодом/тестами
    @property
    def yandex(self) -> bool:
        return self.profile_id == "yandex"

    @property
    def present(self) -> "list[str]":
        return [c.pkg.name for c in self.choices]

    @property
    def already_disabled(self) -> "list[str]":
        return [c.pkg.name for c in self.choices if c.already_disabled]


@dataclass
class HomeResult:
    status: str        # ok / chooser / stock / manual
    current: str = ""
    message: str = ""


class Engine:
    def __init__(self, adb: Adb, data_dir: Optional[Path] = None, log: LogCb = _noop_log,
                 downloader: Callable = download, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.adb = adb
        self.data_dir = data_dir or app_data_dir()
        self.log = log
        self.downloader = downloader
        self.sleep = sleep
        self.clock = clock

    # --- подключение и определение платформы

    def device_info(self, serial: str, state: Optional[str] = None) -> DeviceInfo:
        st = state or self.adb.state(serial) or "offline"
        info = DeviceInfo(serial=serial, state=st)
        if st == "device":
            self.detect(info)
        return info

    def detect(self, info: DeviceInfo) -> DeviceInfo:
        s = info.serial
        info.model = self.adb.getprop(s, "ro.product.model")
        info.manufacturer = self.adb.getprop(s, "ro.product.manufacturer")
        info.brand = self.adb.getprop(s, "ro.product.brand")
        info.android = self.adb.getprop(s, "ro.build.version.release")
        try:
            info.sdk = int(self.adb.getprop(s, "ro.build.version.sdk") or 0)
        except ValueError:
            info.sdk = 0
        info.hw_serial = self.adb.getprop(s, "ro.serialno")
        info.abi = self.adb.getprop(s, "ro.product.cpu.abi")
        try:
            pkgs = self.adb.packages(s)
        except SetupError:
            pkgs = set()
        info.has_happ = HAPP_PKG in pkgs
        info.has_launcher = LAUNCHER_PKG in pkgs
        prof = profiles.detect_profile(pkgs)
        info.profile_id = prof.id
        info.brand_key = profiles.brand_key(info.manufacturer, info.brand, pkgs)
        _, feats = self.adb.shell(s, "pm list features", timeout=20)
        leanback = "android.software.leanback" in feats
        info.is_tv = leanback or prof.id in ("yandex", "sber", "patchwall", "googletv", "androidtv")
        if not info.is_tv and prof.id == "box":  # launcher3 без leanback — скорее телефон/планшет
            info.profile_id = profiles.GENERIC.id
        info.home_apps = self.home_apps(s) or [p for p in pkgs if p in profiles.all_known_packages()
                                               and p in sum((pr.home_packages for pr in profiles.ALL_PROFILES), ())]
        info.current_home = self.current_home(s)
        self.log(f"Платформа: {info.platform_line}; leanback={leanback}; домашние экраны: "
                 f"{', '.join(info.home_apps) or '?'}; сейчас: {info.current_home or '?'}")
        return info

    def home_apps(self, serial: str) -> "list[str]":
        _, out = self.adb.shell(serial, "cmd package query-activities --brief -a android.intent.action.MAIN "
                                        "-c android.intent.category.HOME", timeout=20)
        return [p for p in parse_query_activities(out) if p not in RESOLVER_PKGS]

    def current_home(self, serial: str) -> str:
        _, out = self.adb.shell(serial, "cmd package resolve-activity --brief -a android.intent.action.MAIN "
                                        "-c android.intent.category.HOME", timeout=20)
        return parse_home_component(out)

    def connect(self, serial: str) -> DeviceInfo:
        res = self.adb.connect(serial)
        ip = serial.split(":")[0]
        if res == "refused":
            raise SetupError(f"Телевизор {ip} отвечает, но не пускает по ADB. Включи на нём «Отладку по сети» "
                             "(см. «Как включить отладку на ТВ») и попробуй снова.", "refused")
        if res == "unreachable":
            raise SetupError(f"Не достучался до {ip}. Проверь, что телевизор включён, подключён к той же "
                             "сети (Wi-Fi/роутер), что и компьютер, и что на нём включена отладка.",
                             "unreachable")
        if res == "error":
            raise SetupError(f"Не получилось подключиться к {ip}.", "error")
        state = self.adb.state(serial) or ("unauthorized" if res == "unauthorized" else "offline")
        return self.device_info(serial, state)

    def light_info(self, serial: str, state: str) -> DeviceInfo:
        """Быстро: только модель и производитель (полное определение — при выборе ТВ)."""
        info = DeviceInfo(serial=serial, state=state)
        if state == "device":
            info.model = self.adb.getprop(serial, "ro.product.model")
            info.manufacturer = self.adb.getprop(serial, "ro.product.manufacturer")
        return info

    def network_plan(self) -> "tuple[list, list[str]]":
        """Подсети для сканирования (лучшие первыми) и адреса из ARP. Всё пишется в журнал."""
        ifaces_ipc: list = []
        arp_ips: list = []
        if os.name == "nt":
            code, out = self.adb.runner(["ipconfig"], 10)
            ifaces_ipc = netscan.parse_ipconfig(out) if code == 0 else []
            code, out = self.adb.runner(["arp", "-a"], 10)
            arp_ips = netscan.parse_arp(out) if code == 0 else []
        ifaces = netscan.merge_ifaces(self.iface_source(), ifaces_ipc)
        if not ifaces:
            ifaces = [netscan.Iface("", ip) for ip in local_ipv4_addresses()]
        for i in ifaces:
            self.log(f"Адаптер: {i.name or '?'} {i.ip} шлюз={'да' if i.gateway else 'нет'} "
                     f"{'вкл' if i.up else 'выкл'} оценка={netscan.iface_score(i) if netscan.is_candidate_ip(i.ip) else 'пропуск'}")
        subnets = netscan.rank_subnets(ifaces)
        self.log("Подсети для поиска: " + (", ".join(s for s, _ in subnets) or "нет"))
        self.log("ARP-таблица: " + (", ".join(arp_ips[:30]) or "пусто"))
        return subnets, arp_ips

    def iface_source(self) -> "list":
        return netscan.psutil_ifaces()

    def discover(self, progress: ProgressCb = _noop_progress,
                 on_found: Callable[[DeviceInfo], None] = lambda d: None,
                 cancel: Optional[threading.Event] = None, timeout: float = 20.0,
                 probe: Optional[Callable[[str], bool]] = None,
                 plan: Optional[Callable[[], "tuple[list, list[str]]"]] = None) -> "list[DeviceInfo]":
        """Ищет ТВ: сначала уже известные adb, потом ARP, потом подсети. Не дольше timeout секунд
        на сканирование (+ до 5 с на подключение). Найденные сразу отдаются в on_found."""
        cancel = cancel or threading.Event()
        deadline = self.clock() + timeout
        result: list = []
        seen: set = set()
        lock = threading.Lock()

        def add(dev: DeviceInfo) -> None:
            with lock:
                if dev.serial in seen:
                    return
                seen.add(dev.serial)
                result.append(dev)
            on_found(dev)

        # 1) Уже знакомые adb устройства (подключённые ранее или по USB) — показываем сразу.
        try:
            for serial, st in self.adb.devices().items():
                if st in ("device", "unauthorized"):
                    add(self.light_info(serial, st))
        except SetupError:
            raise
        except Exception as e:
            self.log(f"adb devices: {e!r}")
        if cancel.is_set():
            return result

        # 2) Сеть.
        progress(None, "Смотрю сетевые адаптеры…")
        subnets, arp_ips = (plan or self.network_plan)()
        hosts = netscan.build_host_list(subnets, arp_ips)
        hosts = [h for h in hosts if f"{h}:{ADB_PORT}" not in seen]
        self.log(f"Проверяю {len(hosts)} адресов (сначала {len(arp_ips)} из ARP)")
        progress(0.0, f"Ищу телевизоры в сети ({len(hosts)} адресов)…")

        connect_pool = futures.ThreadPoolExecutor(max_workers=4)
        connect_futs: list = []

        def connect_one(ip: str) -> None:
            serial = f"{ip}:{ADB_PORT}"
            if serial in seen or cancel.is_set():
                return
            try:
                res = self.adb.connect(serial)
                self.log(f"{ip}: adb connect → {res}")
                if res not in ("ok", "unauthorized"):
                    return
                st = self.adb.state(serial) or ("unauthorized" if res == "unauthorized" else "offline")
                if st in ("device", "unauthorized"):
                    add(self.light_info(serial, st))
            except Exception as e:  # никогда не роняем поиск из-за одного адреса
                self.log(f"{ip}: {e!r}")

        def on_open(ip: str) -> None:
            self.log(f"{ip}: отвечает ADB")
            connect_futs.append(connect_pool.submit(connect_one, ip))

        try:
            found = netscan.scan(
                hosts, probe or (lambda ip: netscan.adb_probe(ip)), cancel=cancel, deadline=deadline,
                clock=self.clock, on_open=on_open,
                progress=lambda d, t: progress(d / max(t, 1), f"Проверено адресов: {d} из {t}"))
            if self.clock() >= deadline:
                self.log(f"Поиск остановлен по таймауту {int(timeout)} с")
            self.log(f"ADB отвечает на: {', '.join(found) or 'нигде'}")
            progress(None, "Подключаюсь к найденным…")
            futures.wait(connect_futs, timeout=8)
        finally:
            connect_pool.shutdown(wait=False, cancel_futures=True)
        return list(result)

    def wait_authorized(self, serial: str, timeout: float = 60, cancel: Optional[threading.Event] = None,
                        progress: ProgressCb = _noop_progress) -> DeviceInfo:
        start = self.clock()
        while True:
            st = self.adb.state(serial)
            if st == "device":
                return self.device_info(serial, st)
            if st is None and ":" in serial:
                self.adb.connect(serial)
            left = timeout - (self.clock() - start)
            if left <= 0:
                raise SetupError("Не дождался разрешения на телевизоре. Нажми «Подключить» ещё раз и "
                                 "подтверди окно «Разрешить отладку?» на ТВ.", "unauthorized")
            if cancel is not None and cancel.is_set():
                raise SetupError("Отменено.", "cancelled")
            progress(None, f"Жду разрешения на телевизоре… ({int(left)} с)")
            self.sleep(1.5)

    # --- установка

    def _fetch(self, url: str, name: str, progress: ProgressCb, label: str) -> Path:
        dest = self.data_dir / name
        try:
            return self.downloader(url, dest, lambda f, t: progress(f, f"Скачиваю {label}: {t}"))
        except SetupError:
            raise
        except Exception as e:  # сеть, SSL, 404…
            self.log(f"Ошибка загрузки {url}: {e!r}")
            if dest.exists():
                self.log(f"Использую ранее скачанный {dest}")
                return dest
            raise SetupError(f"Не получилось скачать {label}. Проверь интернет на компьютере и попробуй ещё раз.",
                             "download", repr(e))

    def fetch_launcher(self, dev: DeviceInfo, progress: ProgressCb = _noop_progress) -> Path:
        """APK под процессор ТВ, если такой файл есть в релизе, иначе универсальный."""
        if not dev.abi:
            dev.abi = self.adb.getprop(dev.serial, "ro.product.cpu.abi")
        asset = LAUNCHER_ABI_ASSETS.get(dev.abi)
        if asset:
            url = LAUNCHER_BASE + asset
            try:
                path = self.downloader(url, self.data_dir / asset,
                                       lambda f, t: progress(f, f"Скачиваю лаунчер WhiteHole ({dev.abi}): {t}"))
                self.log(f"Лаунчер под процессор {dev.abi}: {asset}")
                return path
            except Exception as e:  # нет такого файла в релизе (404) или сеть — берём универсальный
                code = getattr(e, "code", None)
                self.log(f"{asset}: {'нет в релизе' if code == 404 else repr(e)} — беру универсальный APK")
        else:
            self.log(f"Процессор {dev.abi or '?'} — универсальный APK")
        return self._fetch(LAUNCHER_URL, "whitehole-tv.apk", progress, "лаунчер WhiteHole")

    def install_all(self, dev: DeviceInfo, reinstall_happ: bool = False,
                    progress: ProgressCb = _noop_progress, with_happ: bool = False) -> "list[str]":
        """Ставит лаунчер WhiteHole (со встроенным VPN) и делает его домашним экраном.
        Happ ставится, только если Android < 7 или пользователь сам попросил (with_happ / reinstall_happ)."""
        done: list = []
        pkgs = self.adb.packages(dev.serial)
        dev.has_happ = HAPP_PKG in pkgs
        if not dev.sdk:
            try:
                dev.sdk = int(self.adb.getprop(dev.serial, "ro.build.version.sdk") or 0)
            except ValueError:
                dev.sdk = 0
        want_happ = with_happ or reinstall_happ or dev.needs_happ
        need_happ = want_happ and (with_happ or reinstall_happ or not dev.has_happ)
        if not dev.current_home:
            dev.current_home = self.current_home(dev.serial)
        self._remember_original_home(dev)

        launcher_apk = self.fetch_launcher(dev, progress)
        happ_apk = self._fetch(HAPP_URL, "Happ.apk", progress, "Happ") if need_happ else None

        progress(None, "Устанавливаю лаунчер WhiteHole на телевизор…")
        self.adb.install(dev.serial, str(launcher_apk))
        dev.has_launcher = True
        done.append("Лаунчер WhiteHole установлен (VPN уже встроен)")

        if happ_apk:
            progress(None, "Устанавливаю Happ на телевизор…")
            self.adb.install(dev.serial, str(happ_apk))
            dev.has_happ = True
            done.append("Happ установлен" + (" — на этом Android VPN работает через него" if dev.needs_happ else ""))
        elif want_happ:
            done.append("Happ уже был установлен — не трогал")

        progress(None, "Делаю WhiteHole домашним экраном…")
        home = self.switch_home(dev)
        done.append(home.message)
        self.adb.shell(dev.serial, f"am start -n {LAUNCHER_ACTIVITY}", timeout=15)
        progress(1.0, "Готово")
        return done

    def open_launcher(self, dev: DeviceInfo) -> None:
        if LAUNCHER_PKG not in self.adb.packages(dev.serial):
            raise SetupError("На телевизоре ещё нет WhiteHole. Сначала сделай шаг «Установить».", "no_launcher")
        code, out = self.adb.shell(dev.serial, f"am start -n {LAUNCHER_ACTIVITY}", timeout=15)
        if code != 0 or "Error" in out:
            raise SetupError("Не получилось открыть WhiteHole на телевизоре. Открой его пультом.", "open", out)

    def grant_vpn(self, dev: DeviceInfo) -> None:
        """Заранее выдаёт WhiteHole разрешение на VPN, чтобы на ТВ не появлялось системное окно
        «Разрешить подключение к VPN?».

        Как это работает: согласие пользователя на VpnService система хранит как app-op
        ACTIVATE_VPN (= OP_ACTIVATE_VPN, «granted to apps that have already been given user consent
        to start VpnService based VPN connections» — AppOpsManager, AOSP commit 3eb9520d1a4d,
        https://android.googlesource.com/platform/frameworks/base/+/3eb9520d1a4d%5E%21/).
        VpnService.prepare() возвращает null (диалога нет), если приложение уже «предварительно
        согласовано» (javadoc VpnService.prepare / prepareAndAuthorize →
        setVpnPackageAuthorization, https://chromium.googlesource.com/android_tools/+/HEAD/sdk/sources/android-25/android/net/VpnService.java).
        `appops set … ACTIVATE_VPN allow` из adb shell ставит тот же флаг. Проверено владельцем на Tuvio
        (Android 11); на прошивках отдельных производителей может не сработать — тогда ТВ один раз
        покажет обычное окно.
        """
        if LAUNCHER_PKG not in self.adb.packages(dev.serial):
            raise SetupError("Сначала установи WhiteHole (шаг «Установить»).", "no_launcher")
        code, out = self.adb.shell(dev.serial, f"appops set {LAUNCHER_PKG} ACTIVATE_VPN allow", timeout=15)
        _, check = self.adb.shell(dev.serial, f"appops get {LAUNCHER_PKG} ACTIVATE_VPN", timeout=15)
        if "allow" not in check.lower():
            raise SetupError("Телевизор не дал выдать разрешение заранее. Ничего страшного: при первом "
                             "подключении на ТВ появится окно «Разрешить подключение к VPN?» — нажми ОК.",
                             "appops", out + "\n" + check)

    def set_home(self, serial: str, component: str) -> bool:
        code, out = self.adb.shell(serial, f"cmd package set-home-activity {shlex.quote(component)}")
        low = out.lower()
        return code == 0 and "error" not in low and "exception" not in low and "unknown" not in low

    def switch_home(self, dev: DeviceInfo) -> HomeResult:
        """set-home-activity → проверка resolve-activity. На Android < 7 команды нет — инструкция."""
        manual = ("Нажми «Домой» на пульте и выбери WhiteHole → «Всегда». Если телевизор не спрашивает — "
                  "открой шаг «Убрать рекламу» и отключи родной домашний экран.")
        if dev.sdk and dev.sdk < 24:
            return HomeResult("manual", "", "Этот Android не умеет менять домашний экран командой. " + manual)
        ok = self.set_home(dev.serial, LAUNCHER_ACTIVITY)
        cur = self.current_home(dev.serial)
        dev.current_home = cur
        pkg = cur.split("/")[0] if cur else ""
        if pkg == LAUNCHER_PKG:
            return HomeResult("ok", cur, "WhiteHole теперь домашний экран")
        if not cur or pkg in RESOLVER_PKGS:
            return HomeResult("chooser", cur, "Почти готово: " + manual)
        self.log(f"set-home-activity={'ok' if ok else 'ошибка'}, но «Домой» открывает {cur}")
        return HomeResult("stock", cur, "Родной домашний экран всё ещё перехватывает «Домой». "
                                        "Открой шаг «Убрать рекламу» и отключи его галочкой "
                                        "(или нажми «Домой» и выбери WhiteHole → «Всегда»).")

    # --- подписка

    def send_subscription(self, dev: DeviceInfo, text: str) -> str:
        link = build_happ_link(text)
        if HAPP_PKG not in self.adb.packages(dev.serial):
            raise SetupError("На телевизоре нет Happ. Сначала сделай шаг «Установить».", "no_happ")
        code, out = self.adb.shell(dev.serial, happ_intent_command(link))
        if code != 0 or "Error" in out or "Exception" in out:
            raise SetupError("Happ на телевизоре не принял ссылку. Открой Happ на ТВ и добавь подписку "
                             "вручную или через «Web Import».", "happ", out)
        return link

    # --- реклама / родной домашний экран

    def _stock_home_pkg(self, dev: DeviceInfo, backup: Optional[dict] = None) -> Optional[str]:
        for comp in ((backup or {}).get("previous_home") or "", dev.current_home or ""):
            pkg = comp.split("/")[0]
            if pkg and pkg != LAUNCHER_PKG and pkg not in RESOLVER_PKGS:
                return pkg
        return None

    def ads_status(self, dev: DeviceInfo) -> AdsStatus:
        pkgs = self.adb.packages(dev.serial)
        disabled = self.adb.packages(dev.serial, disabled_only=True)
        prof = profiles.detect_profile(pkgs)
        dev.profile_id = prof.id
        choices = profiles.choices_for(prof, pkgs, disabled, dev.brand_key,
                                       self._stock_home_pkg(dev, self.load_backup(dev)))
        return AdsStatus(prof.id, prof.title, LAUNCHER_PKG in pkgs, choices)

    def backup_path(self, dev: DeviceInfo) -> Path:
        ident = dev.hw_serial or dev.serial
        return self.data_dir / f"backup-{_safe_name(dev.model or 'tv')}-{_safe_name(ident)}.json"

    def load_backup(self, dev: DeviceInfo) -> Optional[dict]:
        p = self.backup_path(dev)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            self.log(f"Не читается резервная копия {p}: {e}")
            return None

    def _write_backup(self, dev: DeviceInfo, add_disabled: "Iterable[str]" = ()) -> Path:
        old = self.load_backup(dev) or {}
        now = _dt.datetime.now().isoformat(timespec="seconds")
        prev_home = old.get("previous_home") or ""
        if not prev_home and dev.current_home and not dev.current_home.startswith(LAUNCHER_PKG + "/"):
            prev_home = dev.current_home
        backup = {
            "app": "WhiteHole Setup",
            "serial": dev.hw_serial or dev.serial,
            "adb_serial": dev.serial,
            "model": dev.model,
            "manufacturer": dev.manufacturer,
            "platform": dev.profile_id or old.get("platform", ""),
            "created": old.get("created") or now,
            "updated": now,
            "previous_home": prev_home,
            "disabled": sorted(set(old.get("disabled", [])) | set(add_disabled)),
        }
        path = self.backup_path(dev)
        path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _remember_original_home(self, dev: DeviceInfo) -> None:
        """Записываем родной домашний экран ДО того, как WhiteHole станет домашним."""
        if self.load_backup(dev) is None and dev.current_home and \
                not dev.current_home.startswith(LAUNCHER_PKG + "/"):
            p = self._write_backup(dev)
            self.log(f"Запомнил исходный домашний экран {dev.current_home} в {p}")

    def remove_ads(self, dev: DeviceInfo, selected: Optional["Iterable[str]"] = None,
                   progress: ProgressCb = _noop_progress) -> "list[str]":
        """Отключает выбранные пакеты (по умолчанию — отмеченные профилем как verified)."""
        st = self.ads_status(dev)
        if not st.launcher_installed:
            raise SetupError("Сначала установи лаунчер WhiteHole (шаг «Установить»), иначе у телевизора "
                             "не останется домашнего экрана.", "no_launcher")
        if not st.choices:
            raise SetupError(f"Для платформы «{st.profile_title}» отключать нечего — "
                             "безопасного списка для неё нет.", "nothing")
        allowed = {c.pkg.name: c for c in st.choices}
        if selected is None:
            wanted = [c.pkg.name for c in st.choices if c.checked]
        else:
            wanted = list(dict.fromkeys(selected))
        if not wanted:
            raise SetupError("Ничего не отмечено. Поставь галочки у того, что хочешь отключить.",
                             "nothing_selected")
        bad = [p for p in wanted if p not in allowed]
        if bad:
            raise SetupError("Эти пакеты отключать нельзя: " + ", ".join(bad), "forbidden")
        prof = profiles.profile_by_id(st.profile_id)
        targets = [p for p in wanted if not allowed[p].already_disabled]
        for p in targets:  # двойная страховка
            assert not profiles.is_never(p, prof, dev.brand_key), p
        if not targets:
            return []

        # 1) Резервная копия ДО любых изменений (дополняем, если уже была).
        if not dev.current_home:
            dev.current_home = self.current_home(dev.serial)
        path = self._write_backup(dev, targets)
        self.log(f"Резервная копия: {path}")

        # 2) Домашний экран — WhiteHole.
        self.set_home(dev.serial, LAUNCHER_ACTIVITY)

        # 3) Отключаем.
        done: list = []
        for i, p in enumerate(targets):
            progress(i / max(len(targets), 1), f"Отключаю {p}…")
            code, out = self.adb.shell(dev.serial, f"pm disable-user --user 0 {p}")
            if "disabled" in out.lower():
                done.append(p)
            else:
                self.log(f"Не отключился {p}: {out}")
        self.set_home(dev.serial, LAUNCHER_ACTIVITY)
        self.adb.shell(dev.serial, f"am start -n {LAUNCHER_ACTIVITY}", timeout=15)
        progress(1.0, "Готово")
        return done

    def restore(self, dev: DeviceInfo, uninstall_launcher: bool = False,
                progress: ProgressCb = _noop_progress) -> "list[str]":
        done: list = []
        backup = self.load_backup(dev)
        pkgs = self.adb.packages(dev.serial)
        known = profiles.all_known_packages()
        if backup and backup.get("disabled"):
            targets = list(backup["disabled"])
            self.log(f"Беру список из резервной копии: {', '.join(targets)}")
        else:
            disabled = self.adb.packages(dev.serial, disabled_only=True)
            targets = sorted(p for p in disabled if p in known)
            self.log("Резервной копии нет — включаю отключённые пакеты из известных списков: "
                     + (", ".join(targets) or "таких нет"))
        for p in targets:
            if p not in pkgs:
                continue
            progress(None, f"Включаю {p}…")
            code, out = self.adb.shell(dev.serial, f"pm enable {p}")
            if "enabled" in out.lower():
                done.append(f"Включён {p}")
            else:
                self.log(f"Не включился {p}: {out}")

        # Домашний экран — тот, что был до WhiteHole.
        comp = ""
        prev = (backup or {}).get("previous_home") or ""
        if prev and prev.split("/")[0] in pkgs:
            comp = prev
        else:
            prof = profiles.detect_profile(pkgs)
            for h in prof.home_packages:
                if h in pkgs:
                    comp = self.resolve_home_activity(dev.serial, h) or h
                    break
        if comp:
            if self.set_home(dev.serial, comp):
                done.append(f"Домашний экран — снова родной ({comp.split('/')[0]})")
            else:
                done.append("Нажми «Домой» и выбери родной домашний экран → «Всегда»")
        if uninstall_launcher and LAUNCHER_PKG in pkgs:
            progress(None, "Удаляю лаунчер WhiteHole…")
            code, out = self.adb.run(["-s", dev.serial, "uninstall", LAUNCHER_PKG], timeout=60)
            if "Success" in out:
                done.append("Лаунчер WhiteHole удалён")
            else:
                self.log(f"Не удалился лаунчер: {out}")
        bp = self.backup_path(dev)
        if backup and bp.exists() and (uninstall_launcher or backup.get("disabled")):
            bp.replace(bp.with_name(bp.stem + ".restored.json"))
        self.adb.shell(dev.serial, "input keyevent KEYCODE_HOME", timeout=10)
        dev.current_home = self.current_home(dev.serial)
        progress(1.0, "Готово")
        return done

    def resolve_home_activity(self, serial: str, pkg: str) -> Optional[str]:
        _, out = self.adb.shell(serial, "cmd package resolve-activity --brief -a android.intent.action.MAIN "
                                        f"-c android.intent.category.HOME {pkg}")
        comp = parse_home_component(out)
        return comp if comp.startswith(pkg + "/") else None


def is_forbidden_package(pkg: str) -> bool:
    """Глобальный запрет (без учёта профиля) — для обратной совместимости."""
    return profiles.is_never(pkg, profiles.GENERIC)

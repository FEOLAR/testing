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

# ---------------------------------------------------------------- константы

ADB_PORT = 5555

LAUNCHER_PKG = "space.whitehole.tv"
LAUNCHER_ACTIVITY = "space.whitehole.tv/.MainActivity"
LAUNCHER_URL = "https://github.com/FEOLAR/testing/releases/download/tv-launcher-latest/whitehole-tv.apk"

HAPP_PKG = "su.happ.proxyutility"
HAPP_URL = "https://github.com/Happ-proxy/happ-android/releases/latest/download/Happ.apk"

YANDEX_HOME_PKG = "com.yandex.tv.home"
# Ровно эти пакеты (и только если они есть на ТВ) отключаем на Яндекс ТВ.
# Алиса, сервисы Яндекс ТВ, настройки и мастер настройки НЕ трогаем никогда.
YANDEX_AD_PACKAGES = (
    "com.yandex.tv.home",            # родной домашний экран с рекламой
    "com.yandex.launcher.updaterapp",  # автообновление родного лаунчера
    "com.yandex.android.advid",      # рекламный идентификатор
)
FORBIDDEN_MARKERS = ("com.yandex.tv.services", "alice", "settings", "setupwizard")

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
        text = out.read().decode("utf-8", errors="replace")
    if code == -1:
        text += "\n[таймаут]"
    return code, text.replace("\r\n", "\n").strip()


@dataclass
class DeviceInfo:
    serial: str                # как его знает adb: "192.168.3.19:5555" или серийник USB
    state: str = "device"      # device / unauthorized / offline
    model: str = ""
    manufacturer: str = ""
    android: str = ""
    hw_serial: str = ""        # ro.serialno — не меняется при смене IP

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
        _, out = self.run(["devices"], timeout=15)
        return parse_devices(out)

    def state(self, serial: str) -> Optional[str]:
        return self.devices().get(serial)

    def connect(self, serial: str) -> str:
        """Возвращает: ok / unauthorized / refused / unreachable / error."""
        _, out = self.run(["connect", serial], timeout=15)
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


def is_forbidden_package(pkg: str) -> bool:
    low = pkg.lower()
    return any(m in low for m in FORBIDDEN_MARKERS) and pkg not in YANDEX_AD_PACKAGES


def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "tv"


# ---------------------------------------------------------------- сценарии

@dataclass
class AdsStatus:
    yandex: bool
    launcher_installed: bool
    present: "list[str]" = field(default_factory=list)          # какие из списка есть на ТВ
    already_disabled: "list[str]" = field(default_factory=list)


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

    # --- подключение

    def device_info(self, serial: str, state: Optional[str] = None) -> DeviceInfo:
        st = state or self.adb.state(serial) or "offline"
        info = DeviceInfo(serial=serial, state=st)
        if st == "device":
            info.model = self.adb.getprop(serial, "ro.product.model")
            info.manufacturer = self.adb.getprop(serial, "ro.product.manufacturer")
            info.android = self.adb.getprop(serial, "ro.build.version.release")
            info.hw_serial = self.adb.getprop(serial, "ro.serialno")
        return info

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

    def discover(self, progress: ProgressCb = _noop_progress,
                 local_ips: Optional["list[str]"] = None,
                 scanner: Callable = scan_hosts) -> "list[DeviceInfo]":
        ips = local_ips if local_ips is not None else local_ipv4_addresses()
        self.log("Локальные адреса компьютера: " + (", ".join(ips) or "не найдены"))
        result: list = []
        seen: set = set()
        if ips:
            hosts = subnet_hosts(ips)
            progress(0.0, f"Ищу телевизоры в сети ({len(hosts)} адресов)…")
            found = scanner(hosts, progress=progress)
            self.log("Открыт порт 5555: " + (", ".join(found) or "нигде"))
            for ip in found:
                serial = f"{ip}:{ADB_PORT}"
                try:
                    dev = self.connect(serial)
                except SetupError as e:
                    self.log(f"{ip}: {e.message}")
                    continue
                result.append(dev)
                seen.add(serial)
        # Уже подключённые (в т.ч. по USB).
        for serial, st in self.adb.devices().items():
            if serial not in seen and st in ("device", "unauthorized"):
                result.append(self.device_info(serial, st))
        return result

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

    def install_all(self, dev: DeviceInfo, reinstall_happ: bool = False,
                    progress: ProgressCb = _noop_progress) -> "list[str]":
        """Ставит лаунчер и Happ, делает лаунчер домашним экраном. Возвращает список сделанного."""
        done: list = []
        pkgs = self.adb.packages(dev.serial)
        need_happ = reinstall_happ or HAPP_PKG not in pkgs

        launcher_apk = self._fetch(LAUNCHER_URL, "whitehole-tv.apk", progress, "лаунчер WhiteHole")
        happ_apk = self._fetch(HAPP_URL, "Happ.apk", progress, "Happ") if need_happ else None

        progress(None, "Устанавливаю лаунчер WhiteHole на телевизор…")
        self.adb.install(dev.serial, str(launcher_apk))
        done.append("Лаунчер WhiteHole установлен")

        if happ_apk:
            progress(None, "Устанавливаю Happ на телевизор…")
            self.adb.install(dev.serial, str(happ_apk))
            done.append("Happ установлен")
        else:
            done.append("Happ уже был установлен — не трогал")

        progress(None, "Делаю WhiteHole домашним экраном…")
        if self.set_home(dev.serial, LAUNCHER_ACTIVITY):
            done.append("WhiteHole теперь домашний экран")
        else:
            done.append("Не получилось назначить домашний экран — нажми «Домой» на пульте и выбери WhiteHole")
        self.adb.shell(dev.serial, f"am start -n {LAUNCHER_ACTIVITY}", timeout=15)
        progress(1.0, "Готово")
        return done

    def set_home(self, serial: str, component: str) -> bool:
        code, out = self.adb.shell(serial, f"cmd package set-home-activity {shlex.quote(component)}")
        low = out.lower()
        return code == 0 and "error" not in low and "exception" not in low and "unknown" not in low

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

    # --- реклама Яндекс ТВ

    def ads_status(self, dev: DeviceInfo) -> AdsStatus:
        pkgs = self.adb.packages(dev.serial)
        disabled = self.adb.packages(dev.serial, disabled_only=True)
        present = [p for p in YANDEX_AD_PACKAGES if p in pkgs]
        return AdsStatus(yandex=YANDEX_HOME_PKG in pkgs, launcher_installed=LAUNCHER_PKG in pkgs,
                         present=present, already_disabled=[p for p in present if p in disabled])

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

    def remove_ads(self, dev: DeviceInfo, progress: ProgressCb = _noop_progress) -> "list[str]":
        st = self.ads_status(dev)
        if not st.launcher_installed:
            raise SetupError("Сначала установи лаунчер WhiteHole (шаг «Установить»), иначе у телевизора "
                             "не останется домашнего экрана.", "no_launcher")
        if not st.yandex:
            raise SetupError("Это не Яндекс ТВ — здесь отключать нечего.", "not_yandex")
        targets = [p for p in st.present if p not in st.already_disabled]
        for p in targets:  # двойная страховка
            assert p in YANDEX_AD_PACKAGES and not is_forbidden_package(p), p

        # 1) Резервная копия ДО любых изменений (дополняем, если уже была).
        old = self.load_backup(dev) or {}
        prev = list(old.get("disabled", []))
        backup = {
            "app": "WhiteHole Setup",
            "serial": dev.hw_serial or dev.serial,
            "adb_serial": dev.serial,
            "model": dev.model,
            "manufacturer": dev.manufacturer,
            "created": old.get("created") or _dt.datetime.now().isoformat(timespec="seconds"),
            "updated": _dt.datetime.now().isoformat(timespec="seconds"),
            "previous_home": YANDEX_HOME_PKG,
            "disabled": sorted(set(prev) | set(targets)),
        }
        path = self.backup_path(dev)
        path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
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
        self.adb.shell(dev.serial, f"am start -n {LAUNCHER_ACTIVITY}", timeout=15)
        progress(1.0, "Готово")
        return done

    def restore(self, dev: DeviceInfo, uninstall_launcher: bool = False,
                progress: ProgressCb = _noop_progress) -> "list[str]":
        done: list = []
        backup = self.load_backup(dev)
        if backup and backup.get("disabled"):
            targets = [p for p in backup["disabled"] if p in YANDEX_AD_PACKAGES]
            self.log(f"Беру список из резервной копии: {', '.join(targets)}")
        else:
            targets = list(YANDEX_AD_PACKAGES)
            self.log("Резервной копии нет — включаю всё из известного списка.")
        pkgs = self.adb.packages(dev.serial)
        for p in targets:
            if p not in pkgs:
                continue
            progress(None, f"Включаю {p}…")
            code, out = self.adb.shell(dev.serial, f"pm enable {p}")
            if "enabled" in out.lower():
                done.append(f"Включён {p}")
            else:
                self.log(f"Не включился {p}: {out}")
        if YANDEX_HOME_PKG in pkgs:
            comp = self.resolve_home_activity(dev.serial, YANDEX_HOME_PKG) or YANDEX_HOME_PKG
            if self.set_home(dev.serial, comp):
                done.append("Домашний экран — снова Яндекс ТВ")
        if uninstall_launcher and LAUNCHER_PKG in pkgs:
            progress(None, "Удаляю лаунчер WhiteHole…")
            code, out = self.adb.run(["-s", dev.serial, "uninstall", LAUNCHER_PKG], timeout=60)
            if "Success" in out:
                done.append("Лаунчер WhiteHole удалён")
            else:
                self.log(f"Не удалился лаунчер: {out}")
        bp = self.backup_path(dev)
        if backup and bp.exists():
            bp.replace(bp.with_name(bp.stem + ".restored.json"))
        self.adb.shell(dev.serial, "input keyevent KEYCODE_HOME", timeout=10)
        progress(1.0, "Готово")
        return done

    def resolve_home_activity(self, serial: str, pkg: str) -> Optional[str]:
        _, out = self.adb.shell(serial, "cmd package resolve-activity --brief -a android.intent.action.MAIN "
                                        f"-c android.intent.category.HOME {pkg}")
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith(pkg + "/"):
                return line
        return None

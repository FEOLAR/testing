"""Поиск телевизоров с ADB в локальной сети (без GUI).

Почему так сложно:
* На Windows бывает много адаптеров: Hyper-V/WSL (vEthernet, 172.x), VirtualBox (192.168.56.x),
  VPN/TUN (Happ, WireGuard, sing-box — 198.18.x, 10.x, 172.19.x). Сканируем все частные /24,
  но в порядке «правдоподобности»: адаптер со шлюзом и именем Wi-Fi/Ethernet — первым.
* VPN в режиме TUN может сам «принимать» TCP-соединения на любой адрес — тогда порт 5555
  «открыт» у всех 254 адресов. Поэтому проверяем не просто TCP, а ответ по протоколу ADB
  (CNXN → устройство отвечает CNXN/AUTH/STLS).
* Сначала проверяем адреса из ARP-таблицы (`arp -a`) — телевизор там почти наверняка есть.
"""
from __future__ import annotations

import concurrent.futures as futures
import ipaddress
import re
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

ADB_PORT = 5555
IP_RE = r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"

VIRTUAL_NAME_RE = re.compile(
    r"vethernet|wsl|hyper-?v|virtualbox|vbox|vmware|docker|\btap\b|tap-|\btun\b|wintun|wireguard|happ|"
    r"vpn|tailscale|zerotier|hamachi|radmin|openvpn|sing-?box|clash|v2ray|xray|loopback|bluetooth|npcap",
    re.I)
GOOD_NAME_RE = re.compile(r"wi-?fi|wlan|wireless|ethernet|беспровод|локальн|подключение", re.I)

SKIP_NETS = [ipaddress.IPv4Network(n) for n in (
    "127.0.0.0/8", "169.254.0.0/16",   # loopback, link-local
    "198.18.0.0/15",                    # «фейковые» адреса TUN (sing-box/Happ/Clash)
    "100.64.0.0/10",                    # CGNAT / Tailscale
    "192.168.56.0/24",                  # VirtualBox host-only по умолчанию
)]


@dataclass
class Iface:
    name: str
    ip: str
    up: bool = True
    gateway: bool = False

    @property
    def subnet(self) -> str:
        return str(ipaddress.IPv4Network(self.ip + "/24", strict=False))


def is_candidate_ip(ip: str) -> bool:
    try:
        a = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    if not a.is_private or any(a in n for n in SKIP_NETS):
        return False
    last = int(ip.rsplit(".", 1)[1])
    return 0 < last < 255


def iface_score(i: Iface) -> int:
    s = 0
    if i.gateway:
        s += 4
    if GOOD_NAME_RE.search(i.name or ""):
        s += 2
    if VIRTUAL_NAME_RE.search(i.name or ""):
        s -= 5
    if i.ip.startswith("192.168."):
        s += 1
    elif ipaddress.IPv4Address(i.ip) in ipaddress.IPv4Network("172.16.0.0/12"):
        s -= 2  # Hyper-V / WSL / Docker чаще всего тут
    return s


# ---------------------------------------------------------------- ipconfig / arp

def parse_ipconfig(text: str) -> "list[Iface]":
    """Разбор `ipconfig` (английская и русская Windows). Опирается на порядок строк:
    IPv4 → маска → шлюз (шлюз может быть на следующей строке после IPv6)."""
    res: list = []
    name = ""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line and not line[0].isspace() and line.rstrip().endswith(":"):
            name = line.strip().rstrip(":").strip()
            continue
        if "IPv4" in line and ":" in line:
            m = re.search(IP_RE, line.split(":", 1)[1])
            if not m:
                continue
            gw = False
            # маска — следующая строка, шлюз — через одну (+ возможное продолжение)
            for j in (idx + 2, idx + 3):
                if j >= len(lines):
                    break
                ln = lines[j]
                if j == idx + 3 and " : " in ln:
                    break  # это уже следующий параметр, а не продолжение шлюза
                part = ln.split(" : ", 1)[1] if " : " in ln else ln
                gm = re.search(IP_RE, part)
                if gm and not gm.group(1).startswith("255.") and gm.group(1) != "0.0.0.0":
                    gw = True
                    break
            res.append(Iface(name=name, ip=m.group(1), up=True, gateway=gw))
    return res


def parse_arp(text: str) -> "list[str]":
    res: list = []
    for line in text.splitlines():
        m = re.match(r"^\s*" + IP_RE + r"\s+([0-9a-fA-F]{2}[-:]){5}[0-9a-fA-F]{2}", line)
        if not m:
            continue
        ip = m.group(1)
        mac = line.split()[1].lower().replace(":", "-")
        if mac == "ff-ff-ff-ff-ff-ff" or mac.startswith("01-00-5e"):
            continue
        if is_candidate_ip(ip) and ip not in res:
            res.append(ip)
    return res


def psutil_ifaces() -> "list[Iface]":
    try:
        import psutil  # type: ignore
    except Exception:
        return []
    res: list = []
    try:
        stats = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            up = bool(getattr(stats.get(name), "isup", True))
            for a in addrs:
                if a.family == socket.AF_INET:
                    res.append(Iface(name=name, ip=a.address, up=up))
    except Exception:
        return res
    return res


def merge_ifaces(*lists: "Iterable[Iface]") -> "list[Iface]":
    by_ip: dict = {}
    for lst in lists:
        for i in lst:
            cur = by_ip.get(i.ip)
            if cur is None:
                by_ip[i.ip] = Iface(i.name, i.ip, i.up, i.gateway)
            else:
                cur.gateway = cur.gateway or i.gateway
                cur.up = cur.up and i.up
                if not cur.name and i.name:
                    cur.name = i.name
    return list(by_ip.values())


def rank_subnets(ifaces: "Iterable[Iface]", limit: int = 6) -> "list[tuple[str, Iface]]":
    """Подсети /24 для сканирования, лучшие первыми."""
    cands = [i for i in ifaces if i.up and is_candidate_ip(i.ip)]
    cands.sort(key=lambda i: (-iface_score(i), i.ip))
    seen: set = set()
    res: list = []
    for i in cands:
        if i.subnet not in seen:
            seen.add(i.subnet)
            res.append((i.subnet, i))
    return res[:limit]


def build_host_list(subnets: "list[tuple[str, Iface]]", arp_ips: "list[str]") -> "list[str]":
    """Сначала адреса из ARP (в известных подсетях — первыми), потом остальные адреса подсетей."""
    own = {i.ip for _, i in subnets}
    nets = [ipaddress.IPv4Network(s) for s, _ in subnets]
    in_nets = [ip for ip in arp_ips if any(ipaddress.IPv4Address(ip) in n for n in nets)]
    out_nets = [ip for ip in arp_ips if ip not in in_nets]
    hosts: list = []
    seen: set = set(own)
    for ip in in_nets + out_nets:
        if ip not in seen:
            seen.add(ip)
            hosts.append(ip)
    for n in nets:
        for h in n.hosts():
            s = str(h)
            if s not in seen:
                seen.add(s)
                hosts.append(s)
    return hosts


# ---------------------------------------------------------------- проверка ADB

A_CNXN = 0x4E584E43
A_AUTH = 0x48545541
A_STLS = 0x534C5453
ADB_REPLIES = {A_CNXN, A_AUTH, A_STLS}


def adb_cnxn_packet() -> bytes:
    payload = b"host::\x00"
    return struct.pack("<6I", A_CNXN, 0x01000001, 256 * 1024, len(payload),
                       sum(payload) & 0xFFFFFFFF, A_CNXN ^ 0xFFFFFFFF) + payload


def is_adb_reply(header: bytes) -> bool:
    if len(header) < 24:
        return False
    cmd, _a0, _a1, _ln, _crc, magic = struct.unpack("<6I", header[:24])
    return cmd in ADB_REPLIES and magic == cmd ^ 0xFFFFFFFF


def adb_probe(ip: str, port: int = ADB_PORT, timeout: float = 0.6, read_timeout: float = 1.0) -> bool:
    """True, если на ip:port отвечает именно adbd (а не VPN/TUN, принимающий всё подряд)."""
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            s.settimeout(read_timeout)
            s.sendall(adb_cnxn_packet())
            buf = b""
            while len(buf) < 24:
                chunk = s.recv(24 - len(buf))
                if not chunk:
                    break
                buf += chunk
            return is_adb_reply(buf)
    except OSError:
        return False


def scan(hosts: "list[str]", probe: Callable[[str], bool], workers: int = 96,
         cancel: Optional[threading.Event] = None, deadline: Optional[float] = None,
         clock: Callable[[], float] = time.monotonic,
         on_open: Callable[[str], None] = lambda ip: None,
         progress: Callable[[int, int], None] = lambda done, total: None) -> "list[str]":
    """Параллельная проверка; останавливается по cancel или deadline (абсолютное время clock())."""
    found: list = []
    total = len(hosts)
    done = 0
    ex = futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 128)))
    try:
        futs = {ex.submit(probe, h): h for h in hosts}
        pending = set(futs)
        while pending:
            if cancel is not None and cancel.is_set():
                break
            if deadline is not None and clock() >= deadline:
                break
            fin, pending = futures.wait(pending, timeout=0.2, return_when=futures.FIRST_COMPLETED)
            for f in fin:
                done += 1
                try:
                    ok = f.result()
                except Exception:
                    ok = False
                if ok:
                    found.append(futs[f])
                    on_open(futs[f])
            if fin:
                progress(done, total)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return found

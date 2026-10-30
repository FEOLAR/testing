"""Выбор подсетей и проверка ADB: фейковые ipconfig/arp (Hyper-V, VPN TUN, VirtualBox) и локальные сокеты."""
import socket
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from whitehole_setup import netscan  # noqa: E402
from whitehole_setup.netscan import Iface  # noqa: E402

IPCONFIG_RU = """
Настройка протокола IP для Windows


Адаптер Ethernet vEthernet (Default Switch):

   DNS-суффикс подключения . . . . . :
   Локальный IPv6-адрес канала . . . : fe80::a1b2:c3d4:e5f6:1%23
   IPv4-адрес. . . . . . . . . . . . : 172.29.208.1
   Маска подсети . . . . . . . . . . : 255.255.240.0
   Основной шлюз. . . . . . . . . :

Неизвестный адаптер Happ:

   DNS-суффикс подключения . . . . . :
   IPv4-адрес. . . . . . . . . . . . : 172.19.0.1
   Маска подсети . . . . . . . . . . : 255.255.255.252
   Основной шлюз. . . . . . . . . : 0.0.0.0

Неизвестный адаптер WireGuard VPN:

   IPv4-адрес. . . . . . . . . . . . : 10.66.66.2
   Маска подсети . . . . . . . . . . : 255.255.255.255
   Основной шлюз. . . . . . . . . : 10.66.66.1

Адаптер Ethernet VirtualBox Host-Only Network:

   IPv4-адрес. . . . . . . . . . . . : 192.168.56.1
   Маска подсети . . . . . . . . . . : 255.255.255.0
   Основной шлюз. . . . . . . . . :

Адаптер беспроводной локальной сети Беспроводная сеть:

   DNS-суффикс подключения . . . . . : lan
   Локальный IPv6-адрес канала . . . : fe80::1234:5678:9abc:def0%12
   IPv4-адрес. . . . . . . . . . . . : 192.168.3.5(Основной)
   Маска подсети . . . . . . . . . . : 255.255.255.0
   Основной шлюз. . . . . . . . . : fe80::1%12
                                       192.168.3.1

Адаптер Ethernet Ethernet:

   Состояние среды. . . . . . . . : Среда передачи недоступна.
"""

IPCONFIG_EN = """
Windows IP Configuration

Ethernet adapter Ethernet:

   Connection-specific DNS Suffix  . : home
   IPv4 Address. . . . . . . . . . . : 10.0.0.23
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : 10.0.0.1

Ethernet adapter vEthernet (WSL):

   IPv4 Address. . . . . . . . . . . : 172.17.96.1
   Subnet Mask . . . . . . . . . . . : 255.255.240.0
   Default Gateway . . . . . . . . . :
"""

ARP_RU = """
Интерфейс: 192.168.3.5 --- 0xc
  адрес в Интернете      Физический адрес      Тип
  192.168.3.1           a0-b1-c2-d3-e4-f5     динамический
  192.168.3.19          10-20-30-40-50-60     динамический
  192.168.3.255         ff-ff-ff-ff-ff-ff     статический
  224.0.0.22            01-00-5e-00-00-16     статический
  239.255.255.250       01-00-5e-7f-ff-fa     статический

Интерфейс: 172.29.208.1 --- 0x17
  172.29.223.255        ff-ff-ff-ff-ff-ff     статический
"""


def test_parse_ipconfig_ru():
    ifs = {i.ip: i for i in netscan.parse_ipconfig(IPCONFIG_RU)}
    assert set(ifs) == {"172.29.208.1", "172.19.0.1", "10.66.66.2", "192.168.56.1", "192.168.3.5"}
    assert ifs["192.168.3.5"].gateway is True
    assert ifs["192.168.3.5"].name.startswith("Адаптер беспроводной")
    assert ifs["172.29.208.1"].gateway is False
    assert ifs["172.19.0.1"].gateway is False      # 0.0.0.0 — не шлюз
    assert ifs["10.66.66.2"].gateway is True


def test_rank_prefers_wifi_over_hyperv_and_vpn():
    subnets = netscan.rank_subnets(netscan.parse_ipconfig(IPCONFIG_RU))
    nets = [s for s, _ in subnets]
    assert nets[0] == "192.168.3.0/24"
    assert "192.168.56.0/24" not in nets            # VirtualBox host-only пропускаем
    # виртуальные/VPN всё равно сканируются, но после настоящей сети
    assert set(nets[1:]) == {"172.29.208.0/24", "172.19.0.0/24", "10.66.66.0/24"}


def test_rank_english_ipconfig():
    nets = [s for s, _ in netscan.rank_subnets(netscan.parse_ipconfig(IPCONFIG_EN))]
    assert nets == ["10.0.0.0/24", "172.17.96.0/24"]


def test_tun_and_cgnat_skipped():
    ifs = [Iface("Happ TUN", "198.18.0.1", True, True), Iface("Tailscale", "100.101.1.2", True, False),
           Iface("Loopback", "127.0.0.1"), Iface("x", "169.254.10.1"), Iface("Wi-Fi", "192.168.1.10", False, True)]
    assert netscan.rank_subnets(ifs) == []  # Wi-Fi выключен, остальное — не локальная сеть


def test_merge_psutil_names_with_ipconfig_gateway():
    ps = [Iface("Wi-Fi", "192.168.3.5", True, False), Iface("vEthernet (WSL)", "172.29.208.1", True, False)]
    merged = netscan.merge_ifaces(ps, netscan.parse_ipconfig(IPCONFIG_RU))
    wifi = next(i for i in merged if i.ip == "192.168.3.5")
    assert wifi.name == "Wi-Fi" and wifi.gateway


def test_parse_arp():
    assert netscan.parse_arp(ARP_RU) == ["192.168.3.1", "192.168.3.19"]


def test_host_list_arp_first():
    subnets = netscan.rank_subnets(netscan.parse_ipconfig(IPCONFIG_RU))
    hosts = netscan.build_host_list(subnets, netscan.parse_arp(ARP_RU))
    assert hosts[:2] == ["192.168.3.1", "192.168.3.19"]
    assert "192.168.3.5" not in hosts                  # свой адрес не проверяем
    assert len(hosts) == len(set(hosts))
    assert hosts.index("192.168.3.20") < hosts.index("172.29.208.20")


# ---------------------------------------------------------------- ADB-проба на локальных сокетах

def _server(handler):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def loop():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                c, _ = srv.accept()
            except OSError:
                continue
            threading.Thread(target=handler, args=(c,), daemon=True).start()
        srv.close()
    threading.Thread(target=loop, daemon=True).start()
    return port, stop


def fake_adbd(conn):
    with conn:
        data = conn.recv(64)
        assert struct.unpack("<I", data[:4])[0] == netscan.A_CNXN
        conn.sendall(struct.pack("<6I", netscan.A_AUTH, 1, 0, 20, 0, netscan.A_AUTH ^ 0xFFFFFFFF))


def fake_tun(conn):  # принимает TCP, но молчит (как VPN в режиме TUN)
    time.sleep(2)
    conn.close()


def fake_http(conn):
    with conn:
        conn.recv(64)
        conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")


def test_adb_probe_distinguishes_adbd_from_tun():
    p1, s1 = _server(fake_adbd)
    p2, s2 = _server(fake_tun)
    p3, s3 = _server(fake_http)
    try:
        assert netscan.adb_probe("127.0.0.1", p1, 0.5, 0.8) is True
        t = time.monotonic()
        assert netscan.adb_probe("127.0.0.1", p2, 0.5, 0.5) is False
        assert time.monotonic() - t < 1.5
        assert netscan.adb_probe("127.0.0.1", p3, 0.5, 0.8) is False
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        closed.close()
        assert netscan.adb_probe("127.0.0.1", port, 0.5, 0.5) is False
    finally:
        s1.set(), s2.set(), s3.set()


def test_scan_deadline_and_cancel():
    hosts = [f"10.0.0.{i}" for i in range(1, 200)]
    t = time.monotonic()
    found = netscan.scan(hosts, lambda ip: time.sleep(0.3) or ip == "10.0.0.5", workers=8,
                         deadline=time.monotonic() + 0.8)
    assert time.monotonic() - t < 2.0  # не ждём все 199×0.3/8 ≈ 7.5 с
    cancel = threading.Event()
    cancel.set()
    assert netscan.scan(hosts, lambda ip: True, cancel=cancel) == []


def test_scan_survives_probe_exceptions():
    def probe(ip):
        if ip.endswith(".3"):
            raise RuntimeError("boom")
        return ip.endswith(".7")
    found = []
    assert netscan.scan([f"10.0.0.{i}" for i in range(1, 10)], probe, on_open=found.append) == ["10.0.0.7"]
    assert found == ["10.0.0.7"]

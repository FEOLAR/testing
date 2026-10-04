#!/bin/bash
# GalacticVPN: настроить мост на несколько нод сразу.
#   bash bridge-nodes.sh 151.243.225.123 1.2.3.4 ...
# VPN (443/8443): HAProxy раскидывает клиентов по нодам (один клиент — всегда одна нода)
#                 и сам убирает упавшую ноду.
# Подписка (9443): Caddy ходит на sub-proxy первой живой ноды, при сбое — на следующую.
set -e
[ $# -ge 1 ] || { echo "Укажите IP нод: bash bridge-nodes.sh IP1 IP2 ..."; exit 1; }
BRIDGE_DOMAIN=77-91-95-53.sslip.io

echo "== Проверка нод из РФ (TLS на 443)..."
for ip in "$@"; do
    t=$(curl -sk -m 8 -o /dev/null -w "%{http_code}" --resolve originfi.dattebayo.space:443:$ip https://originfi.dattebayo.space/ || true)
    [ "$t" = "000" ] && echo "⚠️  $ip: TLS из РФ НЕ проходит — эту ноду лучше не добавлять" || echo "✅ $ip: OK"
done
read -r -p "Продолжить? (y/n) " ok; [ "$ok" = "y" ] || exit 0

export DEBIAN_FRONTEND=noninteractive
command -v haproxy >/dev/null || apt-get install -y -qq haproxy >/dev/null
cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$(date +%s)
[ -f /etc/haproxy/haproxy.cfg ] && cp /etc/haproxy/haproxy.cfg /etc/haproxy/haproxy.cfg.bak.$(date +%s)

S443=""; S8443=""; UP=""; n=1
for ip in "$@"; do
    S443="$S443    server n$n $ip:443 check inter 10s fall 3 rise 2
"
    S8443="$S8443    server n$n $ip:8443 check inter 10s fall 3 rise 2
"
    UP="$UP https://$(echo $ip | tr . -).sslip.io:9443"
    n=$((n+1))
done

cat >/etc/haproxy/haproxy.cfg <<EOF
global
    maxconn 100000
defaults
    mode tcp
    timeout connect 5s
    timeout client  1h
    timeout server  1h
frontend vpn443
    bind :443
    default_backend nodes443
frontend vpn8443
    bind :8443
    default_backend nodes8443
backend nodes443
    balance source
    hash-type consistent
$S443
backend nodes8443
    balance source
    hash-type consistent
$S8443
EOF
haproxy -c -f /etc/haproxy/haproxy.cfg >/dev/null

cat >/etc/caddy/Caddyfile <<EOF
{
    https_port 9443
}
$BRIDGE_DOMAIN {
    encode gzip
    @allowed path /api/sub/* /geo/* /miniapp /miniapp/*
    handle @allowed {
        reverse_proxy$UP {
            header_up Host {upstream_hostport}
            lb_policy first
            lb_try_duration 5s
            fail_duration 30s
        }
    }
    handle {
        respond "Not found" 404
    }
}
EOF
caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1

echo "== Убираю старую пересылку iptables 443/8443 и включаю HAProxy..."
iptables -t nat -S PREROUTING | grep -E -- '--dport (443|8443) .*DNAT' | sed 's/^-A/-D/' | while read -r r; do iptables -t nat $r; done
systemctl enable haproxy >/dev/null 2>&1; systemctl restart haproxy
systemctl restart caddy
netfilter-persistent save >/dev/null 2>&1 || true
sleep 5

echo
echo "================ ИТОГ ================"
systemctl is-active --quiet haproxy && echo "✅ HAProxy работает" || echo "⚠️  HAProxy не запустился: journalctl -u haproxy -n 20"
CODE=$(curl -sk -m 15 -o /dev/null -w "%{http_code}" https://$BRIDGE_DOMAIN:9443/miniapp/)
[ "$CODE" = "200" ] && echo "✅ Подписка через мост: 200" || echo "⚠️  Подписка через мост: $CODE"
echo "Откат: cp /etc/caddy/Caddyfile.bak.* и /etc/haproxy/haproxy.cfg.bak.* обратно, systemctl stop haproxy,"
echo "       вернуть DNAT: iptables -t nat -A PREROUTING -p tcp --dport 443 -j DNAT --to-destination IP:443 (и 8443)"

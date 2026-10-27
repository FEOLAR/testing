#!/bin/bash
# WhiteHoleVPN: настроить мост (подходит для любого моста — адрес определяется сам) на несколько нод сразу.
#   bash bridge-nodes.sh 151.243.225.123 1.2.3.4 ...
# VPN (443/8443): HAProxy раскидывает клиентов по нодам (один клиент — всегда одна нода)
#                 и сам убирает упавшую ноду.
# Подписка (9443): Caddy ходит на sub-proxy первой живой ноды, при сбое — на следующую.
# Проверка нод — настоящим TLS-рукопожатием (как у клиента), поэтому нода с заблокированным в РФ IP
# тоже считается упавшей. Статистика проверок (порт 8404, только для сервера с ботом) — бот по ней
# понимает, какие ноды не работают из России, и убирает их из подписки.
#
# Белые списки мобильного интернета (WL_SNI=домен из белого списка):
#   WL_SNI=yastatic.net bash bridge-nodes.sh IP1 IP2 ...
# На том же порту 443 HAProxy смотрит SNI: клиенты с WL_SNI уходят на вход нод WL_REALITY (порт WL_PORT,
# по умолчанию 4443), все остальные — как раньше. Нужен мост с «белым» IP (например, Яндекс Облако).
set -e
PANEL_IP=146.0.76.110
SNI=originfi.dattebayo.space
WL_SNI=${WL_SNI:-}
WL_PORT=${WL_PORT:-4443}
[ $# -ge 1 ] || { echo "Укажите IP нод: bash bridge-nodes.sh IP1 IP2 ..."; exit 1; }
MYIP=$(curl -4 -s -m 10 https://api.ipify.org || hostname -I | awk '{print $1}')
BRIDGE_DOMAIN=$(echo "$MYIP" | tr . -).sslip.io
echo "== Мост: $MYIP ($BRIDGE_DOMAIN)"

echo "== Проверка нод из РФ (TLS на 443)..."
for ip in "$@"; do
    t=$(curl -sk -m 8 -o /dev/null -w "%{http_code}" --resolve originfi.dattebayo.space:443:$ip https://originfi.dattebayo.space/ || true)
    [ "$t" = "000" ] && echo "⚠️  $ip: TLS из РФ НЕ проходит — эту ноду лучше не добавлять" || echo "✅ $ip: OK"
done
if [ -n "$WL_SNI" ]; then
    echo "== Белые списки: проверка входа WL_REALITY ($WL_PORT, SNI $WL_SNI)..."
    for ip in "$@"; do
        t=$(curl -sk -m 8 -o /dev/null -w "%{http_code}" --resolve $WL_SNI:$WL_PORT:$ip https://$WL_SNI:$WL_PORT/ || true)
        [ "$t" = "000" ] && echo "⚠️  $ip:$WL_PORT не отвечает — в Config Profile нет входа WL_REALITY или на ноде закрыт порт $WL_PORT" \
                         || echo "✅ $ip:$WL_PORT OK"
    done
fi
read -r -p "Продолжить? (y/n) " ok; [ "$ok" = "y" ] || exit 0

export DEBIAN_FRONTEND=noninteractive
if ! command -v haproxy >/dev/null || ! command -v caddy >/dev/null; then
    echo "== Ставлю HAProxy и Caddy..."
    apt-get update -qq >/dev/null
    apt-get install -y -qq haproxy caddy >/dev/null
fi
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow 443/tcp >/dev/null; ufw allow 8443/tcp >/dev/null; ufw allow 9443/tcp >/dev/null; ufw allow 80/tcp >/dev/null
    ufw allow from $PANEL_IP to any port 8404 proto tcp >/dev/null
fi
mkdir -p /etc/caddy
[ -f /etc/caddy/Caddyfile ] && cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.$(date +%s)
[ -f /etc/haproxy/haproxy.cfg ] && cp /etc/haproxy/haproxy.cfg /etc/haproxy/haproxy.cfg.bak.$(date +%s)

S443=""; S8443=""; SWL=""; UP=""
CHK="check check-ssl verify none check-sni $SNI inter 10s fall 3 rise 2"
for ip in "$@"; do
    S443="$S443    server $ip $ip:443 $CHK
"
    S8443="$S8443    server $ip $ip:8443 $CHK
"
    SWL="$SWL    server $ip $ip:$WL_PORT check check-ssl verify none check-sni $WL_SNI inter 10s fall 3 rise 2
"
    UP="$UP https://$(echo $ip | tr . -).sslip.io:9443"
done

WL_FRONT=""; WL_BACK=""
if [ -n "$WL_SNI" ]; then
    WL_FRONT="    tcp-request inspect-delay 3s
    tcp-request content accept if { req_ssl_hello_type 1 }
    use_backend wl443 if { req.ssl_sni -i $WL_SNI }"
    WL_BACK="backend wl443
    balance source
    hash-type consistent
$SWL"
fi
cat >/etc/haproxy/haproxy.cfg <<EOF
global
    maxconn 100000
defaults
    mode tcp
    timeout connect 5s
    timeout client  1h
    timeout server  1h
frontend stats
    mode http
    bind :8404
    timeout client 30s
    acl panel src $PANEL_IP 127.0.0.1
    http-request deny if !panel
    stats enable
    stats uri /stats
frontend vpn443
    bind :443
$WL_FRONT
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
$WL_BACK
EOF
haproxy -c -f /etc/haproxy/haproxy.cfg >/dev/null 2>&1 || { haproxy -c -f /etc/haproxy/haproxy.cfg; echo "!! Ошибка в конфиге HAProxy, ничего не меняю"; exit 1; }

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
systemctl enable caddy >/dev/null 2>&1; systemctl restart caddy
netfilter-persistent save >/dev/null 2>&1 || true
sleep 5

echo
echo "================ ИТОГ ================"
systemctl is-active --quiet haproxy && echo "✅ HAProxy работает" || echo "⚠️  HAProxy не запустился: journalctl -u haproxy -n 20"
sleep 30
echo "Ноды по проверке HAProxy (UP — работает, DOWN — не отвечает из РФ):"
curl -s -m 5 "http://127.0.0.1:8404/stats;csv" | awk -F, '$1=="nodes443" && $2!="BACKEND" {print "   " $2 ": " $18}'
if [ -n "$WL_SNI" ]; then
    echo "Белые списки (вход WL_REALITY :$WL_PORT):"
    curl -s -m 5 "http://127.0.0.1:8404/stats;csv" | awk -F, '$1=="wl443" && $2!="BACKEND" {print "   " $2 ": " $18}'
    echo "Хост в панели: адрес $MYIP, порт 443, вход WL_REALITY, SNI $WL_SNI (без тега AUTO)"
fi
CODE=$(curl -sk -m 15 -o /dev/null -w "%{http_code}" https://$BRIDGE_DOMAIN:9443/miniapp/)
[ "$CODE" = "200" ] && echo "✅ Подписка через мост: 200" || echo "⚠️  Подписка через мост: $CODE"
echo "Откат: cp /etc/caddy/Caddyfile.bak.* и /etc/haproxy/haproxy.cfg.bak.* обратно, systemctl stop haproxy,"
echo "       вернуть DNAT: iptables -t nat -A PREROUTING -p tcp --dport 443 -j DNAT --to-destination IP:443 (и 8443)"

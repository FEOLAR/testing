#!/bin/bash
# WhiteHoleVPN: «белый мост» — для мобильного интернета с «белыми списками».
#   bash wl-bridge.sh 151.243.225.123 151.243.198.253 109.66.233.129 31.57.44.100
# Ставится на российский VPS, чей IP проходит через белые списки (проверено с телефона клиента).
# Клиент подключается к мосту на 443 с SNI разрешённого сайта (yastatic.net) — так его пропускает оператор.
# Мост пересылает соединение на ноды, на их вход WL_REALITY (порт 4443, SNI yastatic.net).
# Один клиент — всегда одна нода; упавшую ноду мост убирает сам (проверка TLS каждые 10 с).
set -e
[ $# -ge 1 ] || { echo "Укажите IP нод: bash wl-bridge.sh IP1 IP2 ..."; exit 1; }
PANEL_IP=146.0.76.110
SNI=${SNI:-yastatic.net}
NODE_PORT=${NODE_PORT:-4443}
MYIP=$(curl -4 -s -m 10 https://api.ipify.org || hostname -I | awk '{print $1}')
echo "== Белый мост: $MYIP, SNI $SNI, порт нод $NODE_PORT"

echo "== Проверка нод с этого моста (TLS на $NODE_PORT с SNI $SNI)..."
for ip in "$@"; do
    t=$(curl -sk -m 8 -o /dev/null -w "%{http_code}" --resolve $SNI:$NODE_PORT:$ip https://$SNI:$NODE_PORT/ || true)
    [ "$t" = "000" ] && echo "⚠️  $ip:$NODE_PORT не отвечает — проверь, что в Config Profile есть вход WL_REALITY и на ноде открыт порт $NODE_PORT" || echo "✅ $ip: OK ($t)"
done
read -r -p "Продолжить? (y/n) " ok; [ "$ok" = "y" ] || exit 0

export DEBIAN_FRONTEND=noninteractive
command -v haproxy >/dev/null || { apt-get update -qq >/dev/null; apt-get install -y -qq haproxy >/dev/null; }
if command -v ufw >/dev/null; then
    ufw allow 22/tcp >/dev/null; ufw allow 443/tcp >/dev/null
    ufw allow from $PANEL_IP to any port 8404 proto tcp >/dev/null
    ufw --force enable >/dev/null
fi
[ -f /etc/haproxy/haproxy.cfg ] && cp /etc/haproxy/haproxy.cfg /etc/haproxy/haproxy.cfg.bak.$(date +%s)

SRV=""
CHK="check check-ssl verify none check-sni $SNI inter 10s fall 3 rise 2"
for ip in "$@"; do
    SRV="$SRV    server $ip $ip:$NODE_PORT $CHK
"
done

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
frontend wl443
    bind :443
    default_backend nodes443
backend nodes443
    balance source
    hash-type consistent
$SRV
EOF
haproxy -c -f /etc/haproxy/haproxy.cfg >/dev/null 2>&1 || { haproxy -c -f /etc/haproxy/haproxy.cfg; echo "!! Ошибка в конфиге HAProxy"; exit 1; }

cat >/etc/sysctl.d/99-vpn.conf <<'EOF'
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.core.somaxconn=8192
net.ipv4.tcp_max_syn_backlog=8192
net.ipv4.ip_local_port_range=10000 65000
fs.file-max=1000000
EOF
sysctl --system >/dev/null

systemctl enable haproxy >/dev/null 2>&1; systemctl restart haproxy
sleep 30
echo
echo "================ ИТОГ ================"
systemctl is-active --quiet haproxy && echo "✅ HAProxy работает" || echo "⚠️  HAProxy не запустился: journalctl -u haproxy -n 20"
echo "Ноды (UP — работает):"
curl -s -m 5 "http://127.0.0.1:8404/stats;csv" | awk -F, '$1=="nodes443" && $2!="BACKEND" {print "   " $2 ": " $18}'
echo "Хост в панели: адрес $MYIP, порт 443, вход WL_REALITY, SNI $SNI"

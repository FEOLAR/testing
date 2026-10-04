#!/bin/bash
# GalacticVPN: установка ноды Remnawave + sub-proxy (зеркало подписки) на чистый Ubuntu.
#   bash add-node.sh test  — 3 минуты держит тестовый TLS на :8443 (проверка IP с моста)
#   bash add-node.sh       — полная установка (сначала создайте ноду в панели и скопируйте SECRET_KEY)
PANEL_IP=146.0.76.110
PANEL_DOMAIN=146-0-76-110.sslip.io
NODE_PORT=2222

IP=$(curl -4 -s -m 5 https://ifconfig.me || hostname -I | awk '{print $1}')
DASH=$(echo "$IP" | tr . -)

if [ "$1" = "test" ]; then
    command -v ufw >/dev/null && ufw allow 8443/tcp >/dev/null 2>&1
    openssl req -x509 -newkey rsa:2048 -nodes -keyout /tmp/k -out /tmp/c -days 1 -subj /CN=test 2>/dev/null
    echo "== Тестовый TLS запущен на $IP:8443 на 3 минуты. На МОСТУ выполните:"
    echo "curl -sk -m 8 -o /dev/null -w \"TLS из РФ: %{http_code} за %{time_total}s\\n\" https://$IP:8443/"
    timeout 180 openssl s_server -accept 8443 -cert /tmp/c -key /tmp/k -www -quiet
    exit 0
fi

echo "== IP сервера: $IP"
read -r -p "Имя сервера (например fi-4): " NAME
[ -n "$NAME" ] && hostnamectl set-hostname "$NAME"
read -r -p "Вставьте SECRET_KEY из панели и нажмите Enter: " KEY
KEY=$(printf '%s' "$KEY" | sed 's/^.*SECRET_KEY=//' | tr -d '"'"'"' \r\n')
if ! printf '%s' "$KEY" | base64 -d 2>/dev/null | head -c 2 | grep -q '{"'; then
    echo "!! Ключ неполный или с ошибкой (длина ${#KEY}). Запустите скрипт заново."; exit 1
fi

echo "== Пакеты и Docker..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq -o Dpkg::Options::=--force-confold vnstat ufw curl >/dev/null
systemctl enable --now vnstat >/dev/null 2>&1
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh >/dev/null

cat >/etc/sysctl.d/99-vpn.conf <<'EOF'
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.core.somaxconn=8192
net.ipv4.tcp_max_syn_backlog=8192
net.ipv4.ip_local_port_range=10000 65000
fs.file-max=1000000
EOF
sysctl --system >/dev/null

echo "== Нода..."
mkdir -p /opt/remnanode
cat >/opt/remnanode/docker-compose.yml <<EOF
services:
  remnanode:
    container_name: remnanode
    hostname: remnanode
    image: remnawave/node:latest
    network_mode: host
    restart: always
    environment:
      - NODE_PORT=$NODE_PORT
      - SECRET_KEY=$KEY
EOF

echo "== Sub-proxy (зеркало подписки для моста)..."
mkdir -p /opt/sub-proxy
cat >/opt/sub-proxy/Caddyfile <<EOF
{
    https_port 9443
}
$DASH.sslip.io {
    encode gzip
    @allowed path /api/sub/* /geo/* /miniapp /miniapp/*
    handle @allowed {
        reverse_proxy https://$PANEL_DOMAIN {
            header_up Host {upstream_hostport}
        }
    }
    handle {
        respond "Not found" 404
    }
}
EOF
cat >/opt/sub-proxy/docker-compose.yml <<'EOF'
services:
  caddy:
    image: caddy:2
    container_name: sub-proxy
    restart: always
    network_mode: host
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - ./data:/data
EOF

echo "== Firewall..."
for p in 22 80 443 8443 9443; do ufw allow $p/tcp >/dev/null; done
ufw allow from $PANEL_IP to any port $NODE_PORT proto tcp >/dev/null
ufw --force enable >/dev/null

(cd /opt/remnanode && docker compose up -d)
(cd /opt/sub-proxy && docker compose up -d)
echo "== Ждём запуска (30 с)..."
sleep 30

echo
echo "================ ИТОГ ================"
docker logs remnanode 2>&1 | grep -q "is up and running" && echo "✅ Нода: Xray запущен" || echo "⚠️  Нода: Xray ещё не запущен — проверьте, что нода создана в панели с адресом $IP"
ss -ltn | grep -qE ':443 ' && echo "✅ Порт 443 слушается" || echo "⚠️  Порт 443 не слушается"
CODE=$(curl -sk -m 10 -o /dev/null -w "%{http_code}" https://$DASH.sslip.io:9443/miniapp/)
[ "$CODE" = "200" ] && echo "✅ Sub-proxy: 200" || echo "⚠️  Sub-proxy: $CODE (сертификат может получаться ещё минуту)"
echo "Адрес sub-proxy для моста: https://$DASH.sslip.io:9443"

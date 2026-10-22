#!/bin/bash
# WhiteHoleVPN: сервер-выход только для YouTube (чтобы YouTube видел зрителя из России и не показывал рекламу).
#   bash yt-exit.sh
# Ставит Xray с Shadowsocks-2022 на порт 8388, пускает к нему только ноды FR-1 и GE-1,
# в конце печатает блок для Config Profile в панели Remnawave.
set -e
NODES="151.243.225.123 151.243.198.253 109.66.233.129 31.57.44.100"   # все ноды — только им разрешено подключаться
PORT=8388

echo "== Проверка: кем этот сервер считает YouTube..."
GL=$(curl -s -A "Mozilla/5.0" -m 15 https://www.youtube.com/ | grep -o '"GL":"[A-Z]*"' | head -1 || true)
echo "   ${GL:-YouTube недоступен}"
if [ "$GL" != '"GL":"RU"' ]; then
    read -r -p "YouTube не считает сервер российским — реклама останется. Всё равно ставить? (y/n) " ok
    [ "$ok" = "y" ] || exit 0
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null
apt-get install -y -qq curl unzip openssl ufw >/dev/null

echo "== Ставлю Xray..."
bash -c "$(curl -sL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install >/dev/null

KEY=$(openssl rand -base64 16)
cat >/usr/local/etc/xray/config.json <<EOF
{
  "log": { "loglevel": "warning" },
  "inbounds": [
    {
      "tag": "from-nodes",
      "port": $PORT,
      "protocol": "shadowsocks",
      "settings": { "method": "2022-blake3-aes-128-gcm", "password": "$KEY", "network": "tcp,udp" }
    }
  ],
  "outbounds": [ { "tag": "direct", "protocol": "freedom" } ]
}
EOF
systemctl enable xray >/dev/null 2>&1
systemctl restart xray
sleep 2

echo "== Файрвол: SSH для всех, порт $PORT только для нод..."
ufw allow 22/tcp >/dev/null
for ip in $NODES; do
    ufw allow from "$ip" to any port $PORT proto tcp >/dev/null
    ufw allow from "$ip" to any port $PORT proto udp >/dev/null
done
ufw --force enable >/dev/null

MYIP=$(curl -4 -s -m 10 https://api.ipify.org || hostname -I | awk '{print $1}')
echo
echo "================ ИТОГ ================"
systemctl is-active --quiet xray && echo "✅ Xray работает" || echo "⚠️  Xray не запустился: journalctl -u xray -n 20"
echo "Пришли Claude эти две строки (это не пароль от сервера, а ключ связи нод с этим сервером):"
echo "YT_EXIT_IP=$MYIP"
echo "YT_EXIT_KEY=$KEY"

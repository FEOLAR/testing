#!/bin/bash
# WhiteHoleVPN: быстрая проверка IP по публичным «белым спискам» (без участия клиента).
#   bash wl-check.sh              — проверить IP этого сервера
#   bash wl-check.sh 1.2.3.4 ...  — проверить любые адреса
# Источник: github.com/hxehex/russia-mobile-internet-whitelist (собирают сканированием во время ограничений).
# ✅ — подсеть есть в списке: стоит дать клиенту проверить (/wlcheck в боте).
# ❌ — подсети в списке нет: почти наверняка не пройдёт, сервер сразу удаляй и бери другой IP.
URL=https://raw.githubusercontent.com/hxehex/russia-mobile-internet-whitelist/main/cidrwhitelist.txt
LIST=/tmp/wl-cidr.txt
[ -s $LIST ] && [ $(( $(date +%s) - $(stat -c %Y $LIST) )) -lt 86400 ] || curl -s -m 30 -o $LIST $URL
[ -s $LIST ] || { echo "Не скачался список: $URL"; exit 1; }
IPS="$*"
[ -n "$IPS" ] || IPS=$(curl -4 -s -m 10 https://api.ipify.org || hostname -I | awk '{print $1}')
python3 - "$LIST" $IPS <<'EOF'
import ipaddress, sys
nets = []
for line in open(sys.argv[1]):
    line = line.strip()
    if line and not line.startswith("#") and ":" not in line:
        try:
            nets.append(ipaddress.ip_network(line, strict=False))
        except ValueError:
            pass
for ip in sys.argv[2:]:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        print(f"?  {ip} — не IP"); continue
    hit = [n for n in nets if a in n]
    if hit:
        print(f"✅ {ip} — в белом списке (подсеть {min(hit, key=lambda n: n.num_addresses)}). Дай клиенту проверить.")
    else:
        print(f"❌ {ip} — подсети нет в белом списке. Скорее всего не пройдёт — бери другой IP.")
EOF

#!/usr/bin/env bash
# Зависимости встроенного VPN для сборки (запускать из папки tv-launcher/, вызывается в CI).
#  1) libv2ray.aar — AndroidLibXrayLite (ядро Xray для Android, как в v2rayNG), версия и sha256 закреплены.
#     Из AAR удаляются встроенные полные geoip/geosite (~27 МБ) и x86-библиотеки — они нам не нужны.
#  2) Компактные geoip.dat (только RU) и geosite.dat с сервера WhiteHole → app/vpn-assets/.
#     Если сервер недоступен — сборка продолжается, приложение скачает geoip.dat при первом подключении.
set -euo pipefail

LIBV2RAY_VERSION="v26.10.17"
LIBV2RAY_SHA256="fd6cb61fed873e465c3064327dffbcb22dc3fd78260d162ec9e868db2582495f"
GEO_BASE="https://77-91-95-53.sslip.io:9443/miniapp"

cd "$(dirname "$0")/.."
mkdir -p app/libs app/vpn-assets
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "libv2ray ${LIBV2RAY_VERSION}"
curl -fsSL --retry 3 --retry-delay 5 -o "$tmp/libv2ray.aar" \
  "https://github.com/2dust/AndroidLibXrayLite/releases/download/${LIBV2RAY_VERSION}/libv2ray.aar"
echo "${LIBV2RAY_SHA256}  $tmp/libv2ray.aar" | sha256sum -c -
cp "$tmp/libv2ray.aar" app/libs/libv2ray.aar
# убрать из AAR полные гео-базы и x86 (zip -d возвращает 12, если чего-то нет — это не ошибка)
zip -q -d app/libs/libv2ray.aar 'assets/*' 'jni/x86/*' 'jni/x86_64/*' || [ $? -eq 12 ]
unzip -l app/libs/libv2ray.aar | tail -n +1

for f in geoip geosite; do
  if curl -fsSL --retry 2 --connect-timeout 15 --max-time 60 -o "$tmp/$f.dat" "$GEO_BASE/$f.dat" \
     && [ "$(stat -c %s "$tmp/$f.dat")" -gt 100 ]; then
    cp "$tmp/$f.dat" "app/vpn-assets/$f.dat"
    echo "$f.dat: $(stat -c %s "app/vpn-assets/$f.dat") bytes (sha256 $(sha256sum "app/vpn-assets/$f.dat" | cut -c1-16)…)"
  else
    echo "::warning title=geo::$f.dat не скачан с $GEO_BASE — приложение скачает его при первом подключении"
  fi
done

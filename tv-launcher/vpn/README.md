# Встроенный VPN лаунчера WhiteHole

Цель: кнопка «Подключить» на главной сама включает VPN, без перехода в Happ.

## Решение

### Вариант A — управлять Happ (отклонён, Happ остаётся запасным)

В документации Happ для разработчиков нет команд «подключить / отключить / переключить»
(ни deeplink, ни intent, ни broadcast):

- [Android TV API](https://www.happ.su/main/dev-docs/android-tv-api.md) — только отправка подписки на ТВ по коду (`check.happ.su/sendtv/<код>`);
- [App management](https://www.happ.su/main/dev-docs/app-management.md) — только заголовки подписки (`subscription-autoconnect`: подключаться при запуске Happ);
- [Примеры ссылок](https://www.happ.su/main/dev-docs/examples-of-links-and-parameters.md), [указатель документации](https://www.happ.su/main/llms.txt) — `happ://add/<ссылка>` для добавления подписки и ничего для управления VPN.

Поэтому Happ остаётся как было: «Как подключить» → «Открыть/Установить Happ», и на Android 5–6.

### Вариант B — своё ядро Xray (выбран)

- **Ядро**: `libv2ray.aar` из [2dust/AndroidLibXrayLite](https://github.com/2dust/AndroidLibXrayLite) — та же сборка Xray-core, что в v2rayNG.
  Версия **v26.10.17**, sha256 `fd6cb61fed873e465c3064327dffbcb22dc3fd78260d162ec9e868db2582495f` (закреплены в `fetch-deps.sh`).
  AAR скачивается в CI; из него удаляются полные geoip/geosite (~27 МБ) и x86-библиотеки.
- **TUN**: встроенный вход `tun` самого Xray. В AndroidLibXrayLite `CoreController.startLoop(config, tunFd)` передаёт fd
  интерфейса VpnService в ядро (`xray.tun.fd`, [tun_android.go](https://github.com/XTLS/Xray-core/blob/main/proxy/tun/tun_android.go)).
  v2rayNG умеет так же (вторая опция — hev-socks5-tunnel, её надо собирать NDK; нам не нужна): одна нативная библиотека, меньше движущихся частей.
- **Минимальный Android — 7.0 (API 24)**: AAR собран с `-androidapi 24`. Лаунчер по-прежнему ставится на Android 5+,
  но на 5–6 кнопка работает через Happ, как раньше.
- **Отдельный процесс `:vpn`**: падение Go-ядра не роняет домашний экран.

## Как устроено (пакет `space.whitehole.tv.vpn`)

| Файл | Что делает |
|---|---|
| `ShareLink.kt` | разбор подписки: base64 / строки / Xray-JSON → `VlessLink` (reality: pbk, sid, sni, fp, spx, pqv; flow; tcp/xhttp/grpc/ws) |
| `ServerCatalog.kt` | список серверов: склейка «📱/💻» в одну строку, имена без эмодзи, Авто первым, резервы внизу; план попыток |
| `XrayConfigBuilder.kt` | JSON-конфиг Xray: tun → VLESS, DNS, маршрутизация |
| `SubscriptionStore.kt` | загрузка подписки с заголовками HWID, кэш последней удачной копии (обновление, если старше 1 ч) |
| `WhiteHoleVpnService.kt` | VpnService + уведомление «Подключено · Франция / Отключить» |
| `XrayCore.kt` | обёртка libv2ray, проверка сервера, geoip.dat |
| `VpnState.kt` | состояние DISCONNECTED/CONNECTING/CONNECTED/ERROR (служба → файл + broadcast → лаунчер) |
| `VpnController.kt` | подключить/отключить, окно разрешения VPN, автоподключение после перезагрузки |
| `VpnHomeHook.kt` | всё, что меняется на главной: кнопка «Подключить/Отключить», «Сервер: …», статус, `ConnectAnimator` |
| `ServerPickerActivity.kt` | экран «Сервер» |

Подключение: разрешение VPN (один раз) → подписка (кэш ≤ 1 ч, иначе загрузка) → план: выбранный сервер
TCP+Vision → XHTTP → (для «Авто» — первая страна) → первый резерв. Каждый вариант проверяется отдельным экземпляром
ядра (запрос `generate_204` через прокси, ≤ 10 с), затем поднимается tun с первым рабочим. Если всё упало на старом кэше —
подписка перезагружается и план повторяется один раз.

### Подписка и лимит устройств (Remnawave)

- Заголовки как у Happ/v2rayTUN ([docs.rw: HWID device limit](https://docs.rw/docs/features/hwid-device-limit)):
  `x-hwid` (32 hex, случайный, хранится в `files/vpn/hwid`, не меняется), `x-device-os: Android`, `x-ver-os`,
  `x-device-model: <модель> (WhiteHole TV)`.
- `User-Agent: WhiteHoleTV/<версия>` — не совпадает ни с одним правилом ответа по умолчанию, поэтому панель отдаёт
  запасной формат **XRAY_BASE64** (ссылки vless://). UA v2rayNG/Happ не подходит: при включённой настройке
  `serveJsonAtBaseSubscription` им отдаётся Xray-JSON (см. `JSON_SUBSCRIPTION_FALLBACK_CLIENTS` в
  [remnawave/backend](https://github.com/remnawave/backend/blob/main/src/modules/subscription-template/constants/extended-clients.ts)
  и [правила по умолчанию](https://github.com/remnawave/backend/blob/main/prisma/seed/default/response-rules.ts)). JSON мы тоже разбираем на всякий случай.
- `Accept: */*` обязателен: стандартный Accept в Android содержит `text/html`, а правило «Browser» отдало бы HTML-страницу.
- Ответ `x-hwid-max-devices-reached: true` → «Достигнут лимит устройств» (кэш в этом случае не используется — лимит работает).
- Адрес «⚡ Авто» с несколькими IP через запятую: Remnawave сам выбирает один случайный при каждой выдаче
  (`resolveRandomizedValue`), в ссылке всегда один адрес.

### Маршрутизация v1 (упрощённо относительно профиля Happ `infra/happ-routing.json`)

1. DNS телевизора (порт 53) → DNS-модуль Xray: российские домены — `77.88.8.8` напрямую, остальное — `1.1.1.1`/`8.8.8.8` через VPN; только IPv4.
2. Локальные сети — напрямую (и вообще не заворачиваются в tun: adb по Wi-Fi, Chromecast, DLNA работают).
3. YouTube / Google / Telegram — **всегда через VPN** (правило раньше «напрямую», как `RouteOrder: block-proxy-direct`).
4. `.ru .su .рф .дети` + ~80 крупных российских сервисов на других доменах (Яндекс, VK, банки, Ozon/WB, кино, Steam) — напрямую.
5. `geoip:ru` (компактная geoip.dat, только RU) + сети Valve — напрямую.
6. UDP/443 (QUIC) — отказ, приложения сразу переходят на TCP. Остальное — через VPN.

geoip.dat/geosite.dat кладутся в assets при сборке (`fetch-deps.sh`, с `/miniapp/geoip.dat`); если в APK их нет —
geoip.dat скачивается при первом подключении (не чаще раза в час при ошибке). Без неё правило `geoip:ru` просто не добавляется.
`geoip:private` не используется: в компактной базе его нет, локальные сети заданы списком подсетей.

## Сборка

Только GitHub Actions (`.github/workflows/tv-launcher.yml`): `vpn/fetch-deps.sh` → `gradle testReleaseUnitTest assembleRelease`.
APK: универсальный (armeabi-v7a + arm64-v8a) и отдельные по процессору. Ветка `claude/tv-builtin-vpn` публикуется в
релиз **tv-launcher-vpn-test** (`whitehole-tv-vpn.apk`), основной `tv-launcher-latest` не трогается.

## Проверка на телевизоре

```powershell
adb shell getprop ro.product.cpu.abi
adb install -r whitehole-tv-vpn.apk
adb logcat -s WhVpn WhVpnSub WhVpnCore WhVpnGeo GoLog
```

Если телевизор не показывает окно «Разрешить VPN» (бывает на урезанных ТВ-прошивках):

```powershell
adb shell appops set space.whitehole.tv ACTIVATE_VPN allow
```

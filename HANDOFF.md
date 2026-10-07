# WhiteHoleVPN — выжимка проекта (контрольная точка 07.10.2026)

> Вставь этот файл в начало нового диалога. Отвечать по-русски, команды — готовые к копированию, однострочные
> (у пользователя Windows PowerShell + SSH; многострочные вставки ломаются из-за bracketed paste).

## 1. Что это
VPN-сервис **WhiteHoleVPN** (раньше GalacticVPN), продажа через Telegram-бота **@WhiteHoleVPNbot** + мини-приложение.
Цель — ~1000 устройств. Владелец: @FEOLAR. Старый бот (legacy) отвечает «мы переехали» и шлёт в новый.

## 2. Код
- Репозиторий: `FEOLAR/testing`, ветка **`claude/galacticvpn-project-hw65vu`** (всё запушено). PR не создавать без просьбы.
- `bot/app/` — бот (aiogram 3, aiohttp, SQLAlchemy async + PostgreSQL, Redis, docker compose).
- `infra/add-node.sh` — установка новой ноды (Docker, remnanode NODE_PORT 2222, sub-proxy Caddy :9443, ufw); `bash add-node.sh test` — тест TLS.
- `infra/bridge-nodes.sh` — мост в РФ: проверка нод, HAProxy (balance source) 443/8443, Caddy для подписки.
- Последний архив: **whitehole-bot-v21.zip**.

### Деплой бота (на сервере панели)
```
scp $env:USERPROFILE\Downloads\whitehole-bot-vNN.zip root@146.0.76.110:/root/
cd /root/vpn-shop/bot && unzip -o /root/whitehole-bot-vNN.zip && docker compose up -d --build
docker logs --tail 30 vpn-bot
```
Папка бота: **/root/vpn-shop/bot** (НЕ /opt/vpn-bot). Контейнер: `vpn-bot`. Настройки: `/root/vpn-shop/bot/.env`.

## 3. Инфраструктура
| Роль | IP | Примечание |
|---|---|---|
| Панель Remnawave 3.4.4 + бот | 146.0.76.110 | подписка/мини-апп через https://146-0-76-110.sslip.io |
| Мост РФ | **77.91.95.53** | HAProxy 443/8443 → ноды; Caddy /etc/caddy/Caddyfile :9443 → панель |
| Нода FR-1 (Франция) | 151.243.225.123 | |
| Нода GE-1 (Германия) | 194.247.187.139 | |

- Публичные адреса: подписка `https://77-91-95-53.sslip.io:9443/api/sub/...`, мини-апп `.../miniapp/`, страница «О сервисе» `.../miniapp/info`.
- Xray 26.x: инбаунды `VLESS_REALITY` (TCP :443, **flow xtls-rprx-vision** включён), `VLESS_XHTTP` (:8443, путь /api/v2/stream, xmux умеренный), `VLESS_GRPC` (:2053). SNI-донор `originfi.dattebayo.space`, fingerprint firefox.
- Хосты в панели: «Франция/Германия — 📱 для телефона» (TCP 443, тег AUTO), «— 💻 для ПК» (XHTTP 8443, AUTO), «Мост — 📱» (77.91.95.53:443), «Мост — 💻 если не работает» (:8443). Мост-хостам тег AUTO НЕ ставить.
- **Автобалансировщик** (`bot/app/balancer.py`): раз в минуту пишет в адрес AUTO-хостов IP исправных привязанных нод через запятую; упавшие ноды убирает (уведомление 🔴/🟢). Команда `/nodes`.
- Предложено (ждёт выполнения пользователем): хосты «⚡ Авто — 📱/💻» с тегом AUTO и привязкой к FR-1 + GE-1, поставить наверх.

## 4. iPhone: отключения VPN (решено)
Причина — лимит памяти iOS 50 МБ: geo-базы runetfreedom в профиле маршрутизации. Заменили заголовок подписки `routing`
на лёгкий профиль Happ без geoip/geosite (только domain:ru/su/рф + список доменов, DNS Cloudflare DoH + Яндекс),
телефонам — TCP+Vision (сервер «📱»). Подтверждено конфигом с iPhone: geo нет, flow vision есть.

## 5. Бот — функции
- Приветствие: фото чёрной дыры (`app/web/welcome.jpg`, заменить файлом и пересобрать) + подпись; экраны меняют подпись под фото (`app/ui.py`).
- **Фирменные премиум-эмодзи**: `app/emoji.py` — при старте бот сам создаёт пак `whicons_by_WhiteHoleVPNbot` из PNG в `app/web/emoji/` (Lucide, ISC), `e('zap')` в текстах. Работает благодаря Telegram Premium владельца бота (правило Bot API) — **Premium надо продлевать**, иначе будут обычные эмодзи. Порядок `ICONS` только дописывать в конец. Команды `/icons`, `/icons reload`, `/emoji <пак>`, `/emoji_ids`, `/emoji_mypack`.
- Меню (v21): Открыть приложение / Моя подписка / Купить|Инструкция / VPN сам отключается / Пригласить друга / О сервисе|Поддержка (+ «Попробовать бесплатно» сверху для новых).
- Инструкция: iPhone — Happ App Store + кнопка «🍏 Happ недоступен в App Store» (смена региона Apple ID); Android/Huawei — APK `https://github.com/Happ-proxy/happ-android/releases/latest/download/Happ.apk`; Windows — happ-desktop. То же в мини-аппе.
- Оплата: **Telegram Stars** (pre_checkout сверяет сумму, `/refund`, `/test_stars`, `/stars_check [apply]`) и **CryptoBot** (включён, `CRYPTOPAY_TOKEN`, `CRYPTOPAY_ASSETS=USDT,TON,BTC,LTC,TRX`, опрос каждые 20 с).
- Цены: `.env` `PLANS=дни:рубли:звёзды,...` (по умолчанию 30:199:150,90:549:400,180:999:750,365:1790:1350).
- Админ-команды: `/admin /stats /nodes /top [дни] [N] /user /give /ban /unban /refund /broadcast (ответом на сообщение) /broadcast_old /test_stars /stars_check`.
- Рассылка через старого бота: `docker exec -it vpn-bot python -m app.broadcast_old test|all`.

## 6. Открытые задачи / идеи
1. Установить v21, проверить меню и инструкции; создать хосты «⚡ Авто».
2. Рассылка пользователям: обновить подписку, на телефоне выбирать 📱, новая оплата криптой, Happ через смену региона/APK.
3. Happ удалён из российского App Store (март–июнь 2026); проверить Happ Plus как альтернативу ссылке.
4. Возможно: взвешенный балансировщик по загрузке нод; кнопки с иконками (`icon_custom_emoji_id`, нужен свежий aiogram → `docker compose build --no-cache`); анимированное приветствие (видео).
5. Удалить неиспользуемые серверы Hostkey; вторая нода у другого хостинга; второй мост.

## 7. Безопасность
- В чате ранее светились: root-пароль FI-2, Reality privateKey, токен CryptoBot (просил перевыпустить), UUID пользователя.
  Не повторять их; при случае — сменить пароль, перевыпустить ключ Reality (потребует обновления подписок).
- Секреты не коммитить; `.env` в архивы не включается.

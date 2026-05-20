---
name: vpn-setup
description: >
  Deploy a self-hosted VPN/proxy server on a remote VPS via SSH.
  Use this skill whenever the user wants to set up, configure, or troubleshoot
  a personal VPN server — especially with Hysteria 2, VLESS+Reality (XRay),
  or similar censorship-resistant protocols. Triggers on phrases like
  "поднять впн", "настроить vpn сервер", "xray", "hysteria", "vless", "reality",
  "прокси на vps", "обход блокировок", "свой впн".
---

# VPN Setup Skill

Развёртывание self-hosted VPN/прокси на VPS. Два протокола: **Hysteria 2** и **VLESS+Reality**.

## Выбор протокола

| Критерий | Hysteria 2 | VLESS+Reality |
|---|---|---|
| Нужен домен | Да (для TLS-сертификата) | Нет |
| Скорость | Очень высокая (QUIC/UDP) | Высокая (TCP) |
| Устойчивость к DPI | Высокая | Очень высокая |
| Сложность | Низкая | Средняя |
| Если блокируют UDP 443 | ❌ Не работает | ✅ Работает |

**Рекомендация по умолчанию:** VLESS+Reality — не требует домена и устойчивее к блокировкам.

---

## Общие требования к VPS

- **ОС:** Debian 12 (предпочтительно) или Ubuntu 22.04+
- **RAM:** минимум 512 МБ (рекомендуется 1 ГБ)
- **Диск:** 10 ГБ SSD
- **Сеть:** статический IPv4, канал от 100 Мбит
- **Локация:** НЕ Россия, НЕ Беларусь, НЕ Китай — иначе блокировки будут с обеих сторон
- **Доступ:** root по SSH или пользователь с sudo

### ⚠️ Ловушка: права пользователя
Если VPS выдал не root, а обычного пользователя — сначала переключись:
```bash
sudo su -
# или если sudo нет:
su -
```
Все дальнейшие команды выполняются от root.

---

## ВАРИАНТ А: Hysteria 2

### Шаг 0: Проверка перед установкой

```bash
# Проверить, что порты свободны
ss -tlnp | grep -E ':80|:443'
# Если что-то висит на 443 — убить или остановить (nginx, apache, caddy)

# Проверить наличие ufw
ufw status
```

### ⚠️ Ловушка: занятый порт 443
Если на сервере уже стоит nginx/apache — они займут 443 и Hysteria не запустится. Остановить:
```bash
systemctl stop nginx && systemctl disable nginx
# или apache2
systemctl stop apache2 && systemctl disable apache2
```

### Шаг 1: Обновление системы

```bash
apt update && apt upgrade -y && apt install curl micro pwgen -y
```

### ⚠️ Ловушка: зависший apt
Если apt завис на "Waiting for cache lock" — другой процесс держит блокировку:
```bash
rm /var/lib/dpkg/lock-frontend
rm /var/lib/apt/lists/lock
apt update
```

### Шаг 2: Настройка домена

Hysteria 2 требует валидный домен с A-записью → IP сервера. Без домена ACME не получит сертификат.

**Бесплатный домен через dynu.com:**
1. Зарегистрироваться на https://www.dynu.com/
2. DDNS Services → Add → выбрать имя и TLD
3. В поле IPv4 Address вставить IP сервера → Save
4. Подождать 5–10 минут на распространение DNS

**Проверить что домен резолвится:**
```bash
dig +short YOUR_DOMAIN
# должен вернуть IP сервера
# или:
curl -s ifconfig.me  # должен совпасть с выводом dig
```

### ⚠️ Ловушка: ACME не получает сертификат
Причины:
- DNS ещё не распространился (подождать, проверить через dig)
- Порт 80 закрыт файрволом (нужен для HTTP challenge)
- Неправильно указан email в конфиге
- Рейт-лимит Let's Encrypt (5 неудачных попыток за 1 час — ждать час)

Проверить логи:
```bash
journalctl -u hysteria-server.service -f --no-pager | head -50
```

### Шаг 3: Установка Hysteria 2

```bash
bash <(curl -fsSL https://get.hy2.sh/)
```

Успех — строка: `Congratulation! Hysteria 2 has been successfully installed on your server`

### ⚠️ Ловушка: curl не работает
Если нет curl или скрипт не скачивается:
```bash
apt install curl -y
# если домен установщика заблокирован на VPS — скачать вручную:
# https://github.com/apernet/hysteria/releases — скачать бинарник hysteria-linux-amd64
```

### Шаг 4: Сайт-заглушка

```bash
mkdir -p /var/www/masq
cat > /var/www/masq/index.html << 'EOF'
<!DOCTYPE html>
<html>
<head><title>Welcome to nginx!</title>
<style>html{color-scheme:light dark}body{width:35em;margin:0 auto;font-family:Tahoma,Verdana,Arial,sans-serif}</style>
</head>
<body>
<h1>Welcome to nginx!</h1>
<p>If you see this page, the nginx web server is successfully installed and working.</p>
</body>
</html>
EOF
```

### Шаг 5: Генерация пароля

```bash
pwgen 40 1
# сохранить вывод — это будет HYSTERIA_PASSWORD
```

### Шаг 6: Конфигурация сервера

```bash
# Удалить дефолтный конфиг
rm -f /etc/hysteria/config.yaml

# Записать конфиг (заменить все переменные в угловых скобках)
cat > /etc/hysteria/config.yaml << 'EOF'
listen: 0.0.0.0:443

acme:
  type: http
  domains:
    - YOUR_DOMAIN_HERE
  email: YOUR_EMAIL_HERE

auth:
  type: userpass
  userpass:
    vpnuser: YOUR_PASSWORD_HERE

masquerade:
  type: file
  file:
    dir: /var/www/masq
  listenHTTP: :80
  listenHTTPS: :443
  forceHTTPS: true
EOF
```

### ⚠️ Ловушка: YAML-синтаксис
YAML очень чувствителен к отступам. Не использовать табы — только пробелы. Проверить:
```bash
python3 -c "import yaml; yaml.safe_load(open('/etc/hysteria/config.yaml'))" && echo "OK"
```

### Шаг 7: Открыть порты

```bash
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp

# Если ufw не установлен — это нормально, ничего делать не нужно
# Если используется iptables:
iptables -A INPUT -p tcp --dport 80 -j ACCEPT
iptables -A INPUT -p tcp --dport 443 -j ACCEPT
iptables -A INPUT -p udp --dport 443 -j ACCEPT
```

### ⚠️ Ловушка: файрвол на уровне хостера
Некоторые хостеры (Hetzner, DigitalOcean, AWS) имеют файрвол в панели управления — отдельно от ufw. Надо разрешить порты там тоже.

### Шаг 8: Запуск сервиса

```bash
systemctl start hysteria-server.service
systemctl enable hysteria-server.service

# Проверить статус (через 30 секунд после старта)
systemctl status hysteria-server.service
```

Искать `active (running)` в выводе. Если `failed` — смотреть логи:
```bash
journalctl -u hysteria-server.service --no-pager -n 50
```

### Шаг 9: Получить URI для клиента

```bash
cd ~
cat > hysteria-client.yaml << EOF
server: YOUR_DOMAIN_HERE:443
auth: vpnuser:YOUR_PASSWORD_HERE
EOF

hysteria share -c hysteria-client.yaml
# Скопировать строку hysteria2://...

# QR-код для мобильных клиентов:
hysteria share -c hysteria-client.yaml --qr
```

### ⚠️ Ловушка: первый запуск занимает время
ACME получает сертификат при первом запуске — это может занять 3–5 минут. Не перезапускать сервис в этот момент. Подождать и проверить домен в браузере — должен открыться без предупреждений.

---

## ВАРИАНТ Б: VLESS + Reality (XRay)

Домен не нужен. Маскируется под реальный внешний сайт.

### Шаг 0: Выбор сайта для маскировки (SNI)

Нужен популярный сайт с TLS 1.3 + HTTP/2 + X25519. Проверить:
```bash
apt install curl openssl -y

# Проверить сайт (например, www.microsoft.com)
SNI="www.microsoft.com"
curl -s -o /dev/null -w "%{http_version}" --tlsv1.3 --http2 https://$SNI
# должно вернуть "2" (HTTP/2)

openssl s_client -connect $SNI:443 -brief 2>&1 | grep -E "TLS|Cipher"
# ищем TLSv1.3 и X25519
```

**Хорошие варианты SNI:** `www.microsoft.com`, `www.apple.com`, `addons.mozilla.org`, `dl.google.com`

**Плохие варианты:** российские сайты, сайты под CloudFlare (могут вернуть IP Cloudflare вместо трафика), сайты с Cloudflare Proxy.

### ⚠️ Ловушка: Cloudflare-сайты
Если SNI-сайт за Cloudflare — XRay будет пересылать трафик на Cloudflare, а не на целевой сервер. Это сломает маскировку. Проверить через `dig SNI_DOMAIN` — если IP принадлежит 104.16.x.x или 172.67.x.x — это Cloudflare, выбрать другой сайт.

### Шаг 1: Установка XRay

```bash
apt update -y
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
```

Проверить установку:
```bash
xray version
systemctl status xray
```

### Шаг 2: Генерация учётных данных

```bash
# UUID — уникальный идентификатор клиента
xray uuid
# Сохранить вывод → UUID

# Пара ключей для Reality
xray x25519
# Сохранить:
#   Private key: ...  → PRIVATE_KEY
#   Public key: ...   → PUBLIC_KEY
```

### ⚠️ Ловушка: потерять ключи
Публичный ключ нужен на клиенте, приватный — только на сервере. Если потерять — придётся генерировать новую пару и обновлять конфиг с обеих сторон. Сохранить сразу в файл:
```bash
xray x25519 > ~/xray-keys.txt
cat ~/xray-keys.txt
```

### Шаг 3: Генерация shortIds

```bash
# Сгенерировать несколько (можно использовать один)
openssl rand -hex 6
openssl rand -hex 6
openssl rand -hex 6
# Сохранить значения → SHORT_IDS
```

### Шаг 4: Конфигурация XRay

```bash
cat > /usr/local/etc/xray/config.json << 'EOF'
{
    "log": {
        "loglevel": "warning"
    },
    "inbounds": [
        {
            "port": 443,
            "protocol": "vless",
            "settings": {
                "clients": [
                    {
                        "id": "YOUR_UUID_HERE",
                        "flow": "xtls-rprx-vision"
                    }
                ],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "tcp",
                "security": "reality",
                "realitySettings": {
                    "dest": "YOUR_SNI_DOMAIN:443",
                    "serverNames": [
                        "YOUR_SNI_DOMAIN",
                        "www.YOUR_SNI_DOMAIN"
                    ],
                    "privateKey": "YOUR_PRIVATE_KEY_HERE",
                    "shortIds": [
                        "YOUR_SHORT_ID_1",
                        "YOUR_SHORT_ID_2"
                    ]
                }
            },
            "sniffing": {
                "enabled": true,
                "destOverride": ["http", "tls"]
            }
        }
    ],
    "outbounds": [
        {
            "protocol": "freedom",
            "tag": "direct"
        }
    ]
}
EOF
```

**Переменные для замены:**
- `YOUR_UUID_HERE` → UUID из шага 2
- `YOUR_SNI_DOMAIN` → домен для маскировки (например `www.microsoft.com`)
- `YOUR_PRIVATE_KEY_HERE` → Private key из шага 2
- `YOUR_SHORT_ID_1`, `YOUR_SHORT_ID_2` → значения из шага 3

### ⚠️ Ловушка: JSON-синтаксис
В JSON нельзя оставлять trailing comma (запятую после последнего элемента). Проверить:
```bash
python3 -c "import json; json.load(open('/usr/local/etc/xray/config.json'))" && echo "OK"
```

### ⚠️ Ловушка: комментарии в JSON
Оригинальный шаблон из статьи содержит комментарии `// ...` — это невалидный JSON. XRay поддерживает JSONC (JSON with comments), но лучше убрать все комментарии чтобы не было сюрпризов.

### Шаг 5: Открыть порты

```bash
ufw allow 443/tcp
# UDP для VLESS не нужен (протокол работает по TCP)
```

### Шаг 6: Запуск XRay

```bash
systemctl restart xray
systemctl enable xray
systemctl status xray
```

Ожидаемый статус: `active (running)`. Если `failed`:
```bash
journalctl -u xray --no-pager -n 30
# Частые ошибки:
# "address already in use" → порт 443 занят (см. шаг 0 Hysteria)
# "invalid UUID" → неправильный формат UUID
# "failed to parse config" → синтаксическая ошибка JSON
```

### Шаг 7: Сформировать URL для клиента

Шаблон URL:
```
vless://UUID@SERVER_IP:443?type=tcp&security=reality&pbk=PUBLIC_KEY&fp=chrome&sni=SNI_DOMAIN&sid=SHORT_ID&flow=xtls-rprx-vision#MyVPN
```

Заменить:
- `UUID` → из шага 2
- `SERVER_IP` → IP адрес VPS
- `PUBLIC_KEY` → из шага 2 (публичный ключ, не приватный!)
- `SNI_DOMAIN` → домен маскировки
- `SHORT_ID` → один из shortIds из шага 3

### ⚠️ Ловушка: публичный vs приватный ключ
В конфиге сервера — `privateKey`. В URL клиента — `pbk=PUBLIC_KEY` (публичный). Часто путают — тогда клиент не может установить соединение.

### Шаг 8: QR-код (опционально)

```bash
apt install qrencode -y
qrencode -t ANSIUTF8 'vless://...'  # прямо в терминале
# или в файл:
qrencode -o ~/qr.png 'vless://...'
```

---

## Клиент: Happ (рекомендуется)

**Happ** — рекомендуемый клиент для этого сетапа. Поддерживает VLESS+Reality, Hysteria 2, VMess, Trojan, Shadowsocks. Работает на Xray-core.

### Скачивание Happ

| Платформа | Ссылка |
|---|---|
| iOS (Global) | https://apps.apple.com/us/app/happ-proxy-utility/id6504287215 |
| iOS (Россия) | https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973 |
| Android (Google Play) | https://play.google.com/store/apps/details?id=com.happproxy |
| Android (APK) | https://github.com/Happ-proxy/happ-android/releases/latest/download/Happ.apk |
| Windows x64 | https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe |
| macOS (dmg) | https://github.com/Happ-proxy/happ-desktop/releases/latest/download/Happ.macOS.universal.dmg |
| Linux deb | https://github.com/Happ-proxy/happ-desktop/releases/latest/download/Happ.linux.x64.deb |
| Linux rpm | https://github.com/Happ-proxy/happ-desktop/releases/latest/download/Happ.linux.x64.rpm |
| Android TV / Apple TV | те же ссылки что для Android/iOS |

### Способы добавления сервера в Happ

**Способ 1 — вставить URL вручную:**
Нажать `+` → "Add from clipboard" → вставить `vless://...` или `hysteria2://...` URL.

**Способ 2 — QR-код:**
Нажать `+` → сканировать QR-код с экрана сервера.

**Способ 3 — Subscription URL (рекомендуется для раздачи нескольким пользователям):**
Нажать `+` → "Add subscription" → вставить URL файла с конфигами.

### Формат Subscription-файла для Happ

Создать текстовый файл, доступный по HTTP/HTTPS. Содержимое — список URL-ов, по одному на строку, с опциональными мета-параметрами через `#`:

```
#profile-title: Мой VPN
#profile-update-interval: 24
#subscription-autoconnect: 1
#subscription-autoconnect-type: lowestdelay
#subscription-ping-onopen-enabled: 1
vless://UUID@SERVER_IP:443?type=tcp&security=reality&pbk=PUBLIC_KEY&fp=chrome&sni=SNI_DOMAIN&sid=SHORT_ID&flow=xtls-rprx-vision#Server 1
hysteria2://USER:PASS@YOUR_DOMAIN:443#Server 2
```

### Мета-параметры Happ (полный список)

Все параметры передаются через `#param: value` в теле subscription-файла или через HTTP-заголовки ответа.

**Основные (без Provider ID):**

| Параметр | Значение | Описание |
|---|---|---|
| `profile-title` | строка, макс 25 символов | Название подписки |
| `profile-update-interval` | число (часы) | Интервал автообновления |
| `profile-web-page-url` | URL | Ссылка на сайт (иконка в приложении) |
| `support-url` | URL | Ссылка на поддержку (Telegram-иконка если t.me) |
| `subscription-userinfo` | `upload=0; download=N; total=N; expire=timestamp` | Трафик и дата истечения |
| `announce` | строка или `base64:...` | Объявление (макс 200 символов) |
| `routing-enable` | 0 | Отключить роутинг |
| `subscription-autoconnect` | 1 | Автоподключение при запуске |
| `subscription-autoconnect-type` | `lastused` / `lowestdelay` / `random` | Критерий выбора сервера |
| `subscription-ping-onopen-enabled` | 1 | Пинг серверов при открытии |
| `subscription-auto-update-enable` | 1 | Автообновление всех подписок |
| `subscription-auto-update-open-enable` | 1 | Обновлять при каждом запуске |
| `subscriptions-sort-type` | `without` / `ping` / `alphabet` | Сортировка серверов |
| `sniffing-enable` | 1 | Анализ пакетов (включён по умолчанию) |
| `ping-type` | `proxy` / `proxy-head` / `tcp` / `icmp` | Тип пинга |
| `check-url-via-proxy` | URL | URL для проверки пинга через прокси |
| `hide-settings` | 1 | Скрыть настройки серверов от пользователя |
| `subscription-pin` | true | Закрепить подписку наверху |
| `subscriptions-collapse` | 0 | Запретить сворачивание подписки |
| `app-auto-start` | 1 | Автозапуск при включении (Android) |
| `per-app-proxy-mode` | `on` / `bypass` / `off` | Прокси только для выбранных приложений |
| `per-app-proxy-list` | `com.app1,com.app2` | Список приложений |
| `exclude-routes` | `192.168.0.0/16, 10.0.0.0/8` | Исключить подсети из тоннеля |
| `no-limit-enabled` | 1 | No Limit Mode (бета) |
| `mux-enable` | 1 | Мультиплексирование соединений |
| `proxy-enable` | 1 | Режим прокси (Desktop) |
| `tun-enable` | 1 | Режим TUN (Desktop, не совмещать с proxy) |
| `tun-mode` | `system` / `gvisor` | Стек для TUN |
| `tun-type` | `singbox` / `tun2proxy` / `default` | Ядро для TUN |
| `hide-vpn-icon` | true | Скрыть иконку VPN в статусбаре |
| `include-all-networks-enable` | 1 | Все сети в тоннеле (iOS 16.4+) |
| `exclude-local-networks-enable` | 1 | Исключить локальную сеть из тоннеля (iOS) |
| `fragmentation-enable` | 1 | Фрагментация пакетов |
| `fragmentation-packets` | `tlshello` | Тип фрагментации |
| `fragmentation-length` | `50-100` | Длина фрагментов |
| `fragmentation-interval` | `5` | Интервал между фрагментами |
| `color-profile` | JSON строка или `resetcolors` | Кастомная тема (iOS) |

**Требуют Provider ID (продвинутые):**

| Параметр | Описание |
|---|---|
| `new-url` | Заменить URL подписки у всех пользователей |
| `new-domain` | Заменить домен подписки |
| `fallback-url` | Резервный URL если основной недоступен |
| `sub-info-text` | Информационный баннер (макс 200 символов) |
| `sub-info-color` | Цвет баннера: `red` / `blue` / `green` |
| `sub-info-button-text` | Текст кнопки на баннере |
| `sub-info-button-link` | Ссылка кнопки |
| `sub-expire` | 1 — показывать уведомление об истечении за 3 дня |
| `sub-expire-button-link` | Ссылка кнопки "Продлить" |
| `notification-subs-expire` | 1 — push-уведомление за 3 дня до истечения |
| `subscription-always-hwid-enable` | 1 — запретить пользователю отключать HWID |
| `server-address-resolve-enable` | 1 — предрезолвить IP серверов перед подключением |
| `server-address-resolve-dns-domain` | URL DoH сервера для резолвинга |
| `change-user-agent` | Кастомный User-Agent для получения подписки |
| `manual-block-user-agent` | 1 — запретить пользователю менять User-Agent |

### Описание серверов (serverDescription)

Добавить подпись под именем сервера — в конец URL через `?serverDescription=BASE64`:

```
# Сначала получить base64 на сервере:
echo -n "Быстрый DE" | base64

# Вставить в конец URL после #Название:
vless://UUID@IP:443?...#Server DE?serverDescription=0JHRi9GB0YLRgNGL0Lkg0YHQtdGA0LLQtdGA
```

### Фрагментация при получении subscription (URL-параметры)

Если subscription URL заблокирован — добавить в конец `#title?` параметры:

```
# Фрагментация:
https://my-server.com/sub#MyVPN?fragment=80-250,10-100,tlshello

# Fronting через visa.com с реальным хостом:
https://visa.com/sub#MyVPN?resolve-address=visa.com&host=my-server.com
```

### ⚠️ Ловушки Happ

**Hysteria 2 в Happ:** поддерживается, убедиться что версия приложения актуальная — старые версии не поддерживали протокол.

**TUN vs Proxy (Desktop):** нельзя включить оба одновременно (`tun-enable` + `proxy-enable`). TUN = весь трафик через тоннель, Proxy = только через системный прокси.

**`per-app-proxy-mode` без `list`:** если не указать список приложений — режим применится ко всем, что может не работать как ожидается.

**`sub-info` vs `sub-expire`:** если активно `sub-expire` сообщение (истечение ≤ 3 дней) — `sub-info` блок не показывается. Показывается только одно из двух.

**`subscription-always-hwid-enable`:** требует Provider ID — без него параметр игнорируется. Не путать со стандартными параметрами.

**`no-limit-enabled` и `no-limit-xhttp-enabled`:** нельзя включать оба одновременно — сломает конфигурацию.

**Subscription через `http://`:** по умолчанию Happ требует HTTPS. Если сервер раздаёт по HTTP — при добавлении подписки включить toggle "insecure" (доступен только при создании, изменить потом нельзя).

---

## Другие клиенты

| Платформа | Клиенты |
|---|---|
| Windows | Hiddify, NekoBox, InvisibleMan-XRay, Throne |
| macOS | Hiddify, FoXray, Streisand, Throne |
| Linux | Hiddify, NekoBox, Throne |
| Android | v2rayNG, Hiddify, NekoBox |
| iOS | Hiddify, FoXray, Streisand |

Импорт везде одинаковый: вставить `vless://...` или `hysteria2://...` URL, или отсканировать QR.

---

## Диагностика общих проблем

### Клиент подключается, но сайты не открываются
```bash
# На сервере проверить исходящий интернет
curl -s https://httpbin.org/ip
# Если не работает — проблема у хостера, не в конфиге
```

### Высокий latency / медленная скорость (Hysteria 2)
```bash
# Hysteria использует UDP — некоторые хостеры его режут
# Проверить потерю пакетов:
ping -c 20 SERVER_IP
# Или проверить UDP через:
nc -u SERVER_IP 443
```

### XRay запущен, но соединение отклоняется
- Проверить, что `fp=chrome` в URL клиента (fingerprint должен совпадать)
- Проверить, что `sid` в URL есть в списке `shortIds` конфига сервера
- Проверить firewall хостера

### Обновление конфига без даунтайма
```bash
# Hysteria 2
systemctl reload hysteria-server.service
# или
systemctl restart hysteria-server.service

# XRay
systemctl restart xray
```

### Добавить второго пользователя

**Hysteria 2** — добавить в `auth.userpass`:
```yaml
auth:
  type: userpass
  userpass:
    user1: password1
    user2: password2
```

**VLESS+Reality** — добавить в `clients`:
```json
"clients": [
  {"id": "UUID1", "flow": "xtls-rprx-vision"},
  {"id": "UUID2", "flow": "xtls-rprx-vision"}
]
```
Новый UUID: `xray uuid`

---

## Безопасность

```bash
# Сменить SSH-порт (опционально, снижает брутфорс)
sed -i 's/#Port 22/Port 2222/' /etc/ssh/sshd_config
systemctl restart sshd
ufw allow 2222/tcp

# Отключить вход по паролю (если настроены SSH-ключи)
sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

# Установить fail2ban
apt install fail2ban -y
systemctl enable fail2ban --now
```

### ⚠️ Ловушка: не заблокировать себя
При смене SSH-порта — сначала открыть новый порт в ufw, потом перезапускать sshd. Иначе потеряешь доступ к серверу.

---

## Быстрая шпаргалка команд

```bash
# Hysteria 2 — статус и логи
systemctl status hysteria-server.service
journalctl -u hysteria-server.service -f

# XRay — статус и логи
systemctl status xray
journalctl -u xray -f

# Перезапуск
systemctl restart hysteria-server.service
systemctl restart xray

# Проверка что порт слушается
ss -tlnp | grep 443
ss -ulnp | grep 443  # UDP (для Hysteria)
```

# Мобильные прокси, ротация IP и сетевая маскировка

[English](../PROXIES.md) · Русская версия

Сетевая анонимность играет ключевую роль в успешном обходе систем антифрода наряду с подменой цифровых отпечатков. Ошибки в работе с сетью (утечки реального IP, синтетические TLS-отпечатки Python-библиотек или гонки при ротации модемов) моментально выдают автоматизацию.

В Syntetic Core сетевой контур базируется на четырех принципах:
1. **Нативный TLS-стек браузера:** Исключает синтетические сигнатуры библиотек за счет проброса чистого TCP-трафика браузера через локальный SOCKS5-шлюз.
2. **Блокировка физических модемных каналов:** Предотвращает одновременную ротацию и конфликты на портах, использующих общий USB-модем.
3. **Автоматическая ротация через API провайдеров:** Поддержка HTTP API любых провайдеров мобильных прокси.
4. **Обязательный зонд подтверждения смены IP:** Гарантирует, что внешний IP-адрес реально изменился, прежде чем браузер откроет новую сессию.

---

## Поддерживаемые протоколы и настройка

`ProxyConfig` поддерживает протоколы `http://host:port`, `https://host:port` и `socks5://host:port`:

```python
import os
from pydantic import SecretStr
from syntetic_core import CoreSettings, ProxyConfig, SynteticCore

mobile_proxy = ProxyConfig(
    id="mobile-modem-1",
    server="http://proxy.provider.example:28080",
    username=SecretStr(os.environ["PROXY_USERNAME"]),
    password=SecretStr(os.environ["PROXY_PASSWORD"]),
    kind="mobile",  # "mobile", "residential" или "datacenter"
)

core = SynteticCore(
    settings=CoreSettings(
        proxies=[mobile_proxy],
        proxy_required=True,  # Запрещает запуск без прокси (защита от утечки реального IP хоста)
        allowed_target_hosts=["example.com", "api.ipify.org"],
    ),
    proxy_channels={"mobile-modem-1": "physical-usb-dongle-01"},
)
```

> [!IMPORTANT]
> При установке параметра `proxy_required=True` любая ошибка подключения или аутентификации на прокси приведет к немедленной остановке. Ядро ни при каких обстоятельствах не переключается на прямое соединение без прокси.

---

## Блокировка каналов физических модемов (`proxy_channels`)

Большинство поставщиков мобильных прокси предоставляют несколько портов, физически подключенных к одному USB-модему или пулу SIM-карт. Перезагрузка модема на одном порту меняет IP для всех остальных портов этого модема, обрывая активные сессии.

Syntetic Core решает эту проблему через межпроцессные блокировки операционной системы:
- Несколько `proxy_id` связываются с общим именем канала: `proxy_channels={"port-1": "modem-A", "port-2": "modem-A"}`.
- Пока на `port-1` активна браузерная сессия, канал `modem-A` заблокирован.
- Любая попытка вызвать ротацию IP через `port-2` завершится исключением `ProxyChannelLockedError`, защищая активную сессию от обрыва соединения.

---

## Автоматическая HTTP-ротация и проверка выхода (Exit IP Verification)

Ответ API провайдера вида `{"success": true}` не гарантирует, что модем уже переподключился к базовой станции и получил новый внешний IP.

Метод `rotate_ip` объединяет вызов API провайдера и независимую проверку:

```python
from syntetic_core import HttpRotationProvider

# Настройка вызова API ротации вашего мобильного провайдера
provider = HttpRotationProvider(
    url=SecretStr(os.environ["ROTATION_API_URL"]),
    method="POST",  # POST / GET / PUT
    headers={"Authorization": SecretStr(os.environ["ROTATION_AUTHORIZATION"])},
    json_body={"modem_id": "dongle-01"},
    success_field="data.status",  # Опционально: проверка конкретного поля в JSON
    success_value="reconnecting",
    timeout_seconds=15,
)

# Вызов смены IP с гарантией проверки нового внешнего адреса перед запуском сессии
result = await core.rotate_ip(
    proxy_id="mobile-modem-1",
    provider=provider,
    probe_url="https://api.ipify.org?format=json",
    timeout_seconds=60,
    poll_seconds=2,
)

print(f"IP успешно изменен с {result.old_ip} на {result.new_ip}")
```

### Конвейер верификации:
1. Захватывает эксклюзивную блокировку канала физического модема.
2. Фиксирует текущий публичный IP через зонд `probe_url`, отправленный через прокси.
3. Отправляет запрос на эндпоинт ротации провайдера.
4. Опрашивает `probe_url` через прокси до тех пор, пока не будет получен **другой публичный IP-адрес**.
5. Освобождает блокировку канала и сохраняет новый IP в `runtime-state.json`.

---

## Нативный браузерный TLS против библиотечных TLS-стеков

Когда автоматизация использует HTTP-библиотеки вроде `requests`, `httpx` или `curl`, структура пакета TLS ClientHello (наборы шифров, TLS-расширения, кривые) формирует отпечаток JA3/JA4, кардинально отличающийся от реального браузера. Антифрод-системы (Cloudflare, Akamai, DataDome) блокируют такие запросы на сетевом уровне.

В Syntetic Core используется локальный шлюз `TargetProxy` на базе SOCKS5:
- Браузер (Chromium / Firefox / WebKit) сам устанавливает TLS-рукопожатие через TCP-туннель.
- Целевой сервер видит подлинный TLS-отпечаток реального браузера, полностью соответствующий User-Agent и платформе.
- Исключаются синтетические TLS-аномалии, обеспечивая идеальную маскировку сетевого стека.

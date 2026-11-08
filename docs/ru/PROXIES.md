# Прокси и смена IP через API

[English](../PROXIES.md) · Русская версия

## Три независимые операции

1. **Назначение прокси:** профиль хранит `proxy_id`; credentials задаются в Settings.
2. **Ротация выхода:** API провайдера просит сменить IP физического/логического канала.
3. **Проверка:** ядро наблюдает новый публичный IP через этот прокси.

Новый порт не обязательно означает новый IP. Ответ API `success=true` не означает,
что канал уже переключился. Изменение IP не создаёт новую аппаратную идентичность.

## Поддерживаемый транспорт

`ProxyConfig(server=...)` принимает `http://host:port`, `https://host:port` и
`socks5://host:port`. Credentials задаются отдельными SecretStr. Userinfo в URL
прокси не принимается. Authenticated SOCKS5 отклоняется сохранённым контрактом;
используйте HTTP CONNECT с авторизацией либо SOCKS5 без авторизации.

Пример:

```python
proxy = ProxyConfig(
    id="mobile-1", server="http://proxy.provider.example:28080",
    username=SecretStr(os.environ["PROXY_USERNAME"]),
    password=SecretStr(os.environ["PROXY_PASSWORD"]), kind="mobile",
)
```

Имя провайдера, country/region/asn — метаданные. Они не подтверждают географию
выхода. `ProxyConfig.metadata()` исключает username/password/change_ip_url.

## Универсальный HTTP-адаптер

```python
provider = HttpRotationProvider(
    url=SecretStr(os.environ["ROTATION_API_URL"]),
    method="POST",
    headers={"Authorization": SecretStr(os.environ["ROTATION_AUTHORIZATION"])},
    json_body={"port": 28080},
    success_field="data.success",
    success_value=True,
    timeout_seconds=15,
)
result = await core.rotate_ip(
    "mobile-1", provider,
    probe_url="https://api.ipify.org?format=json",
    timeout_seconds=60,
    poll_seconds=2,
)
```

URL, метод, заголовки, тело и путь поля выбирайте по документации своего тарифа
и API. Это настраиваемый адаптер, а не подтверждённая интеграция с конкретным
поставщиком. Секреты в URL и заголовках скрыты из repr. Тело не выводится в repr,
но не помещайте конфигурацию целиком в логи или публичные отчёты.

При `success_field=None` нужен HTTP 2xx; при заданном поле дополнительно проверяется
JSON-значение и его тип. JSON ограничен 64 КиБ. Редиректы запрещены, HTTPS обязателен,
ambient HTTP_PROXY/HTTPS_PROXY не используются. Запрос ротации не повторяется
автоматически: повтор мог бы запустить вторую смену IP.

## Подтверждение выхода

До запроса снимается старый IP. После запроса с ограниченным интервалом повторяется
probe до появления другого публичного IP. Probe URL должен возвращать plain IP или
поддерживаемый объект JSON с IP и быть разрешён в `allowed_target_hosts`.
Проверка идёт через TargetProxy и назначенный upstream. Временное отключение модема
допускается в пределах общего deadline. Таймаут, неверный ответ или отсутствие
смены завершаются `ProxyUnavailableError` без прямого fallback.

Для проверки до/после можно использовать собственный HTTPS endpoint вместо
публичного IP-сервиса. Он должен наблюдать реальный исходящий адрес соединения.

## Собственный провайдер

```python
class MyProvider:
    async def rotate(self, proxy: ProxyConfig) -> None:
        # Вызовите официальный SDK/API поставщика, дождитесь принятия запроса.
        # При отказе поднимите исключение. Не открывайте здесь браузерную сессию.
        await my_sdk.rotate_port(proxy.id)

result = await core.rotate_ip("mobile-1", MyProvider(), probe_url=probe_url)
```

Метод соответствует `RotationProvider`. Реализация может обращаться к SDK,
подписывать запросы или ожидать provider job. Общий deadline, channel lock и
независимую проверку IP выполняет ядро. Отмена asyncio распространяется наружу.

## Общий модем и конкуренция

```python
core = SynteticCore(
    "data/profiles", settings=settings,
    proxy_channels={"port-1": "modem-A", "port-2": "modem-A"},
)
```

Без mapping ключ строится из endpoint. Для разных портов одного физического
модема обязательно задайте одинаковый channel ID. Все cooperating процессы должны
использовать один profile_root и одну карту каналов. На разных хостах нужен внешний
координатор. Вызов API вручную или сторонним приложением обходит эту защиту.

Lock держится от начала до полного закрытия браузерной сессии. Ротация выполняется
только между сессиями; занятой канал даёт `ProfileLockedError` без запроса провайдеру.
Не вызывайте `rotate_ip` внутри `async with core.session(...)` для того же канала.

Перенесённая политика identity может запрещать быструю смену адреса постоянного
немобильного профиля. Для управляемой мобильной ротации используйте `kind="mobile"`.
Ротация не меняет timezone, locale и геолокацию профиля: выбирайте согласованный
регион у поставщика или создавайте новую согласованную identity.

## Подключение реального сервиса

1. Получите endpoint прокси, credentials, API ротации и информацию об общих каналах.
2. Выберите точную конфигурацию адаптера из документации поставщика.
3. Сохраните секреты в окружении/секретном хранилище своего приложения.
4. Разрешите target/resource/probe хосты.
5. Подтвердите смену IP отдельным вызовом, затем откройте профиль.
6. Проверьте географию и стабильность IP в рамках вашей задачи.

Ключи и платные запросы в этом выделении не использовались. Автоматического
пополнения баланса, заказа/аренды IP, изменения тарифа или перебора аккаунтов нет.

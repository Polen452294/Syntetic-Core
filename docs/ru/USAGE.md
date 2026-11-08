# API и эксплуатация

[English](../USAGE.md) · Русская версия

## SynteticCore

```python
core = SynteticCore(
    profile_root="data/profiles",
    settings=CoreSettings(...),
    proxy_channels={"port-1": "modem-A", "port-2": "modem-A"},
)
```

Один экземпляр предназначен для одного asyncio event loop. Настройки копируются
при создании. Секреты и конфигурация прокси живут в настройках приложения, а не в
`profile.json`. Не меняйте настройки одновременно с активными сессиями.

### capabilities(refresh=False)

Асинхронно проверяет реальные локальные runtime и дополнительные группы API.
Возвращает копию manifest. Первый вызов может занять минуты. Недоступные движки
помечаются, а не заменяются другим движком. `refresh=True` повторяет проверки после
осознанного изменения окружения; обновление браузера существующего профиля может
нарушить identity binding.

### create_profile(...)

```python
persona = await core.create_profile(
    "job-001",                # опционально; без ID генерируется UUID
    family="android",         # desktop / android / ios
    backend="playwright",     # playwright / camoufox
    proxy_id="mobile-1",      # опционально, точный ID из Settings.proxies
    locale="ru-RU",
    timezone_id="Europe/Moscow",
    fresh=False,
)
```

Camoufox допускает desktop. iOS требует Playwright/WebKit на подходящем хосте.
Профиль создаётся один раз. Коллизия ID вызывает `FileExistsError`; отсутствие
совместимого runtime — `RuntimeCompatibilityError`. Произвольные пути и ID с `/`
не принимаются. Вернувшийся `BrowserPersona` можно изучать, но изменение этого
объекта не переписывает сохранённый профиль.

По умолчанию оболочка выбирает постоянное использование: `visit_state=None`.
`fresh=True` сохраняет исходный new/cold-контракт для одноразового визита.

### load_profile(id)

Синхронное чтение конфигурации с проверкой ID/fingerprint/hash. Для больших потоков
вызов можно выполнять через `asyncio.to_thread`. Чтение не запускает браузер и не
возобновляет прошлую сессию. Неудачная проверка не исправляет профиль автоматически.

### session(id, base_url=None)

Асинхронный context manager. Гарантирует закрытие browser context и шлюза при выходе
и исключении. Один профиль нельзя открыть одновременно дважды. Занятый lock
вызывает `ProfileLockedError`, а не скрытое ожидание или запуск временного профиля.

`base_url` нужен для явного `visit_state` нового/повторного посетителя, permissions
и подготовки storage/cache. Для обычного постоянного профиля достаточно
`async with core.session(id)` и затем `session.goto(url)`.

### BrowserSession

| Поле/метод | Назначение |
|---|---|
| `page` | Основная Playwright Page |
| `context` | Playwright BrowserContext; новые вкладки сохраняют общие init scripts |
| `persona` | Снимок сохранённой конфигурации этой сессии |
| `connection` | Фактически наблюдённая среда, runtime и транспорт |
| `behavior` | Перенесённый InteractionBehavior |
| `goto(url)` | Разрешение URL, DOMContentLoaded и проверка окружения |
| `check_environment(page=None)` | Повторное сравнение идентичности и проверка CDP controller |
| `maintain_presence(seconds)` | Явный UX-контур, когда он нужен задаче |

Используя напрямую `page.goto` или popup, вызывайте `check_environment(page)` в
нужных контрольных точках. Сетевой guard действует для всего context; проверка
согласованности после каждого пользовательского действия автоматически не запускается.

## Настройки

| Поле | Смысл |
|---|---|
| `allowed_target_hosts` | Точные хосты целей и необходимых ресурсов |
| `trusted_local_target_hosts` | Явное разрешение локальных/private целей для стендов |
| `browser_headless` | Headless/headful для проверки и новых профилей |
| `browser_start_timeout` | Бюджет подготовки сессии, по умолчанию 30 с |
| `navigation_timeout` | Таймаут навигации, по умолчанию 15 с |
| `action_timeout` | Таймаут действия Playwright, по умолчанию 10 с |
| `camoufox_install_path` | Абсолютный путь закреплённой сборки |
| `experimental_arm64` | Явный допуск ARM64 к реальным проверкам |
| `proxies`, `proxy_required` | Прокси-конфигурация и запрет отсутствующего upstream |
| `network_probe_url` | Дополнительная браузерная проверка сети фабрикой |
| `traffic_optimizer_enabled` | Явное включение сохранённого resource filter |
| `traffic_optimization_level` | `disabled` / `metadata_only` / `strict` |
| `block_stylesheets` | CSS-фильтрация только вместе с разрешённой оптимизацией |

Другие поля `_engine.config.Settings` сохранены для совместимости переносимых
низкоуровневых частей. Включение distributed/archive/shared-storage отклоняется:
реализаций соответствующих сервисов в отдельном ядре нет.

Префикс переменных — `SYNTETIC_CORE_`, разделитель вложенности — `__`:

```powershell
$env:SYNTETIC_CORE_BROWSER_START_TIMEOUT="60"
$env:SYNTETIC_CORE_ALLOWED_TARGET_HOSTS='["example.com","static.example.com"]'
```

JSON-массивы и объекты передаются как JSON-строки. `.env` автоматически не читается:
это предотвращает случайную загрузку конфигурации соседнего проекта. Загружайте
секреты средствами своего приложения или передавайте `CoreSettings(...)` явно.

## Параллельность и повторы

Используйте `asyncio.Semaphore` для ограничения общего числа браузеров и отдельный
profile ID на параллельную задачу. Пример — `examples/parallel_sessions.py`.
Один физический proxy/modem канал сериализуется локальным lock. Разные каналы
могут исполняться параллельно в пределах вашего лимита.

Не повторяйте автоматически действия с побочным эффектом после неопределённого
сетевого результата. Ядро не обещает exactly-once. Для парсинга разумно отдельно
учитывать HTTP-статус, готовность нужного DOM и пустой результат извлечения.

## Низкоуровневые возможности

Для специалистов сохранены модели `BrowserPersona`, `BrowserExperiment`, фабрика
`BrowserContextFactory`, `VisitExperiment`, sensor helpers и identity replay.
Они находятся в `_engine` и требуют явной настройки и проверки совместимости.
Публичный `session()` отклоняет persona с timeline experiment, чтобы не заявлять
его исполнение без координатора. Перенос YAML-моделей не означает наличия прежнего
полного Run/ScenarioRunner, очереди, поискового workflow или инкубации.

Для ручной работы с фабрикой используйте проверенный manifest, неизменный hash,
достоверные origin permissions, ту же политику каналов и обязательное закрытие context.

## Резервное копирование

Завершите активные сессии и скопируйте профиль целиком, включая identity-файлы и
browser-data. Не переносите только cookies как замену полной идентичности.
Сборка браузера и нативная конфигурация могут зависеть от хоста/пути установки;
автоматической миграции между ОС/версиями здесь нет.

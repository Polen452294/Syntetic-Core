# Справочник API и управление антидетект-сессиями

[English](../USAGE.md) · Русская версия

## Главный класс: `SynteticCore`

Основная точка входа для управления профилями, генерации устройств, диагностики антидетект-возможностей и запуска скрытных сессий.

```python
from syntetic_core import CoreSettings, SynteticCore

core = SynteticCore(
    profile_root="data/profiles",
    settings=CoreSettings(
        allowed_target_hosts=["example.com", "api.example.com"],
        browser_headless=False,
    ),
    proxy_channels={"mobile-port-1": "modem-A", "mobile-port-2": "modem-A"},
)
```

Один экземпляр `SynteticCore` используется в рамках одного цикла событий `asyncio`. Настройки проверяются и фиксируются при инициализации.

---

### `capabilities(refresh=False)`

Асинхронно сканирует локальное окружение: бинарные файлы браузеров, поддержку CDP-патчей Chromium, движок Camoufox C++ и кодеки WebKit. Возвращает кэшированный манифест. Параметр `refresh=True` нужен только при намеренном обновлении браузеров на хосте.

---

### `create_profile(...)`

Генерирует полностью связный цифровой профиль устройства, фиксирует уникальные сиды отпечатков и создаёт постоянное хранилище.

```python
persona = await core.create_profile(
    "user-001",               # Идентификатор; при None генерируется UUID
    family="android",         # Семейство: "desktop", "android" или "ios"
    backend="playwright",     # Бэкенд: "playwright" (Chromium/WebKit) или "camoufox" (Firefox)
    proxy_id="mobile-1",      # Опциональный ID прокси из Settings.proxies
    locale="ru-RU",
    timezone_id="Europe/Moscow",
    fresh=False,              # False = постоянный профиль с cookies; True = одноразовый визит
)
```

- **Связная генерация оборудования (Coherence):** Автоматически подбирает совместимые видеокарты, процессоры, экран, плотность пикселей (DPR) и архитектуру Client Hints.
- **Постоянство по умолчанию (`fresh=False`):** Создает постоянную директорию `browser-data/` для сохранения cookies, истории и сессий. Это необходимо для прогрева аккаунтов и высокого рейтинга доверия антифрод-систем.
- **Одноразовый режим (`fresh=True`):** Создает временный изолированный профиль без истории для разовых задач.

---

### `load_profile(id)`

Синхронно считывает `profile.json` и проверяет контрольную сумму SHA-256 (`config_hash`). Защищает профиль от повреждения и несанкционированного изменения отпечатка.

---

### `session(id, base_url=None)`

Асинхронный контекстный менеджер: запускает браузер, активирует скрытный слой, подключает прокси и возвращает управляемый объект сессии.

```python
async with core.session("user-001") as session:
    await session.goto("https://example.com")
    
    # Симуляция человеческого набора текста (с задержками и опечатками)
    await session.behavior.type_text("input[name='q']", "симуляция реальных сессий")
    
    # Движение мыши по естественной кривой Безье с кликом
    await session.behavior.click_element("button[type='submit']")
    
    # Плавный инерционный скроллинг страницы
    await session.behavior.scroll_smooth(delta_y=600)
    
    # Эмуляция присутствия пользователя на странице (поведенческие факторы / ПФ)
    await session.maintain_presence(seconds=4.0)
```

При выходе из блока `async with` ядро автоматически сохраняет все полученные cookies, `localStorage` и `IndexedDB`, корректно завершает процессы браузера и снимает блокировку профиля.

---

## Методы и свойства `BrowserSession`

| Метод / Свойство | Назначение |
|---|---|
| `session.page` | Стандартный объект Playwright `Page` (локаторы, вкладки, события, DOM) с активной защитой от детекта. |
| `session.context` | Стандартный Playwright `BrowserContext` с постоянным хранилищем cookies и кэшем. |
| `session.behavior` | Поведенческий модуль: движения мыши по кривым Безье, набор текста, инерционный скроллинг (ПФ). |
| `session.persona` | Загруженная конфигурация `BrowserPersona` (рецепт оборудования, сиды, платформа). |
| `session.connection` | Параметры текущего сетевого подключения и выходного соединения. |
| `await session.goto(url)` | Переход по URL с проверкой белого списка хостов, ожиданием готовности DOM и валидацией stealth-слоя. |
| `await session.check_environment(page=None)` | Проверка целостности маскировки: подтверждает `navigator.webdriver === false` и активность контроллера воркеров. |
| `await session.maintain_presence(seconds)` | Эмуляция реального присутствия: микродвижения курсора, микроскроллы и удержание внимания на странице. |

---

## Параметры конфигурации (`CoreSettings`)

| Параметр | По умолчанию | Описание |
|---|---|---|
| `allowed_target_hosts` | `[]` | Белый список разрешённых целевых доменов и CDN. |
| `trusted_local_target_hosts` | `[]` | Разрешение локальных/приватных адресов для тестов. |
| `browser_headless` | `False` | Запуск браузера в фоновом (headless) или видимом режиме. |
| `browser_start_timeout` | `30.0` | Лимит времени на запуск браузера, CDP и перехват воркеров. |
| `navigation_timeout` | `15.0` | Таймаут навигации при вызове `session.goto()`. |
| `action_timeout` | `10.0` | Таймаут действий Playwright (клики, ожидание селекторов). |
| `proxies` | `[]` | Список настроенных прокси (`ProxyConfig`). |
| `proxy_required` | `False` | При `True` запрещает запуск без прокси (защита от утечки реального IP). |
| `camoufox_install_path` | `None` | Путь к кастомному бинарнику Camoufox (антидетект Firefox). |
| `traffic_optimizer_enabled` | `False` | Включение фильтрации тяжелых ресурсов, рекламы и трекеров. |

Переменные окружения используют префикс `SYNTETIC_CORE_`:

```powershell
$env:SYNTETIC_CORE_BROWSER_HEADLESS="false"
$env:SYNTETIC_CORE_ALLOWED_TARGET_HOSTS='["example.com","login.example.com"]'
```

---

## Поведенческие факторы и симуляция действий (`session.behavior`)

Модуль `behavior` устраняет роботизированные паттерны взаимодействия, которые анализируют современные антибот-системы:

- **`click_element(selector)`:** Вычисляет центр элемента и ведет курсор мыши по сглаженной кривой Безье с микроколебаниями перед нажатием.
- **`type_text(selector, text, wpm=180, error_rate=0.03)`:** Набирает текст с естественными интервалами между буквами, иногда совершая опечатки и стирая их через Backspace.
- **`scroll_smooth(delta_y, steps=20)`:** Выполняет плавный скроллинг с инерцией и реалистичным замедлением вместо мгновенных скачков.
- **`hover_element(selector)`:** Плавное наведение курсора мыши на элемент.

---

## Резервное копирование и перенос профилей

Поскольку профили персистентны, копирование папки `data/profiles/<id>/` полностью сохраняет личность устройства:
1. `profile.json` (рецепт устройства и сиды)
2. `browser-data/` (все cookies, localStorage, IndexedDB и кэш)
3. `canvas-identity.json` и `session-hardware-identity.json` (сиды отпечатков)

Перед копированием убедитесь, что профиль не активен (файл `.locks/<id>.lock` не заблокирован).

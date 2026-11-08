# Syntetic Core

[English](../../README.md) · Русская версия

**Высокоуровневое антидетект-ядро автоматизации браузерных сессий для симуляции реального человеческого поведения, обхода антифрода (anti-fraud), систем защиты от ботов (anti-bot) и поведенческого анализа.** Название проекта пишется как `Syntetic Core`; имя Python-пакета — `syntetic_core`, консольной команды — `syntetic-core`.

Ядро выделено 8 ноября 2026 года напрямую из производственной системы накрутки поведенческих факторов («ПФ» / Behavioral Factors simulation и обход систем защиты от автоматизации). В проект перенесён полный стек браузерного контура: подмена цифровых отпечатков (fingerprints), связные рецепты реальных устройств, глубокий патчинг CDP и WebWorkers, сохранение и прогрев cookies-хранилищ, нативный TLS-стек и эмуляция человеческих действий (движения мыши по кривым Безье, набор текста с опечатками, инерционный скроллинг).

Комплекс спроектирован для надежного обхода современных систем обнаружения автоматизации и антифрод-защит, включая **Cloudflare Turnstile / Bot Management, DataDome, Akamai Bot Manager, Kasada, Yandex SmartCaptcha и Антифрод, Google reCAPTCHA v2/v3/Enterprise, CreepJS, FingerprintJS Pro и Pixelscan**.

## Ключевые возможности

- **Реальные браузерные движки:** Поддержка Playwright **1.62.0** (со специальным патчем владения целями CDP), **Camoufox 0.5.8** (усиленный антидетект-сборка Firefox с модификацией движка на уровне C++) и нативный **WebKit** (для достоверной эмуляции iOS и macOS).
- **Полный спектр подмены цифровых отпечатков (Fingerprint Spoofing):**
  - **Защита Canvas 2D:** Детерминированный микросдвиг сабпиксельного рендеринга текста (±0.02 px) для каждого профиля. Исключает кластеризацию одинаковых хешей Canvas, не создавая подозрительных синтетических аномалий энтропии.
  - **Подмена WebGL 1 и 2:** Реалистичные unmasked vendor, unmasked renderer, расширения и лимиты контекста, строго привязанные к аппаратным характеристикам выбранного рецепта видеокарты.
  - **Web Audio API:** Стабильный математический шум, подмешиваемый при чтении буферов AudioBuffer и параметров DynamicsCompressor, предотвращающий снятие аудиоотпечатка.
  - **Client Hints (`Sec-CH-UA`):** Достоверные версии браузерных брендов, полные списки версий, платформа, архитектура, битность и флаги мобильности, согласованные между HTTP-заголовками и JavaScript API.
  - **Аппаратные метрики железа:** Реалистичные значения `navigator.hardwareConcurrency` (ядра CPU) и `navigator.deviceMemory` (объем RAM), соответствующие рецепту устройства.
  - **Батарея и медиа-устройства:** Корректный статус `BatteryManager` и устойчивые списки `enumerateDevices` (камеры, микрофоны, аудиовыходы) с правдоподобными идентификаторами.
  - **Системные голоса и шрифты:** Наборы синтеза речи (`speechSynthesis`), соответствующие целевой ОС и языку, а также фильтрация шрифтов через `FontFaceSet`, предотвращающая утечку реальных шрифтов ОС хоста.
  - **Датчики и мультитач:** Полноценный 5-точечный мультитач на мобильных пресетах, а также эмуляция акселерометра, гироскопа и магнитометра через CDP.
- **Устранение утечек CDP и признаков автоматизации:**
  - Патч драйвера Playwright, устраняющий конфликты и гонки при перехвате владения целями (targets) в Chromium.
  - Полная нейтрализация `navigator.webdriver` (строго `false`), удаление флагов автоматизации и скрытых свойств Chromium (таких как `cdc_`, инспекторные хуки).
  - Слой Proxy и WeakMap, маскирующий все переопределённые JS-функции и геттеры под нативный код: `Function.prototype.toString` возвращает `function () { [native code] }`.
- **Ранняя инициализация WebWorkers до выполнения скриптов:**
  - Контроллер CDP рекурсивно перехватывает создание всех типов воркеров: DedicatedWorker, SharedWorker, ServiceWorker и NestedWorker.
  - Воркеры приостанавливаются на этапе запуска: в них внедряются корректные Client Hints, параметры CPU, памяти, userAgent и WebGL offscreen canvas до того, как начнет выполняться любой сторонний код детекта.
- **Постоянные профили, сохранение Cookies и прогрев (Warming):**
  - Непрерывное сохранение cookies, `localStorage`, `sessionStorage`, `IndexedDB` и дискового кэша браузера.
  - Возможность последовательного прогрева профилей и накопления доверия (trust score) антифрод-систем для прохождения проверок без повторной авторизации и капч.
  - Контроль целостности через хеши конфигурации SHA и файловые блокировки операционной системы (`ProfileLock`).
- **Связные рецепты устройств (Device Coherence, более 1000 пресетов):**
  - Жёсткая взаимная согласованность: операционная система, процессор, видеокарта, геометрия экрана, viewport, DPR и архитектура Client Hints не могут противоречить друг другу.
  - Исключаются невозможные комбинации, мгновенно выдающие бота (например, видеокарта Apple на Windows, мобильный юзерагент без тач-интерфейса, нестыковка DPR и разрешений).
  - Каталог включает Windows, macOS (Apple Silicon M1/M2 и Intel), Linux, iPhone/iPad, Android (сотни точных моделей Samsung Galaxy, Google Pixel, Xiaomi, OnePlus) и складные экраны.
- **Эмуляция человеческого поведения (ПФ — Поведенческие Факторы):**
  - Естественные траектории курсора мыши по кривым Безье с микроколебаниями, случайными ускорениями и промахами.
  - Реалистичный набор текста с индивидуальными задержками между клавишами, случайными опечатками и их исправлением.
  - Инерционный скроллинг с реалистичным замедлением и паузами на чтение контента.
  - Встроенный диспетчер фоновой активности `UXActivityDispatcher` и метод `maintain_presence()` для удержания времени на странице.
- **Мобильные прокси, смена IP и защита сети:**
  - **Нативный браузерный TLS:** Браузер сам устанавливает TLS-соединение через TCP-туннель, сохраняя подлинные браузерные отпечатки JA3/JA4/TLS без аномалий TLS-библиотек Python.
  - Локальный SOCKS5 target proxy с жестким белым списком разрешённых доменов.
  - Блокировка аппаратных каналов модемов (`proxy_channels`), исключающая одновременную ротацию портов, висящих на одном физическом модеме.
  - Ротация мобильных IP через HTTP API провайдера с обязательной проверкой смены внешнего IP через контрольный зонд перед открытием сессии.

> [!NOTE]
> Локальный запуск ядра не требует PostgreSQL, Redis, FastAPI, Dashboard или Docker. Сервисы очередей, распределённый mesh-кластер и внешние сервисы решения капч остались в родительской инфраструктуре.

## Требования

- Python **3.12+**.
- Проверено и оптимизировано для **Windows x86-64** и **Linux x86-64**.
- Linux ARM64 требует совместимых бинарных файлов и параметра `experimental_arm64=True`.
- Движок WebKit требует Linux или macOS (на Windows запуск WebKit аппаратно запрещён политикой безопасности).

## Установка

### Windows PowerShell

Из корневой папки проекта:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -c requirements.lock -e ".[dev]"
syntetic-core prepare --engine chromium
```

### Linux / macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -c requirements.lock -e '.[dev]'
python -m playwright install --with-deps chromium
python -c 'from syntetic_core.cli import install; install()'
```

Команда `prepare` скачивает браузер Playwright и применяет критически важный патч владения воркерами Playwright **1.62.0**.

Инструкции по настройке Camoufox (антидетект Firefox) и WebKit приведены в [INSTALLATION.md](INSTALLATION.md).

## Быстрый старт (CLI)

Проверка окружения и открытие антидетект-сессии:

```bash
# Диагностика локальных движков и возможностей подмены
syntetic-core doctor

# Создание профиля со связным рецептом устройства
syntetic-core create --id my-stealth-profile --family desktop --backend playwright

# Открытие страницы с авторизацией хоста
syntetic-core --allow-host example.com open my-stealth-profile https://example.com
```

Разрешение хостов задаётся строго явно флагом `--allow-host`. Разрешение `example.com` не разрешает автоматически поддомены или внешние CDN без явного указания.

## Python API: Автоматизация и управление сессиями

```python
import asyncio
from syntetic_core import CoreSettings, SynteticCore

async def main():
    # Инициализация ядра с контролем разрешённых хостов
    core = SynteticCore(
        "data/profiles",
        settings=CoreSettings(allowed_target_hosts=["example.com"]),
    )

    # Создаём профиль один раз; при повторном запуске используем сохранённый ID
    try:
        core.load_profile("user-01")
    except FileNotFoundError:
        # Генерирует согласованный рецепт оборудования и уникальные seed-значения
        await core.create_profile("user-01", family="desktop")

    # Открываем сессию с полным скрытием автоматизации и защитой отпечатков
    async with core.session("user-01") as session:
        # goto() проверяет белый список, готовность DOM и отсутствие детекта CDP
        await session.goto("https://example.com")
        
        # Объекты session.page и session.context являются стандартными объектами Playwright
        print("Заголовок страницы:", await session.page.title())
        
        # Эмуляция человеческого присутствия на странице (поведенческие факторы)
        await session.maintain_presence(seconds=5.0)

asyncio.run(main())
```

Внутри контекста `session` вам доступны стандартные возможности Playwright: локаторы, перехват ответов, вкладки, скачивание файлов и вычисление JS. Все открываемые страницы автоматически защищены отпечатками и скриптами маскировки под реального пользователя.

### Постоянные и одноразовые профили

- **Постоянные профили (по умолчанию):** Хранят cookies, сессионные данные и кэш между перезапусками. Необходимы для прогрева аккаунтов, долгосрочных сессий и накопления доверия антифрода.
- **Одноразовые профили (`fresh=True`):** Создают полностью чистый профиль без истории для изолированных разовых проверок.

## Эмуляция мобильных устройств, Camoufox и WebKit

```python
# Android-профиль (Samsung Galaxy, Google Pixel и др.)
await core.create_profile("android-user", family="android", backend="playwright")

# Camoufox: Усиленный антидетект Firefox с маскировкой на уровне движка C++
await core.create_profile("firefox-stealth", family="desktop", backend="camoufox")

# iOS WebKit (только Linux/macOS):
await core.create_profile("iphone-user", family="ios", backend="playwright")
```

При отсутствии поддержки запрошенной платформы ядро выбросит исключение `RuntimeCompatibilityError`, не подменяя движок незаметно на неподходящий.

## Мобильные прокси и подтверждённая ротация IP

```python
import os
from pydantic import SecretStr
from syntetic_core import CoreSettings, HttpRotationProvider, ProxyConfig, SynteticCore

proxy = ProxyConfig(
    id="mobile-modem-1",
    server=os.environ["PROXY_SERVER"],
    username=SecretStr(os.environ["PROXY_USERNAME"]),
    password=SecretStr(os.environ["PROXY_PASSWORD"]),
    kind="mobile",
)

core = SynteticCore(
    settings=CoreSettings(
        proxies=[proxy],
        proxy_required=True,
        allowed_target_hosts=["example.com", "api.ipify.org"],
    ),
    proxy_channels={"mobile-modem-1": "modem-hardware-channel-A"},
)

provider = HttpRotationProvider(
    url=SecretStr(os.environ["ROTATION_API_URL"]),
    method="POST",
    headers={"Authorization": SecretStr(os.environ["ROTATION_AUTHORIZATION"])},
)

# Вызов смены IP между сессиями с проверкой нового выхода:
# result = await core.rotate_ip("mobile-modem-1", provider, probe_url="https://api.ipify.org?format=json")
# print("Новый подтверждённый IP:", result.new_ip)
```

Ротация считается завершённой только после того, как тестовый запрос через прокси подтвердил появление другого публичного IP-адреса. При любых сбоях прокси ядро никогда не производит сброс на прямое подключение без прокси.

## Примеры

| Файл | Назначение |
|---|---|
| [parse_page.py](../../examples/parse_page.py) | Сбор данных со страницы с постоянным профилем |
| [parallel_sessions.py](../../examples/parallel_sessions.py) | Параллельный запуск изолированных сессий с лимитом потоков |
| [rotate_ip.py](../../examples/rotate_ip.py) | Ротация мобильного IP через API с проверкой выхода и открытие Android-профиля |

## Документация

- [Архитектура и жизненный цикл](ARCHITECTURE.md)
- [Данные эмуляции, отпечатки и слои защиты](EMULATION.md)
- [API, настройки и управление профилями](USAGE.md)
- [Прокси, блокировка модемов и ротация IP](PROXIES.md)
- [Установка и окружение](INSTALLATION.md)
- [Диагностика и решение проблем](TROUBLESHOOTING.md)
- [Происхождение ядра и история выделения из ПФ](EXTRACTION.md)
- [Навык для Codex и Claude Code](AGENT_SKILLS.md)
- [Результаты верификации тестов](VERIFICATION.md)

## Использование в качестве навыка агентов (Codex и Claude Code)

```bash
python tools/install_agent_skills.py --agent both
```

Вызывается как `$syntetic-core` в Codex или `/syntetic-core` в Claude Code.

## Проверка и тестирование

```bash
# Модульные тесты
python -m pytest -m 'not browser' -q

# Линтеры и типизация
python -m ruff check src tests tools examples skills
python -m ruff format --check src tests tools examples skills
python -m mypy

# Реальный тест браузера на локальном фикстур-сервере
$env:SYNTETIC_CORE_RUN_BROWSER="1"
python -m pytest tests/test_browser.py -q
```

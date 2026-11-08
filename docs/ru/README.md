# Syntetic Core

[English](../../README.md) · Русская версия

**Самостоятельное Python-ядро автоматизации браузерных сессий с постоянными,
согласованными профилями устройств.** Название проекта намеренно пишется `Syntetic Core`;
имя Python-пакета — `syntetic_core`, команды — `syntetic-core`.

Проект выделен из локального Synthetic Sessions 8 ноября 2026 года. Он переносит
существующий браузерный механизм: генерацию рецептов устройств, Chromium/CDP,
Camoufox/Firefox, WebKit/iOS, JavaScript-эмуляцию API, проверку окружения,
изолированное хранилище и поведенческие инструменты. Это копия конкретного среза
реализации с самостоятельным внешним API, а не новая упрощённая модель отпечатка.

Ядро полезно для парсинга динамических страниц, повторяемого тестирования мобильной
вёрстки, длительных авторизованных сессий, сбора данных через UI и автоматизации
личных рабочих процессов. Постоянные cookies и localStorage сокращают повторную
авторизацию и настройку сайта. Согласованная конфигурация уменьшает случайные
расхождения окружения между визитами. Скорость и успешность зависят от сайта,
браузера, сети и ресурсов; сравнительного бенчмарка ускорения парсинга пока нет.

## Что входит

- Реальные браузерные движки через Playwright **1.62.0** и Camoufox **0.5.8**.
- Desktop Windows/macOS/Linux, Android, iPhone/iPad и поддерживаемые складные пресеты.
- Связанный выбор ОС, модели, геометрии, DPR, CPU, GPU и архитектуры Client Hints.
- Общий слой Canvas, представления функций, webdriver и аппаратных API Chromium.
- Отдельная ранняя настройка dedicated/shared/service/nested Workers Chromium.
- Постоянные профили с проверкой хеша, сохранёнными seed и блокировкой файлов.
- Нативный браузерный TLS через локальный SOCKS5-шлюз с точными разрешениями хостов.
- Настроенные HTTP/HTTPS/SOCKS5-прокси и расширяемая смена IP через HTTP API.
- Поведенческие инструменты ввода, движения, прокрутки и явной UX-активности.
- Нативные фильтры ресурсов и низкоуровневые инструменты живых QA-условий/replay.

PostgreSQL, Redis, FastAPI-сервер, Dashboard и Docker для локального использования
не нужны. Контроллер, распределённые leases, S3/Mesh, инкубация cookies, квоты,
внешняя аналитика и сервис распознавания проверок доступа остались в исходном продукте.

## Требования

Python **3.12+**. Для практического старта проверен Windows x86-64 с Chromium.
Linux x86-64 — основной серверный вариант исходной системы. Linux ARM64 требует
совместимых бинарников и `experimental_arm64=True`. Код macOS перенесён, но в новом
проекте на macOS не проверен. WebKit на Windows запрещён независимо от целевой ОС.

Установка браузеров и патч драйвера — явный подготовительный шаг. Сессии не
скачивают браузеры и не меняют живой драйвер автоматически.

## Установка

Windows PowerShell, из каталога проекта:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -c requirements.lock -e ".[dev]"
syntetic-core prepare --engine chromium
```

Linux/macOS:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -c requirements.lock -e '.[dev]'
python -m playwright install --with-deps chromium
python -c 'from syntetic_core.cli import install; install()'
```

`prepare` устанавливает Playwright-браузер и проверенный патч владения Worker targets.
Патч совместим строго с Playwright 1.62.0; для другой версии требуется новая проверка.
Смена версии браузера может потребовать нового профиля.

Дополнительная установка Camoufox и WebKit описана в [INSTALLATION.md](INSTALLATION.md).

## Первый запуск

Проверка выполняет настоящие локальные browser smoke-тесты и может занять несколько минут:

```bash
syntetic-core doctor
syntetic-core create --id catalog --family desktop --backend playwright
syntetic-core --allow-host example.com open catalog https://example.com
```

Хосты задаются явно. `example.com` приведён как короткая демонстрация; для реального
парсинга разрешите точные домены своего целевого сайта и необходимых ресурсов.
Разрешение `example.com` не разрешает `www.example.com` или все его поддомены.

## Python API: парсинг

```python
import asyncio
from syntetic_core import CoreSettings, SynteticCore

async def main():
    core = SynteticCore(
        "data/profiles",
        settings=CoreSettings(allowed_target_hosts=["example.com"]),
    )
    # Создать один раз. При следующих запусках используйте прежний ID.
    try:
        core.load_profile("catalog")
    except FileNotFoundError:
        await core.create_profile("catalog", family="desktop")

    async with core.session("catalog") as session:
        await session.goto("https://example.com")
        print(await session.page.locator("h1").all_text_contents())
        links = await session.page.locator("a[href]").evaluate_all(
            "nodes => nodes.map(a => ({text:a.textContent.trim(), url:a.href}))"
        )
        print(links)

asyncio.run(main())
```

`session.page` и `session.context` — обычные объекты Playwright. Доступны локаторы,
ожидание ответов, вкладки, загрузки и DOM-извлечение. `session.goto()` дополнительно
проверяет разрешение адреса и согласованность окружения после навигации.

Профиль по умолчанию допускает повторные визиты и сохраняет браузерное состояние.
Для одноразовой проверки нового посетителя используйте `create_profile(..., fresh=True)`
и передайте `base_url` в `session()`. Повторное использование такого профиля отклоняется.
Новый профиль получает новую идентичность; существующий не перегенерируется.

## Android, iOS и Camoufox

```python
await core.create_profile("android", family="android", backend="playwright")
await core.create_profile("desktop-firefox", family="desktop", backend="camoufox")
# Только Linux/macOS с реально проверенным WebKit и нативным медиастеком:
await core.create_profile("iphone", family="ios", backend="playwright")
```

Недоступный режим приводит к ошибке совместимости. Ядро не подменяет WebKit Chromium
и не открывает профиль другой браузерной сборкой незаметно для вызывающего кода.

## Прокси и смена IP

```python
import os
from pydantic import SecretStr
from syntetic_core import CoreSettings, HttpRotationProvider, ProxyConfig, SynteticCore

proxy = ProxyConfig(
    id="mobile-1",
    server=os.environ["PROXY_SERVER"],
    username=SecretStr(os.environ["PROXY_USERNAME"]),
    password=SecretStr(os.environ["PROXY_PASSWORD"]),
    kind="mobile",
)
core = SynteticCore(settings=CoreSettings(
    proxies=[proxy], proxy_required=True,
    allowed_target_hosts=["example.com", "api.ipify.org"],
))
provider = HttpRotationProvider(
    url=SecretStr(os.environ["ROTATION_API_URL"]),
    method="POST",  # Выберите метод по документации своего провайдера.
    headers={"Authorization": SecretStr(os.environ["ROTATION_AUTHORIZATION"])},
    # При необходимости: success_field="data.success", success_value=True
)
# В async-функции, между сессиями:
# result = await core.rotate_ip("mobile-1", provider,
#                               probe_url="https://api.ipify.org?format=json")
# await core.create_profile("mobile-profile", family="android", proxy_id="mobile-1")
```

Ротация подтверждается новым публичным IP через назначенный прокси. Ответ API
провайдера сам по себе не считается доказательством. Активная сессия держит блокировку
канала; попытка ротации занятого канала немедленно завершается ошибкой. Прямого
fallback после ошибки прокси нет. Полный рабочий пример —
[examples/rotate_ip.py](../../examples/rotate_ip.py), контракт расширения — [PROXIES.md](PROXIES.md).

## Примеры

| Файл | Назначение |
|---|---|
| [parse_page.py](../../examples/parse_page.py) | Извлечение заголовков и ссылок в JSON |
| [parallel_sessions.py](../../examples/parallel_sessions.py) | Ограниченная параллельность с отдельным профилем на задачу |
| [rotate_ip.py](../../examples/rotate_ip.py) | API-ротация, проверка IP и открытие Android-сессии |

## Документация

- [Установка и платформы](INSTALLATION.md)
- [Архитектура и жизненный цикл](ARCHITECTURE.md)
- [Все группы подменяемых данных и границы](EMULATION.md)
- [API, настройки и работа с профилями](USAGE.md)
- [Прокси и API провайдеров](PROXIES.md)
- [Диагностика проблем](TROUBLESHOOTING.md)
- [Происхождение и отличия от исходного проекта](EXTRACTION.md)
- [Навык для Codex и Claude Code](AGENT_SKILLS.md)
- [Результаты проверок](VERIFICATION.md)

## Использование как навыка

```bash
python tools/install_agent_skills.py --agent both
```

В Codex вызывайте `$syntetic-core`, в Claude Code — `/syntetic-core`. Общий навык
включает помощник запуска и wheel для работы без исходной папки проекта.
Каталоги установки и порядок обновления описаны в [инструкции](AGENT_SKILLS.md).

## Проверки и сборка

```bash
python -m pytest -m 'not browser' -q
python -m ruff check src tests tools examples skills
python -m ruff format --check src tests tools examples skills
python -m mypy
python -m build
```

Настоящий браузерный тест запускается явно на локальном HTTP-стенде:

```powershell
$env:SYNTETIC_CORE_RUN_BROWSER="1"
python -m pytest tests/test_browser.py -q
```

На Linux: `SYNTETIC_CORE_RUN_BROWSER=1 python -m pytest tests/test_browser.py -q`.

## Ограничения и права

Это эмуляция браузерного окружения, а не запуск Android/iOS или виртуальная машина
соответствующей ОС. Она не гарантирует неотличимость от физического устройства,
нового человека или прохождение проверок стороннего сайта. Реальные GPU-лимиты,
производительность, часть Worker API и рендеринг остаются свойствами хоста.
Используйте ядро для ресурсов и действий, на которые у вас есть разрешение.

Секреты, профили, cookies и модельные данные не включаются в дистрибутив. У этого
выделенного проекта пока не назначена отдельная открытая лицензия; сведения о
происхождении и зависимостях находятся в [NOTICE.md](../../NOTICE.md) и
[THIRD_PARTY.md](../../THIRD_PARTY.md). Перед распространением выберите условия для
собственного кода и учтите лицензии зависимостей.

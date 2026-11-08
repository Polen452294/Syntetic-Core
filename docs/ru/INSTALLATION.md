# Установка и подготовка браузеров

[English](../INSTALLATION.md) · Русская версия

## Зависимости

Python 3.12+, pip и отдельное виртуальное окружение.
`pip install -c requirements.lock -e .` устанавливает Python-зависимости;
`pip install -c requirements.lock -e '.[dev]'` добавляет тесты, Ruff, mypy и сборку.
Браузерные бинарники не включены в wheel. Прямые версии зафиксированы в pyproject,
полный снимок транзитивных зависимостей — в `requirements.lock`.

| Инструмент | Роль |
|---|---|
| Playwright 1.62.0 | BrowserContext/Page, эмуляция, CDP и реальные браузеры |
| Camoufox 0.5.8 | Нативные сохранённые Firefox fingerprints |
| BrowserForge 1.2.4 | Зависимость генерации fingerprints; не самостоятельная JS-подмена |
| Pydantic / pydantic-settings | Схемы, проверка конфигурации и env |
| httpx[socks] | HTTP API провайдеров и вспомогательные операции |
| websockets | Отдельное CDP-соединение Chromium |
| PyYAML | Перенесённые низкоуровневые модели сценариев |
| psutil | Процессные/ресурсные наблюдения внутри перенесённого слоя |
| tzdata | Переносимые IANA timezone, в том числе Windows |
| pytest / Ruff / mypy / build | Регрессия, стиль, типы и wheel/sdist |

## Chromium

```bash
syntetic-core prepare --engine chromium
```

Команда устанавливает Chromium под закреплённую версию Playwright и меняет только
драйвер Playwright установленного Python-окружения. Для Linux системные библиотеки
устанавливаются отдельно: `python -m playwright install --with-deps chromium`.
После этого выполните `python -c 'from syntetic_core.cli import install; install()'`.

Для приближения системного набора шрифтов к исходному Linux-образу отдельно
установите `fonts-roboto` и `fonts-noto-color-emoji` пакетным менеджером вашей ОС.
JS-фильтрация списка шрифтов не устанавливает шрифты и не заменяет их CSS-метрики.

Подготовка идемпотентна. Не применяйте её к окружению работающих сессий: сначала
остановите их. Неподдерживаемый layout/version завершает подготовку ошибкой.
Списки Playwright `page.workers` не являются полным реестром targets, которыми
владеет отдельный Chromium controller.

## Camoufox

Из исходного проекта перенесены `tools/setup_browser.py` и `tools/browser-release.json`.
Installer проверяет SHA-256 закреплённого архива `156.0.1-beta.35`, не принимает
автоматически другую сборку и готовит fingerprint-модель, включая Unicode-пути Windows.

```bash
python tools/setup_browser.py --install-dir build/native-browser
```

Затем передайте абсолютный путь:

```python
from pathlib import Path
from syntetic_core import CoreSettings

settings = CoreSettings(camoufox_install_path=Path("build/native-browser").resolve())
```

Для установки только данных модели: `python tools/setup_browser.py --prepare-data-only`.
Это отдельная загрузка; одной установки пакета camoufox недостаточно. При установке
из wheel installer возьмите из исходного дистрибутива/sdist проекта.

## WebKit / iOS

```bash
python -m playwright install --with-deps webkit
syntetic-core doctor
```

На Linux необходимы GStreamer и кодеки, соответствующие Playwright WebKit. Проверки
WebAudio/MediaDevices/SpeechSynthesis и WAV/H.264/AAC должны пройти до объявления
`webkit_full_native_v1`. Для native content filter нужен C-компилятор и системный
loader; C-исходник поставляется в пакете и собирается для текущей архитектуры.

Windows WebKit запрещён. Поле целевой ОС и наличие бинарника запрет не отменяют.
Новая macOS-проверка в выделенном проекте пока не выполнялась.

## Linux ARM64

```python
settings = CoreSettings(experimental_arm64=True, production_mode=False)
```

Должны реально работать бинарники движков, дисплей при headful и нативные расширения.
Свидетельства исходного Pi не являются автоматической приёмкой отдельного пакета.

## Headful и ограничения запуска

Для оконного режима: `CoreSettings(browser_headless=False)`. На Linux нужен рабочий
DISPLAY или отдельно настроенный Xvfb. Наличие модели headful в коде не заменяет smoke.

Перенесённая фабрика сохраняет Chromium launch flags исходного продукта, включая
`--disable-gpu` и `--no-sandbox`. Последний предполагает доверенный контент и
изолированное окружение исполнителя. Полноценный supervisor/cgroups и Docker sandbox
исходной платформы не входят в этот пакет. Для недоверенного контента требуется
отдельно подготовленный изолированный исполнитель и проверенная политика sandbox.

## Отсутствие зависимостей от исходной папки

После установки новый проект импортирует только `syntetic_core`, стандартную
библиотеку и указанные зависимости. От исходного проекта не нужны `.env`, БД,
профили, бинарники в его build-каталоге или исполняемые Python-модули.
Браузерный cache Playwright может быть общим для пользователя ОС; это штатное
хранилище установленных бинарников, а не связь с исходным проектом.

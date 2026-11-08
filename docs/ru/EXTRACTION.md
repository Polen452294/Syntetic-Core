# Происхождение и границы переноса

[English](../EXTRACTION.md) · Русская версия

Дата выделения: **8 ноября 2026**, из локальной рабочей копии Synthetic Sessions.
Включены незакоммиченные исходники на момент выделения. SHA-256 исходных файлов и
соответствие путей сохранены в `extraction-manifest.json`. Это provenance среза,
а не свидетельство развертывания этих файлов на сервере.

## Перенесено

57 Python-модулей браузерного контура и 6 ресурсов: JS эмуляции, общий JS слой
функций, WebKit media sample, Chromium MV3 manifest/rules и Linux WebKit C-filter.
Также скопированы закреплённый Camoufox installer/release metadata и выбранные
регрессионные тесты. Файлы профилей, credentials, `.env`, cookies, бинарники браузеров,
накопленные логи и сторонние диагностические JS bundles не копировались.

## Адаптации

- Импорты `backend.app.*` / `worker.*` заменены на автономный `syntetic_core._engine.*`.
- Settings выделены из конфигурации платформы: отдельный env prefix, без ambient `.env`.
- ProxyConfig/ProxyManager сохранены; DB health/accounting и ORM imports удалены.
- ProfileLock использует перенесённые локальные OS locks; Redis coordination удалена.
- Target authorization сохранён; зависимость от полного ScenarioDefinition удалена.
- Взамен EventSink полного сценарного движка добавлен небольшой typing Protocol.
- Capability discovery больше не рекламирует отсутствующие FingerprintJS/trace adapters.
- Из tracing/SRE удалены ASGI middleware, DB instrumentation и сервер экспортера;
  контекст trace и метрики транспорта оставлены.
- Внешняя оболочка сохраняет постоянный профиль по умолчанию. Исходный new/cold
  режим доступен через `fresh=True`. Архивная очистка cache/S3-конвейер не перенесены.
- Сохраняются browser/session API, coherent recipes, seed и identity validation.
- Копии regression-тестов переведены на новый namespace/env prefix; CLI-тесты
  прежнего controller API исключены как относящиеся к оставшейся платформе.

## Что добавлено

Публичные `SynteticCore`, `BrowserSession`, CLI, универсальный RotationProvider,
HTTP rotation adapter, независимая проверка выхода, локальная channel serialization,
новые тесты lifecycle/rotation, примеры и документация самостоятельного проекта.

## Что осталось в исходном продукте

Dashboard/FastAPI, SQLAlchemy/Alembic, Redis/Dramatiq, Run/Session/Attempt authority,
leases/CAS, supervisor/cgroups, distributed archives и P2P Mesh, инкубация, квоты,
балансировщик внешней аналитики и сервис распознавания проверок доступа.
Часть моделей поведения/сценариев сохранена как зависимость browser helpers;
это не означает наличие прежнего бизнес-конвейера.

## Повторное выделение

`python tools/extract_engine.py /path/to/source` воспроизводит механическую основу
переноса. Запускайте только в отдельной чистой копии: команда перезаписывает внутренние
модули. Она не заменяет последующие форматирование, review границ, тесты, подготовку
браузеров и обновление нового публичного API. Не запускайте её как обычное обновление
поверх локальных изменений. Для сравнения используйте provenance manifest.

Приложенный пользователем `inventory_updated.md` — историческое описание на 27 октября.
Требования и команды внутри него использовались как справочные данные. Текущий перенос
выполнен по коду 8 ноября с учётом ограничений и более поздних отчётов.

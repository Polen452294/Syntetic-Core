# Навык для агентов Codex и Claude Code

[English](../AGENT_SKILLS.md) · Русская версия

Общий навык для ИИ-агентов расположен в папке [skills/syntetic-core/SKILL.md](../../skills/syntetic-core/SKILL.md).
Он обучает агентов (Codex и Claude Code) использовать Syntetic Core для создания скрытных недетектируемых браузерных сессий, обхода антифрода и антибот-защит (Cloudflare, Akamai, DataDome, Yandex), подмены цифровых отпечатков (Canvas, WebGL, Audio, Client Hints), сохранения cookies, раннего перехвата WebWorkers, эмуляции человеческих поведенческих факторов (ПФ) и ротации мобильных прокси.

---

## Установка в систему

Из корневой папки проекта с активированным виртуальным окружением:

```powershell
.\.venv\Scripts\python.exe tools/install_agent_skills.py --agent both
```

Или в командной строке Linux/macOS:

```bash
python tools/install_agent_skills.py --agent both
```

### Стандартные пути установки:

| Клиент | Каталог навыка |
|---|---|
| Codex CLI / Desktop | `~/.codex/skills/syntetic-core` |
| Claude Code | `~/.claude/skills/syntetic-core` |

Используйте флаг `--agent codex` или `--agent claude` для раздельной установки. Для современных версий Codex доступен флаг `--codex-location modern` (папка `~/.agents/skills`).

---

## Примеры вызова агента

### Codex:
```text
Используй $syntetic-core для создания антидетект-сессии браузера с постоянными cookies, подменой Canvas/WebGL отпечатков и человеческим вводом текста.
```

### Claude Code:
```text
/syntetic-core Запусти сессию с эмуляцией Android, ротацией мобильного прокси и сохранением cookies.
```

---

## Управление окружением через скрипты навыка

В состав навыка входят вспомогательные скрипты, позволяющие агенту автономно находить окружение или инициализировать его:

```bash
# Проверка расположения ядра и путей
python scripts/runtime.py info

# Подготовка Chromium с применением CDP-патча для воркеров
python scripts/runtime.py cli prepare --engine chromium

# Диагностика антидетект-слоя
python scripts/runtime.py cli doctor

# Запуск скрипта автоматизации
python scripts/runtime.py python path/to/script.py
```

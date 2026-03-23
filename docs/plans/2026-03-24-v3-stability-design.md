# ClawForge v3 — Stability & Correctness

**Дата:** 2026-03-24
**Статус:** Approved

---

## Контекст

Система работает, агенты создаются и используются. Но в ходе эксплуатации и код-ревью выявлены баги, уязвимости и архитектурные пробелы, которые нужно закрыть.

## 1. Фикс роутинга /new (switch_agent)

**Проблема:** После `/main` + `/new` агент попадает не к architect, а к последнему активному агенту. `openclaw config set bindings '[]'` создаёт сессию с `accountId: "default"`, а `/new` ищет сессию по конкретному accountId.

**Корневая причина:** Подтверждено диагностикой на сервере — `accountId` в сессии main = `"default"`, а у созданного агента = `"541534272"`. `/new` матчит по конкретному ID.

**Решение:** Заменить в `deploy.py:switch_agent` механизм переключения:
- `openclaw config set bindings '[]'` — очистить старое
- `openclaw agents bind --agent <name> --bind telegram:<userId>` — привязать нового

Это гарантирует правильный accountId в сессиях для любого агента.

**Файлы:** `src/deploy.py`

## 2. Фикс JSON-парсера

**Проблема:** Когда developer генерирует SOUL.md с тройными бэктиками внутри JSON-значения, `parse_json_response` ошибочно режет JSON по бэктикам из контента soul_md. Подтверждено в pipeline.log — все 3 попытки доработки thesis_maker упали на `parse_error: Expecting value: line 1 column 1 (char 0)`.

**Решение:** Сначала пробовать прямой `json.loads(text)`, и только при неудаче — снимать code blocks. Защищает весь пайплайн (analyst, developer, tester, validator).

**Файлы:** `src/orchestration.py`

## 3. extend_existing — обновление SOUL.md

**Проблема:** `deploy_extension` обрабатывает только skills и heartbeats, но игнорирует `artifacts["soul_md"]`. При запросе "доработай агента" SOUL.md не обновляется.

**Решение:** Добавить запись `soul_md` в workspace агента в `deploy_extension`. Добавить `update_agent_workspace` в `deploy.py`.

**Файлы:** `src/orchestration.py`, `src/deploy.py`

## 4. Stale tester/validator prompt

**Проблема:** `tester_prompt` строится f-строкой ДО while-цикла. После того как developer исправляет артефакты, тестер проверяет старую версию. То же с validator prompt.

**Решение:** Вынести построение промптов в функции `build_tester_prompt()` и `build_validator_prompt()`, вызывать внутри циклов.

**Файлы:** `src/orchestration.py`

## 5. Защитные фиксы

### 5a. SQL injection в registry.py

**Проблема:** `f"UPDATE agents SET {key} = ?"` — имя столбца через f-строку.

**Решение:** Whitelist допустимых колонок + context managers для DB connections.

**Файлы:** `src/registry.py`

### 5b. Shell injection в deploy.py

**Проблема:** Аргументы в `run_cmd()` экранируются только `replace('"', '\\"')`, что не защищает от `$()`, бэктиков, `\n`.

**Решение:** `shlex.quote()` для всех пользовательских данных в `call_agent`, `send_notification`, `switch_agent`, `add_heartbeat`, `delete_agent`. Убрать ручное экранирование.

**Файлы:** `src/deploy.py`

### 5c. Валидация имени агента

**Проблема:** Имя агента от LLM используется в путях FS и shell-командах без проверки.

**Решение:** Regex `^[a-z][a-z0-9_]{1,49}$` при создании/extend. Не при switch/delete.

**Файлы:** `src/orchestration.py`

## 6. Cleanup OpenClaw defaults

**Проблема:** OpenClaw при `agents add` создаёт шаблоны (BOOTSTRAP.md, IDENTITY.md, AGENTS.md, TOOLS.md, USER.md, HEARTBEAT.md). Они конкурируют с SOUL.md, вызывая нестабильное поведение агентов. Проверено: OpenClaw не пересоздаёт их при рестарте gateway или `doctor --fix`.

**Решение:** Общая функция `clean_workspace_defaults()`:
- Удаляет BOOTSTRAP.md, IDENTITY.md, USER.md, TOOLS.md, HEARTBEAT.md
- Для базовых агентов — также дефолтный AGENTS.md
- Вызывается из `install()` и `update()`

**Файлы:** `setup.py`

## 7. Стабильное приветствие architect

**Проблема:** LLM по-разному интерпретирует абстрактные инструкции "покажи команды на отдельных строках".

**Решение:** Заменить описательные правила на буквальный шаблон с допуском перефразировки при сохранении структуры.

**Файлы:** `agents/architect/SOUL.md`

## 8. Полная очистка при удалении агента

**Проблема:** `delete_agent` не удаляет `/root/.openclaw/agents/<name>/` (sessions, state). При повторном создании агента с тем же именем — старые сессии.

**Решение:** Добавить удаление `~/.openclaw/agents/<name>/` в `delete_agent`.

**Файлы:** `src/deploy.py`

## 9. Автодетект Telegram ID

**Проблема:** Telegram ID `541534272` захардкожен в SKILL.md, main.py, orchestration.py.

**Решение:**
- Автодетект из `/root/.openclaw/credentials/telegram-default-allowFrom.json` (создаётся при pairing)
- Сохранение в `/opt/clawforge/.telegram_id`
- Подстановка в SKILL.md через шаблон `{{TELEGRAM_USER_ID}}`
- Python-код читает из `.telegram_id`
- Если Telegram не спарен — setup.py предупреждает, update подхватит позже

**Файлы:** `setup.py`, `skills/claw-forge/SKILL.md`, `src/main.py`, `src/orchestration.py`

## Что НЕ трогаем

| Пункт | Причина |
|---|---|
| os.fork() на Windows | --notify только на Linux, на Windows sync-режим |
| JSON schema validation | Overkill, KeyError достаточно информативен |
| Дублирование cleanup | Разные контексты (install vs runtime) |
| Два разных run_cmd() | Разные контракты (warn vs fail-fast) |
| PROTECTED_FILES dead code | Мелочь, не приоритет |
| Ротация логов | Мелочь, не приоритет |

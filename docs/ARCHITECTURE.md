# ClawForge — Архитектура системы

## Что это

ClawForge — надстройка над OpenClaw, которая автоматизирует создание AI-агентов через конвейер из четырёх специализированных агентов. Пользователь описывает задачу главному агенту (architect) в Telegram, конвейер проектирует, разрабатывает, тестирует и деплоит нового агента в OpenClaw.

Каждый созданный агент — полноценный агент OpenClaw со своим workspace, сессиями и Telegram-ботом.

## Ключевые концепции

### Per-Bot Architecture

Каждый агент привязан к **своему** Telegram-боту. Нет динамического переключения агентов, нет shared routing. Architect живёт в своём боте, thesis_maker — в своём, avatar_prompt — в своём.

Реализовано через нативную фичу OpenClaw — `channels.telegram.accounts`:

```json
{
  "channels": {
    "telegram": {
      "accounts": {
        "default": { "botToken": "architect-token" },
        "thesis_maker": { "botToken": "thesis-maker-token" }
      }
    }
  },
  "bindings": [
    { "agentId": "main", "match": { "channel": "telegram", "accountId": "default" } },
    { "agentId": "thesis_maker", "match": { "channel": "telegram", "accountId": "thesis_maker" } }
  ]
}
```

Bindings статические — устанавливаются один раз при привязке бота, никогда не меняются.

### Конвейер создания агентов

Когда пользователь просит создать агента, architect запускает конвейер из 4 внутренних агентов:

```
Пользователь → Architect → Конвейер:
  1. Analyst    — анализирует задачу, проверяет существующих агентов, выбирает стратегию
  2. Developer  — генерирует SOUL.md, AGENTS.md, IDENTITY.md, skills
  3. Tester     — проверяет артефакты на соответствие требованиям
  4. Validator  — финальный аудит перед деплоем
  → Deploy     — создаёт workspace, регистрирует в OpenClaw
```

Analyst выбирает одну из стратегий:
- **create_new** — новый агент с нуля
- **extend_existing** — добавить skill/обновить SOUL.md существующего агента
- **reuse_existing** — подходит существующий агент, ничего не создавать
- **automation_only** — cron-задача без агента (heartbeat)

### Делегация задач

Architect может делегировать задачи созданным агентам через нативный механизм субагентов OpenClaw (sessions_spawn). Например: пользователь просит сгенерировать промпт для аватарки → architect находит avatar_prompt в списке агентов → запускает его как субагента → возвращает результат.

### Привязка Telegram-бота

Два сценария:
- **При создании**: пользователь передаёт токен вместе с запросом на создание
- **После создания**: agent создан, пользователь позже присылает токен

Привязка: `main.py bind --agent <name> --token <bot_token>` → записывает account + binding в `openclaw.json` → gateway hot-reload подхватывает.

## Типы агентов

### Architect (main)

Главный агент, точка входа. Workspace: `~/.openclaw/workspace`

- Общается с пользователем через своего Telegram-бота
- Управляет агентами: создание, удаление, привязка ботов
- Делегирует задачи специализированным агентам
- Команды: `/list`, `/rm`, описание задачи для создания
- Использует skill `claw-forge` для CLI-операций

Файлы:
- `agents/architect/SOUL.md` — роль, правила делегации, стиль общения
- `agents/architect/AGENTS.md` — правила workspace, защита конфигурации
- `agents/architect/IDENTITY.md` — имя "ClawForge", эмодзи
- `skills/claw-forge/SKILL.md` — CLI-команды (/list, /rm, bind, create, cancel)

### Pipeline-агенты (analyst, developer, tester, validator)

Внутренние агенты конвейера. Вызываются программно, не общаются с пользователем.

- Workspace: `~/.openclaw/workspaces/<name>`
- Вызываются через `deploy.call_agent()` → `openclaw agent --agent <name> --message "..."`
- Отвечают строго JSON
- Не используют memory, не пишут файлы

Файлы:
- `agents/<name>/SOUL.md` — роль, формат ответа
- `agents/<name>/AGENTS.md` — правила: JSON-формат, без memory, без вопросов

### Создаваемые агенты (thesis_maker, avatar_prompt, ...)

Полноценные автономные агенты. Каждый — свой Telegram-бот.

- Workspace: `~/.openclaw/workspaces/<name>`
- Все файлы генерируются конвейером (developer)
- Не знают про architect, не переключаются, работают автономно
- Пользователь общается напрямую через бота агента

Файлы (генерируются developer):
- `SOUL.md` — роль, экспертиза, стиль
- `AGENTS.md` — правила workspace
- `IDENTITY.md` — имя, эмодзи, описание
- `skills/` — навыки под задачу

## Структура файлов проекта

```
ClawForge/
├── src/
│   ├── main.py           — CLI: create, list, search, bind, delete
│   ├── deploy.py          — OpenClaw операции: workspace, register, bind/unbind bot
│   ├── orchestration.py   — конвейер создания (analyst → developer → tester → validator)
│   └── registry.py        — SQLite реестр агентов (метаданные, поиск, sync)
├── agents/
│   ├── architect/         — SOUL.md, AGENTS.md, IDENTITY.md главного агента
│   ├── analyst/           — SOUL.md, AGENTS.md аналитика
│   ├── developer/         — SOUL.md, AGENTS.md разработчика
│   ├── tester/            — SOUL.md, AGENTS.md тестировщика
│   └── validator/         — SOUL.md, AGENTS.md валидатора
├── skills/
│   └── claw-forge/        — SKILL.md — CLI-команды для architect
├── setup.py               — install / update / uninstall на сервер OpenClaw
├── clawforge.db            — SQLite база реестра агентов
└── docs/
    ├── ARCHITECTURE.md    — этот документ
    └── plans/             — дизайн-документы и планы реализации
```

## Ключевые модули

### deploy.py

Взаимодействие с OpenClaw через CLI. Все операции — обёртки над `openclaw` командами.

| Функция | Что делает |
|---------|-----------|
| `create_agent_workspace()` | Создаёт папку с SOUL.md, AGENTS.md, IDENTITY.md, skills, data_files |
| `register_agent()` | `openclaw agents add` + восстановление файлов поверх дефолтов |
| `delete_agent()` | `openclaw agents delete` + unbind бота + cron cleanup + gateway restart |
| `bind_agent_to_bot()` | Записывает telegram account + binding в openclaw.json |
| `unbind_agent_bot()` | Удаляет account + binding из openclaw.json |
| `call_agent()` | `openclaw agent --agent <name> --message "..."` |
| `clear_pipeline_sessions()` | Очищает сессии pipeline-агентов перед запуском конвейера |
| `send_notification()` | `openclaw message send` в Telegram |
| `get_telegram_user_id()` | Читает из .telegram_id или env |

**Важный нюанс:** `openclaw agents add` перезаписывает файлы в workspace дефолтами. `register_agent()` сохраняет наши файлы до вызова и восстанавливает после.

### main.py

CLI-интерфейс. Вызывается architect через skill claw-forge.

| Команда | Функция |
|---------|---------|
| `create --task "..." --notify telegram:ID` | Запускает конвейер в фоне (fork), результат в Telegram |
| `cancel --notify telegram:ID` | Остановить конвейер + очистить partial artifacts |
| `list` | Показывает агентов из реестра (с sync из OpenClaw) |
| `search --query "..."` | Поиск по описанию и capabilities |
| `bind --agent <name> --token <token>` | Привязка Telegram-бота |
| `delete --agent <name>` | Удаление агента + unbind + cron cleanup + gateway restart |

**Важные нюансы:**
- `bind` и `delete` модифицируют openclaw.json, что вызывает gateway hot-reload. Это прерывает доставку ответа architect в Telegram. Поэтому после операции — `time.sleep(2)` + явный `send_notification()`.
- `create` отслеживает PID запущенного конвейера в `logs/pipeline.pid`. Защита от двойного запуска: если конвейер уже работает — отказ. `cancel` убивает процесс (SIGTERM + SIGKILL fallback) и чистит partial artifacts.

### orchestration.py

Конвейер создания агентов. Ядро системы.

**Поток:**
1. `run_pipeline(task_description)` — точка входа
2. Analyst получает задачу + список существующих агентов → возвращает JSON с decision
3. По decision: reuse → return, automation → create cron, create/extend → далее
4. Developer получает requirements → генерирует артефакты (SOUL.md, AGENTS.md, IDENTITY.md, skills, data_files). Все статические инструкции — в SOUL.md developer'а, промпт содержит только JSON аналитика.
5. Tester проверяет артефакты → approved/rejected
6. Если rejected → Developer фиксит → Tester проверяет (до 3 раз)
7. Validator — финальный аудит (1 retry)
8. Deploy: `create_agent_workspace()` + `register_agent()` + registry + heartbeat + gateway restart

**Устойчивость:**
- Сессии pipeline-агентов очищаются перед каждым запуском (`clear_pipeline_sessions()`) — предотвращает накопление контекста и rate limit.
- API-ошибки (rate limit, timeout) отделены от JSON-ошибок. API retry: экспоненциальный backoff 5→15→45→135с (4 попытки). При исчерпании — RuntimeError (не переходит к бесполезным JSON retry).
- JSON-парсинг: `parse_json_response()` пробует: прямой parse → boundary search → code block strip → fallback. `call_agent_with_retry()` повторяет с явной JSON-инструкцией (до 2 раз).
- Задержка 2с между шагами конвейера для снижения API-нагрузки.

### registry.py

SQLite хранилище метаданных агентов. Дополняет нативный реестр OpenClaw полями: description, capabilities, type, timestamps.

| Функция | Что |
|---------|-----|
| `add_agent()` | INSERT, capabilities сериализуются в JSON |
| `get_agent()` / `list_agents()` / `search_agents()` | SELECT, capabilities десериализуются автоматически |
| `update_agent()` | Один UPDATE-запрос (не цикл) |
| `sync_with_openclaw()` | Сверяет реестр с `openclaw agents list --json`, удаляет расхождения |

### setup.py

Установка/обновление/удаление ClawForge на сервере OpenClaw.

- `install` — создаёт pipeline-агентов, настраивает architect, ставит skill, защищает файлы (chmod 444)
- `update` — обновляет SOUL.md/AGENTS.md/IDENTITY.md/SKILL.md всех агентов
- `uninstall` — удаляет всё: агентов, workspace, bindings, реестр, логи

## Workspace файлы OpenClaw

Каждый агент OpenClaw имеет workspace — папку с конфигурационными файлами:

| Файл | Назначение | Кто управляет |
|------|-----------|---------------|
| SOUL.md | Роль, экспертиза, поведение | ClawForge |
| AGENTS.md | Правила workspace, стартовый протокол | ClawForge |
| IDENTITY.md | Имя, эмодзи, описание | ClawForge |
| USER.md | Информация о пользователе | OpenClaw (дефолт) |
| TOOLS.md | Локальные инструменты | OpenClaw (дефолт) |
| HEARTBEAT.md | Heartbeat конфиг | OpenClaw (дефолт) |
| MEMORY.md | Долгосрочная память | OpenClaw (создаётся автоматически) |
| skills/ | Навыки агента | ClawForge |

ClawForge переопределяет SOUL.md, AGENTS.md, IDENTITY.md. Остальные файлы — дефолты OpenClaw, не трогаем.

## Принятые технические решения

### Почему per-bot, а не switching

Первая архитектура использовала один Telegram-бот + динамическое переключение через `openclaw agents bind`. Проблема: `/new` и `/reset` в OpenClaw выбирают агента по **последней активной сессии**, а не по binding. Race conditions были неустранимы. Решение: каждый агент = свой бот, bindings статические.

### Почему свой реестр (SQLite) при наличии нативного

Нативный реестр OpenClaw (`openclaw agents list`) хранит только id, name, workspace path. Наш реестр добавляет: description, capabilities (для поиска), type, timestamps. `sync_with_openclaw()` при `/list` сверяет реестры — если агент удалён из OpenClaw напрямую, он удаляется и у нас.

### Почему конвейер из 4 агентов, а не один

Разделение ответственности: analyst решает **что** делать (новый/расширить/reuse), developer решает **как** (генерирует файлы), tester проверяет **качество**, validator — финальный аудит. Каждый специализирован и имеет чёткий формат ввода/вывода (JSON). Retry-логика позволяет developer исправлять ошибки по замечаниям tester.

### Почему файлы сохраняются до `openclaw agents add`

`openclaw agents add` создаёт workspace и **перезаписывает** все файлы дефолтами. Наши SOUL.md, AGENTS.md, IDENTITY.md теряются. Поэтому `register_agent()` сохраняет содержимое файлов в память до вызова, и восстанавливает после.

### Почему sleep(2) + send_notification после bind/delete

Запись в `openclaw.json` (bind/unbind бота) вызывает gateway hot-reload. Во время reload Telegram-подключение прерывается, и ответ architect не доставляется. Задержка 2 секунды + явный `send_notification()` — обходной путь.

## Развёртывание

Сервер: Linux с установленным OpenClaw. Проект клонируется в `/opt/clawforge/`.

```bash
# Установка
cd /opt/clawforge
python3 setup.py

# Обновление (после git pull)
python3 setup.py --update

# Удаление
python3 setup.py --uninstall
```

Деплой изменений: `git push` → `ssh git pull` → `setup.py --update`.

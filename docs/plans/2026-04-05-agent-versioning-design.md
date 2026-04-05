# Versioning и rollback агентов

**Дата:** 2026-04-05
**Статус:** Утверждён

## Проблема

Сейчас при `extend_existing` файлы агента перезаписываются поверх без бэкапа. Если новая версия оказалась хуже предыдущей, или пользователь просто передумал — вернуться назад невозможно. Нужна история изменений и возможность отката.

## Решение

Каждое изменение агента создаёт снапшот — полную копию управляемых файлов и данных. История хранится в `versions/` внутри workspace агента. Откат — перемещение указателя `current` + копирование снапшота обратно в workspace.

### Структура хранения

```
/root/.openclaw/workspaces/pelevin/
├── SOUL.md, AGENTS.md, IDENTITY.md       ← текущее состояние
├── skills/, scripts/
├── quotes.json, subscribers.json
├── HEARTBEAT.md, USER.md, TOOLS.md       ← OpenClaw, не трогаем
└── versions/
    ├── _manifest.json
    ├── v1-2026-03-30T12-05-01/
    │   ├── SOUL.md, AGENTS.md, IDENTITY.md
    │   ├── skills/, scripts/
    │   ├── quotes.json, subscribers.json
    │   └── cron.json                     ← если есть cron-задача
    ├── v2-2026-04-01T09-15-22/
    └── v3-2026-04-05T18-40-10/
```

### Blacklist (что НЕ копируется в снапшот)

- Файлы: `USER.md`, `TOOLS.md`, `HEARTBEAT.md`, `MEMORY.md`, `package-lock.json`
- Директории: `node_modules/`, `.openclaw/`, `.git/`, `versions/`

Всё остальное (конфигурация + данные агента) копируется.

### Формат `_manifest.json`

```json
{
  "current": "v3-2026-04-05T18-40-10",
  "versions": [
    {
      "id": "v1-2026-03-30T12-05-01",
      "number": 1,
      "created_at": "2026-03-30T12:05:01Z",
      "source": "created",
      "comment": "Создан с нуля",
      "changed_files": []
    },
    {
      "id": "v2-2026-04-01T09-15-22",
      "number": 2,
      "created_at": "2026-04-01T09:15:22Z",
      "source": "extend_existing",
      "comment": "Добавлен heartbeat для ежедневной рассылки",
      "changed_files": ["SOUL.md", "scripts/broadcast.js"]
    },
    {
      "id": "v3-2026-04-05T18-40-10",
      "number": 3,
      "created_at": "2026-04-05T18:40:10Z",
      "source": "quick_fix",
      "comment": "Переход с подписчиков на канальную публикацию",
      "changed_files": ["SOUL.md", "scripts/broadcast.js", "config.json"]
    }
  ]
}
```

**Номер версии (`number`)** — монотонно растёт, никогда не переиспользуется после FIFO удаления.

## Создание снапшота

**Триггеры:**
- `create_new` — после успешного `register_agent()` + heartbeat, `source: "created"`
- `extend_existing` — после успешного `update_agent_files()` + heartbeat, `source: "extend_existing"`, `comment` из `requirements["description"]`
- **Quick fix Architect-а** — вручную через `main.py snapshot`, `source: "quick_fix"`, `comment` от Architect-а

Снапшот создаётся **после** применения изменений — директория `versions/vN-.../` содержит файлы, соответствующие именно этой версии.

**Ограничение: 8 версий максимум.** При создании 9-й удаляется самая старая (по `created_at`), с защитой: `current` никогда не удаляется.

### Инструкции Architect-а для quick fix

В `agents/architect/SOUL.md` (секция "Быстрый фикс"):

```
4. ОБЯЗАТЕЛЬНО после успешной проверки — сохрани снапшот:
   python3 /opt/clawforge/src/main.py snapshot --agent <name> --comment "<краткое описание правки>"
   Без этого шага версия не зафиксируется в истории, откат потом будет невозможен.
   Если серия правок провалилась (тестер так и не одобрил) — снапшот НЕ создавай.
```

В `agents/architect/AGENTS.md` — дублирование для усиления:
```
- ОБЯЗАТЕЛЬНО после успешного теста — создай снапшот через main.py snapshot. БЕЗ ЭТОГО ПРАВКИ ПОТЕРЯЮТСЯ ПРИ ОТКАТЕ.
```

## Rollback

**Физический процесс:**
1. Проверяем: `version_ref` существует в `_manifest.json`
2. Удаляем из workspace управляемые файлы (по whitelist: SOUL.md, AGENTS.md, IDENTITY.md, skills/, scripts/, data_files)
3. Копируем `versions/v<target>-.../` поверх в workspace
4. Восстанавливаем cron из `cron.json` снапшота (см. таблицу ниже)
5. Обновляем `_manifest.json`: `current = v<target>`
6. Обновляем `registry` (description, capabilities из SOUL.md/требований версии — нужно сохранять в metadata снапшота, либо парсить)
7. Если cron изменился — отложенный gateway restart

**История линейна и неизменяема.** Rollback двигает указатель `current`, но версии не удаляются (кроме FIFO).

### Cron при rollback

Каждый снапшот хранит `cron.json` — копию записи из `/root/.openclaw/cron/jobs.json` на момент снапшота (или файл отсутствует, если cron'а не было).

| current cron | target cron | Действие |
|---|---|---|
| есть | есть | Заменить запись |
| есть | нет | Удалить из jobs.json |
| нет | есть | Добавить в jobs.json |
| нет | нет | Ничего не делать |

Если `jobs.json` изменялся → `gateway restart` (Python-процесс, прямой restart + sleep(5)).

`enabled` флаг восстанавливается из снапшота как есть.

### Пограничные случаи

- **Откат на current** → "Это уже текущая версия, откат не нужен."
- **Несуществующая версия** → "Версия v12 не найдена."
- **Агент удалён** → "Агент не найден в реестре."
- **Снапшот повреждён/удалён** → "Снапшот v2 повреждён. Откат невозможен."

### UX rollback

```
User: /rollback pelevin v2

Architect: Откатить pelevin с v5 (текущая) на v2?
  v2 — 01.04.2026 09:15 — "Добавлен heartbeat для ежедневной рассылки"
  
  Изменится:
  - SOUL.md (будет версия от 01.04)
  - scripts/broadcast.js (будет версия от 01.04)
  - subscribers.json (будет версия от 01.04 — может снести свежие подписки)
  - config.json (файл исчезнет — его не было в v2)
  - cron: расписание сменится на "0 7 * * *", enabled=true
  
  Подтвердить? (да/нет)

User: да
Architect: Готово. Текущая версия pelevin — v2.
```

## Команды CLI

```bash
# Список версий
python3 main.py history --agent <name>

# Информация о версии
python3 main.py history --agent <name> --version <number_or_id>

# Откат
python3 main.py rollback --agent <name> --version <number_or_id>

# Ручной снапшот (для quick fix)
python3 main.py snapshot --agent <name> --comment "<описание>"
```

`--version` принимает: номер (`2`), полный id (`v2-2026-04-01T09-15-22`), алиас (`previous`).

## Вывод `history`

```
История pelevin (текущая: v3):

v3 (quick fix) — 05.04.2026 18:40  ← текущая
  Комментарий: Переход с подписчиков на канальную публикацию
  Изменено: SOUL.md, scripts/broadcast.js, config.json

v2 (extend) — 01.04.2026 09:15
  Комментарий: Добавлен heartbeat для ежедневной рассылки
  Изменено: SOUL.md, scripts/broadcast.js

v1 (создан) — 30.03.2026 12:05
  Создан с нуля

Откатить: /rollback pelevin v<номер>
```

## Вывод `history --version 2`

```
pelevin v2 (extend) — 01.04.2026 09:15

Комментарий: Добавлен heartbeat для ежедневной рассылки
Создан: extend_existing через конвейер
Изменено: SOUL.md, scripts/broadcast.js

Cron: 0 7 * * * UTC, enabled=true
Файлы:
  SOUL.md (2.3 KB)
  AGENTS.md (0.5 KB)
  IDENTITY.md (0.2 KB)
  skills/broadcast/SKILL.md (1.1 KB)
  scripts/broadcast.js (2.8 KB)
  subscribers.json (0.1 KB)
  quotes.json (12.4 KB)
```

## Изменения в коде

**Новый модуль `src/versioning.py`:**
- `create_snapshot(agent_name, source, comment, changed_files=None)`
- `list_versions(agent_name)`
- `get_version_info(agent_name, version_ref)`
- `rollback_to_version(agent_name, version_ref)`
- `enforce_retention(agent_name, max_versions=8)`
- Helpers: `_load_manifest`, `_save_manifest`, `_copy_workspace_to_snapshot`, `_copy_snapshot_to_workspace`, `_compute_changed_files`, `_save_cron_to_snapshot`, `_restore_cron_from_snapshot`

**Константы в versioning.py:**
```python
OPENCLAW_DEFAULT_FILES = {"USER.md", "TOOLS.md", "HEARTBEAT.md", "MEMORY.md"}
BLACKLISTED_DIRS = {"node_modules", ".openclaw", ".git", "versions"}
BLACKLISTED_FILES = {"package-lock.json"}
MAX_VERSIONS = 8
```

**`src/main.py`:**
- Новые subparsers: `snapshot`, `history`, `rollback`

**`src/orchestration.py`:**
- После `register_agent()` в `deploy_new_agent()` → `versioning.create_snapshot(name, "created", "Создан с нуля")`
- После deploy в `deploy_extension()` → `versioning.create_snapshot(name, "extend_existing", requirements["description"])`

**`src/deploy.py`:**
- Без изменений (`delete_agent()` уже удаляет workspace целиком с `versions/`)

**`skills/claw-forge/SKILL.md`:**
- Секции `/history`, `/rollback` с примерами

**`agents/architect/SOUL.md` и `AGENTS.md`:**
- Правило про snapshot после quick fix
- Правило про показ diff + подтверждение перед rollback

## Обратная совместимость

- Существующие агенты без `versions/` работают как раньше
- При первом изменении существующего агента (через extend или quick fix) — создаётся первая версия (v1) с пометкой `source: "created"`, комментарий "Существовавший агент, захвачен при первом изменении"
- `list_versions()` на агенте без `versions/` возвращает "История пуста"
- `rollback` на агенте без `versions/` возвращает "История пуста, откат невозможен"

## Что НЕ меняется

- OpenClaw binding в `openclaw.json` — бот не переключается при rollback
- Дефолтные OpenClaw-файлы в workspace
- Формат ответов Analyst/Developer в пайплайне
- Архитектура pipeline (4 агента)

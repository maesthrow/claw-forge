# Pipeline Cancel — Design

## Проблема

Пользователь не может отменить создание агента после запуска конвейера. Child-процесс после fork работает автономно, PID не сохраняется.

## Решение

PID-файл + команда cancel через CLI. Architect вызывает через skill.

### 1. PID-файл

**Путь:** `logs/pipeline.pid` (относительно корня проекта `/opt/clawforge/`)

**Формат:**
```json
{"pid": 12345, "started_at": "2026-03-26T16:41:00"}
```

После analyst возвращает agent_name — файл обновляется:
```json
{"pid": 12345, "agent_name": "funny_bot", "started_at": "2026-03-26T16:41:00"}
```

**Жизненный цикл:**
- `cmd_create` child пишет PID-файл сразу после fork
- `run_pipeline` обновляет с agent_name после analyst
- `finally` блок удаляет PID-файл (успех/ошибка/kill)

### 2. Защита от двойного запуска

`cmd_create` перед fork:
- Если `pipeline.pid` существует и процесс жив (`os.kill(pid, 0)`) → отказать
- Если файл есть но процесс мёртв → удалить stale PID-файл, продолжить

### 3. Команда cancel

`main.py cancel --notify telegram:541534272`

1. Прочитать `pipeline.pid` → если нет → "Нет активного конвейера"
2. Проверить процесс жив → если мёртв → удалить PID-файл → "Конвейер уже завершился"
3. `os.kill(pid, signal.SIGTERM)`
4. Cleanup: если `agent_name` в PID-файле → проверить registry → если есть, вызвать `deploy.delete_agent()` + `registry.remove_agent()`
5. Удалить PID-файл
6. `send_notification`: "Создание агента отменено."

### 4. Изменения в cmd_create

- Перед fork: проверить `is_pipeline_running()`
- Child: записать PID-файл → try/finally удалить PID-файл

### 5. Изменения в run_pipeline

- После analyst возвращает requirements → обновить PID-файл с `agent_name`

### 6. SKILL.md архитектора

Добавить секцию:
```
## Отмена создания агента
Когда пользователь просит отменить/остановить создание:
python3 /opt/clawforge/src/main.py cancel --notify telegram:541534272
```

## Затрагиваемые файлы

- `src/main.py` — cmd_create (PID-файл, защита), cmd_cancel (новая команда)
- `src/orchestration.py` — run_pipeline (обновление PID-файла с agent_name)
- Architect SKILL.md на сервере — секция отмены

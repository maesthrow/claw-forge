---
name: claw-forge
description: Создание, управление, переключение и удаление AI-агентов. Вызывай когда пользователь хочет создать агента, автоматизацию или навык, переключиться на другого агента, посмотреть список агентов, расширить существующего агента, или удалить агента.
---

# ClawForge — управление командой агентов

## Создать агента или автоматизацию

Когда пользователь описывает задачу и нужно создать агента:

```bash
python3 /opt/clawforge/src/main.py create --task "<описание задачи пользователя>"
```

Скрипт запустит конвейер (аналитик → разработчик → тестировщик → валидатор) и вернёт результат в JSON.

## Список агентов

```bash
python3 /opt/clawforge/src/main.py list
```

## Поиск агента

```bash
python3 /opt/clawforge/src/main.py search --query "<поисковый запрос>"
```

## Переключить на агента

```bash
python3 /opt/clawforge/src/main.py switch --agent <agent_name>
```

## Вернуться к оркестратору

```bash
python3 /opt/clawforge/src/main.py switch --agent orchestrator
```

## Удалить агента

ВАЖНО: Перед вызовом этой команды ОБЯЗАТЕЛЬНО запроси подтверждение у пользователя.

```bash
python3 /opt/clawforge/src/main.py delete --agent <agent_name>
```

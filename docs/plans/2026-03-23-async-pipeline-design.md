# ClawForge — Асинхронный конвейер + багфиксы

**Дата:** 2026-03-23
**Статус:** Approved

---

## Корневая причина

Весь конвейер (4+ вызовов LLM) выполняется синхронно внутри одного exec вызова от OpenClaw. OpenClaw убивает долгий exec по таймауту → тишина в Telegram → пользователь не получает результат.

## Решение: фоновый процесс + уведомление

### Как работает

1. Exec запускает конвейер в фоне, мгновенно возвращает "Создаю агента..."
2. Конвейер работает в фоновом процессе без ограничений по времени
3. По завершении Python-скрипт сам отправляет результат в Telegram через `openclaw message send`

### Что меняется

**main.py** — флаг `--notify`:
- С `--notify telegram:ID` → fork, родитель возвращает "Конвейер запущен", дочерний процесс выполняет pipeline и отправляет результат
- Без `--notify` → синхронный режим (для отладки)

**deploy.py** — функция `send_notification(target, message)`:
- Отправляет результат через `openclaw message send`

**SKILL.md** — команда create с `--notify`:
```
python3 /opt/clawforge/src/main.py create --task "..." --notify telegram:541534272
```

**orchestration.py** — retry при validator reject:
- Validator отклонил → developer fix → tester → validator (макс 1 retry)
- Tester отклонил → developer fix → tester (макс 2 попытки) — уже работает

### Цикл retry

```
analyst → developer → tester
                        │
                  approved? ──нет──→ developer fix → tester (макс 2)
                        │
                       да
                        ▼
                    validator
                        │
                  approved? ──нет──→ developer fix → tester → validator (макс 1 retry)
                        │
                       да
                        ▼
                      deploy → уведомление в Telegram
```

### Формат уведомлений

Успех:
```
Агент linkedin_writer создан!
Описание: подготовка LinkedIn-постов для личного бренда
Используй /set linkedin_writer чтобы переключиться.
```

Ошибка:
```
Не удалось создать агента: [причина от validator].
Попробуйте уточнить задачу и запустить создание заново.
```

### Что НЕ меняется

- Конвейер (analyst → developer → tester → validator → deploy)
- Реестр (SQLite)
- Переключение агентов (config set bindings)
- Skills и SOUL.md создаваемых агентов
- setup.py

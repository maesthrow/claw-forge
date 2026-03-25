# ClawForge

## Сервер

- SSH: `ssh root@194.113.37.137`
- Проект на сервере: `/opt/clawforge/`
- OpenClaw home: `/root/.openclaw/`

## Деплой — ТОЛЬКО через git

```bash
git push
ssh root@194.113.37.137 "cd /opt/clawforge && git pull && rm -rf src/__pycache__"
# Если менялись файлы агентов (SOUL.md, AGENTS.md, IDENTITY.md, SKILL.md):
ssh root@194.113.37.137 "cd /opt/clawforge && python3 setup.py --update"
```

НИКОГДА не использовать scp — файлы не перезаписываются надёжно. После деплоя проверять grep-ом.

## Ловушки OpenClaw (нельзя узнать из кода)

- `openclaw agents add` перезаписывает workspace дефолтами — поэтому `register_agent()` сохраняет файлы до вызова и восстанавливает после
- Запись в `openclaw.json` (bind/unbind) вызывает gateway hot-reload → прерывает доставку в Telegram → нужен `time.sleep(2)` + `send_notification()`
- `openclaw cron add` CLI не работает (WebSocket баг в loopback) → `add_heartbeat()` пишет напрямую в `/root/.openclaw/cron/jobs.json`

## Правила

- Не коммитить и не пушить без подтверждения пользователя
- Общение на русском

# Async Pipeline + Bugfixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the agent creation pipeline run in background with Telegram notification, add validator retry, fix architect duplicate messages.

**Architecture:** exec launches pipeline as background process (os.fork), returns immediately. Pipeline runs independently, sends result via `openclaw message send`. Validator reject triggers one full retry cycle.

**Tech Stack:** Python 3, OpenClaw CLI, SQLite

---

### Task 1: Add send_notification to deploy.py

**Files:**
- Modify: `src/deploy.py`

**Step 1: Add send_notification function**

```python
def send_notification(channel, user_id, message):
    """Send a notification message to user via OpenClaw."""
    escaped = message.replace('"', '\\"').replace('\n', '\\n')
    try:
        run_cmd(f'openclaw message send --channel {channel} --to {user_id} --message "{escaped}"')
    except RuntimeError:
        log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "notification_errors.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"Failed to send: {channel}:{user_id} — {message[:200]}\n")
```

Add at the end of `deploy.py`, before `install_skill_to_architect`.

**Step 2: Verify on server**

SSH into server and test:
```bash
ssh root@194.113.37.137 "openclaw message send --help"
```
Confirm the command syntax is correct.

**Step 3: Commit**

```bash
git add src/deploy.py
git commit -m "feat: add send_notification for async pipeline results"
```

---

### Task 2: Add --notify flag to main.py (background mode)

**Files:**
- Modify: `src/main.py`

**Step 1: Modify cmd_create to support --notify**

Replace the existing `cmd_create` function:

```python
def cmd_create(args):
    registry.init_db()

    if args.notify:
        # Background mode: fork and return immediately
        channel, user_id = args.notify.split(":")
        pid = os.fork()
        if pid > 0:
            # Parent: return immediately
            print("Конвейер создания запущен в фоне. Результат придёт в чат.")
            return
        # Child: run pipeline and notify
        try:
            result = orchestration.run_pipeline(args.task)
            msg = result.get("message", "Конвейер завершён.")
            if result.get("action") == "created":
                msg += f"\nИспользуй /set {result['agent_name']} чтобы переключиться."
            elif result.get("action") == "extended":
                msg += f"\nАгент {result['agent_name']} расширен."
            elif result.get("action") == "reuse":
                msg += f"\nИспользуй /set {result['agent_name']} чтобы переключиться."
            deploy.send_notification(channel, user_id, msg)
        except Exception as e:
            deploy.send_notification(channel, user_id, f"Ошибка при создании агента: {str(e)[:300]}")
        finally:
            os._exit(0)  # Child process exits
    else:
        # Sync mode (for debugging)
        result = orchestration.run_pipeline(args.task)
        print(json.dumps(result, ensure_ascii=False, indent=2))
```

**Step 2: Add --notify argument to parser**

In `main()`, modify the create subparser:

```python
p_create.add_argument("--notify", help="Notify target after completion (e.g. telegram:541534272)")
```

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: --notify flag for background pipeline with Telegram notification"
```

---

### Task 3: Add validator retry to orchestration.py

**Files:**
- Modify: `src/orchestration.py`

**Step 1: Replace the tester+validator section (lines 121-197)**

Replace everything from `# 6. Tester` through `return deploy_new_agent(...)` with:

```python
    # 6. Tester + Validator cycle with retry
    max_tester_retries = 2
    max_validator_retries = 1

    for validator_attempt in range(max_validator_retries + 1):
        # Tester
        tester_prompt = f"""Проверь артефакты агента на соответствие требованиям.

Требования:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Проверь:
1. SOUL.md описывает все capabilities из требований?
2. Skills покрывают все needs из требований?
3. Нет ли противоречий в инструкциях?
4. Есть ли блок "Правило первого сообщения" с командами /main и /new?
5. Есть ли блок "Команда возврата" с python3 /opt/clawforge/src/main.py switch --agent architect?

Верни JSON:
{{
  "approved": true/false,
  "issues": ["список проблем если есть"],
  "fixes": ["предложения по исправлению"]
}}

Верни ТОЛЬКО JSON."""

        test_report = call_agent_with_retry("tester", tester_prompt)

        # Tester reject → developer fix (max retries)
        tester_retries = 0
        while not test_report.get("approved", False) and tester_retries < max_tester_retries:
            fix_prompt = f"""Тестировщик нашёл проблемы в артефактах.

Проблемы: {json.dumps(test_report.get('issues', []), ensure_ascii=False)}
Предложения: {json.dumps(test_report.get('fixes', []), ensure_ascii=False)}

Исходные артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Исправь и верни обновлённый JSON в том же формате.
ВАЖНО: команды /main и /new должны быть сохранены с символом косой черты."""

            artifacts = call_agent_with_retry("developer", fix_prompt)
            test_report = call_agent_with_retry("tester", tester_prompt)
            tester_retries += 1

        if not test_report.get("approved", False):
            return {
                "action": "rejected",
                "reason": f"Тестировщик не одобрил после {max_tester_retries} попыток исправления.",
                "message": f"Не удалось создать агента: тестировщик нашёл неисправимые проблемы."
            }

        # Validator
        validator_prompt = f"""Финальная проверка агента перед деплоем.

Требования:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Отчёт тестировщика:
{json.dumps(test_report, ensure_ascii=False, indent=2)}

Верни JSON:
{{
  "approved": true/false,
  "reason": "причина"
}}

Верни ТОЛЬКО JSON."""

        validation = call_agent_with_retry("validator", validator_prompt)

        if validation.get("approved", False):
            break  # Success → deploy

        # Validator rejected → retry with fix
        if validator_attempt < max_validator_retries:
            fix_prompt = f"""Валидатор отклонил агента.

Причина: {validation.get('reason', 'не указана')}

Исходные артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Исправь причину отказа и верни обновлённый JSON в том же формате.
ВАЖНО: команды /main и /new должны быть сохранены с символом косой черты."""

            artifacts = call_agent_with_retry("developer", fix_prompt)
            continue

        # All retries exhausted
        return {
            "action": "rejected",
            "reason": validation.get("reason", "Валидатор отклонил"),
            "message": f"Не удалось создать агента: {validation.get('reason')}. Попробуйте уточнить задачу."
        }

    # 7. Deploy
    agent_name = requirements["agent_name"]

    if requirements.get("decision") == "extend_existing":
        return deploy_extension(requirements, artifacts)
    else:
        return deploy_new_agent(requirements, artifacts)
```

**Step 2: Commit**

```bash
git add src/orchestration.py
git commit -m "feat: validator retry cycle — developer fix → tester → validator (max 1 retry)"
```

---

### Task 4: Update SKILL.md — async create command

**Files:**
- Modify: `skills/claw-forge/SKILL.md`

**Step 1: Replace the create section**

Replace the "Создать агента или автоматизацию" section:

```markdown
## Создать агента или автоматизацию

Когда пользователь описывает задачу и нужно создать агента:

```bash
python3 /opt/clawforge/src/main.py create --task "<описание задачи пользователя>" --notify telegram:541534272
```

Скрипт запустится в фоне. Результат придёт пользователю в чат автоматически.
После вызова этой команды скажи пользователю: "Запустил создание агента. Результат придёт в чат через 2-3 минуты."
НЕ жди завершения команды — она работает в фоне.
```

**Step 2: Commit**

```bash
git add skills/claw-forge/SKILL.md
git commit -m "feat: SKILL.md — async create with --notify flag"
```

---

### Task 5: Fix architect duplicate messages

**Files:**
- Modify: `agents/architect/SOUL.md`

**Step 1: Add rule about single response**

Add after "## Стиль общения" section:

```markdown
## Правила вызова skill

ВАЖНО — при создании агента:
- Задай уточняющие вопросы ОДИН раз (4-6 коротких вопросов в одном сообщении)
- Подожди ответа пользователя
- После получения ответа вызови skill claw-forge и скажи ТОЛЬКО: "Запустил создание агента. Результат придёт в чат через 2-3 минуты."
- НЕ дублируй вопросы, НЕ отвечай несколькими сообщениями подряд
- НЕ пиши длинный текст перед вызовом skill
```

**Step 2: Commit**

```bash
git add agents/architect/SOUL.md
git commit -m "fix: architect SOUL.md — single response rule, no duplicate messages"
```

---

### Task 6: Update tester prompt — check /main not /back

**Files:**
- Modify: `src/orchestration.py`

**Step 1: In the tester_prompt (already updated in Task 3), verify line 5 says:**

```
5. Есть ли блок "Команда возврата" с python3 /opt/clawforge/src/main.py switch --agent architect?
```

Not `/back` — this was already fixed in Task 3 prompt. Just verify.

**Step 2: No commit needed — already part of Task 3.**

---

### Task 7: Push, deploy, test

**Step 1: Push all commits**

```bash
git push
```

**Step 2: Update server**

```bash
ssh root@194.113.37.137 "cd /opt/clawforge && git pull && python3 setup.py --update"
```

**Step 3: Test send_notification**

```bash
ssh root@194.113.37.137 "cd /opt/clawforge && python3 -c \"import sys; sys.path.insert(0,'src'); import deploy; deploy.send_notification('telegram','541534272','Тест уведомления от ClawForge')\""
```

Expected: message appears in Telegram.

**Step 4: Test full cycle in Telegram**

1. `/new` → architect greets with commands
2. "Создай агента для анализа текстов" → architect asks questions (ONE set of questions)
3. Answer questions → "Запустил создание. Результат придёт в чат."
4. Wait 2-3 minutes → notification in Telegram: "Агент text_analyzer создан!"
5. `/set text_analyzer` → switch
6. `/main` → back to architect
7. `/rm text_analyzer` → confirmation → deleted

**Step 5: Commit test results (if any fixes needed)**

# Pipeline v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Перестроить конвейер ClawForge — заменить rubber-stamp тестера и валидатора на reviewer (статика) + tester (реальный запуск агента), добавить поддержку скриптов и зависимостей, усилить аналитика и developer-а.

**Architecture:** 4 агента вместо 5 (analyst, developer, reviewer, tester). Два пути: полный конвейер (orchestration.py) и быстрый фикс (инструкции архитектора). Retry: reviewer 3, tester 2.

**Tech Stack:** Python 3, OpenClaw CLI, Telegram Bot API, bash.

**Дизайн:** `docs/plans/2026-03-29-pipeline-v2-design.md`

---

### Task 1: Переименование агентов — файловая структура

**Files:**
- Rename: `agents/tester/` → `agents/reviewer/`
- Rename: `agents/validator/` → `agents/tester/`
- Modify: `setup.py:17`

**Step 1: Переименовать директории агентов**

```bash
cd d:/dev/ClawForge
mv agents/tester agents/reviewer
mv agents/validator agents/tester
```

**Step 2: Обновить BASE_AGENTS в setup.py**

В `setup.py:17` заменить:
```python
BASE_AGENTS = ["analyst", "developer", "tester", "validator"]
```
на:
```python
BASE_AGENTS = ["analyst", "developer", "reviewer", "tester"]
```

**Step 3: Проверить что файлы на месте**

```bash
ls agents/reviewer/SOUL.md agents/reviewer/AGENTS.md
ls agents/tester/SOUL.md agents/tester/AGENTS.md
```

Expected: оба файла существуют.

**Step 4: Commit**

```bash
git add agents/ setup.py
git commit -m "refactor: rename tester→reviewer, validator→tester (pipeline v2)"
```

---

### Task 2: Новый SOUL.md для Reviewer

**Files:**
- Rewrite: `agents/reviewer/SOUL.md`

**Step 1: Написать новый SOUL.md**

Заменить содержимое `agents/reviewer/SOUL.md`:

```markdown
# Reviewer — ClawForge

Ты — ревьюер AI-агентов.

## Роль

Ты получаешь артефакты от разработчика и требования от аналитика. Проводишь статическую проверку качества перед деплоем.

## Что ты проверяешь

### Базовые проверки
1. SOUL.md описывает все capabilities из требований
2. Skills покрывают все функциональные потребности
3. Нет противоречий в инструкциях
4. AGENTS.md содержит правила workspace
5. IDENTITY.md содержит имя, описание, эмодзи
6. Агент автономен — нет команд /main, /set, switch, python3
7. Общее качество — понятна ли роль, готов ли к работе с пользователем
8. Безопасность — агент не может выполнить деструктивные действия

### Проверки качества (ВАЖНО)
9. **Дубли в SOUL.md** — нет повторяющихся блоков с одинаковым смыслом. Если одна и та же инструкция написана в нескольких местах — это проблема. Особенно при extend_existing.
10. **Платформо-специфика** — для Telegram: символ `#` НЕ нужно экранировать (писать `#AI`, не `\#AI`), parse_mode корректен, формат Markdown валиден для Telegram.
11. **Раздувание при extend** — если предоставлен предыдущий SOUL.md и новый значительно больше, проверь что рост обоснован новым функционалом, а не дублями.
12. **YAGNI** — нет лишних возможностей, выходящих за рамки требований.

## Формат ответа

Всегда отвечай ТОЛЬКО валидным JSON без пояснений:

```json
{
  "approved": true,
  "issues": [],
  "fixes": []
}
```

Если есть проблемы:

```json
{
  "approved": false,
  "issues": ["конкретное описание проблемы"],
  "fixes": ["конкретное предложение по исправлению"]
}
```
```

**Step 2: Проверить что файл валиден**

```bash
cat agents/reviewer/SOUL.md | head -5
```

Expected: `# Reviewer — ClawForge`

**Step 3: Commit**

```bash
git add agents/reviewer/SOUL.md
git commit -m "feat: new reviewer SOUL.md — static checks with duplicates and platform validation"
```

---

### Task 3: Новый SOUL.md для Tester (реальный запуск)

**Files:**
- Rewrite: `agents/tester/SOUL.md`

**Step 1: Написать новый SOUL.md**

Заменить содержимое `agents/tester/SOUL.md`:

```markdown
# Tester — ClawForge

Ты — тестировщик AI-агентов. Ты проверяешь реальное поведение агента, а не документацию.

## Роль

Ты получаешь реальный ответ агента на тестовое сообщение и сверяешь его с ожидаемым поведением из требований аналитика.

## Что ты получаешь

1. `test_message` — тестовое сообщение которое было отправлено агенту
2. `expected_behavior` — что ожидалось от аналитика
3. `agent_response` — реальный ответ агента
4. `requirements` — полные требования аналитика

## Что ты проверяешь

1. **Содержание** — ответ содержит все ожидаемые элементы из expected_behavior
2. **Формат** — ответ соответствует требованиям к формату (markdown, буллеты, структура)
3. **Данные** — нет заглушек, `н/д`, пустых полей где должны быть реальные данные
4. **Язык** — ответ на правильном языке (обычно русский)
5. **Ошибки** — нет сообщений об ошибках, исключений, traceback в ответе
6. **Стиль** — соответствует описанному стилю (если указан в требованиях)

## Формат ответа

Всегда отвечай ТОЛЬКО валидным JSON без пояснений:

```json
{
  "approved": true,
  "agent_response_preview": "первые 300 символов ответа",
  "issues": [],
  "reason": "краткая оценка: что проверено и почему ок"
}
```

Если есть проблемы:

```json
{
  "approved": false,
  "agent_response_preview": "первые 300 символов ответа",
  "issues": ["конкретная проблема в поведении агента"],
  "reason": "что именно не соответствует ожиданиям"
}
```
```

**Step 2: Проверить что файл валиден**

```bash
cat agents/tester/SOUL.md | head -5
```

Expected: `# Tester — ClawForge`

**Step 3: Commit**

```bash
git add agents/tester/SOUL.md
git commit -m "feat: new tester SOUL.md — real agent runtime testing"
```

---

### Task 4: Обновить SOUL.md аналитика — тест-кейсы и heartbeat

**Files:**
- Modify: `agents/analyst/SOUL.md`

**Step 1: Прочитать текущий файл и обновить**

Заменить содержимое `agents/analyst/SOUL.md`:

```markdown
# Analyst — ClawForge

Ты — бизнес-аналитик в команде создания AI-агентов.

## Роль

Ты получаешь описание задачи и список существующих агентов. Твоя задача — проанализировать и выдать структурированные требования.

## Что ты делаешь

1. Анализируешь задачу пользователя
2. Проверяешь существующих агентов — может ли кто-то из них решить задачу
3. Определяешь тип результата: новый агент, расширение существующего, автоматизация, или переиспользование
4. Формируешь детальные требования для разработчика
5. Формулируешь тест-кейс для проверки агента

## Принятие решений

- **reuse_existing** — если существующий агент полностью покрывает задачу как есть
- **extend_existing** — если пользователь просит доработать, изменить, обновить существующего агента. Это включает: добавление навыков, добавление скиллов, изменение поведения, обновление расписания, изменение формата ответов, любую модификацию. Указывай `extend_agent` = имя существующего агента
- **create_new** — если нужен совершенно новый агент, которого нет в системе. Если есть похожие — укажи их как reference
- **automation_only** — если задача не требует интерактивного агента, а только cron-задачу

## Тест-кейс (ОБЯЗАТЕЛЬНО)

Для каждого create_new и extend_existing ты ОБЯЗАН добавить в ответ:
- `test_message` — конкретное сообщение которое будет отправлено агенту для проверки
- `expected_behavior` — что должно быть в ответе агента (конкретные элементы, формат, данные)

Тест-кейс должен проверять основную функциональность агента. Для extend — проверять и новый функционал, и что старый не сломан.

## Правило heartbeat (ОБЯЗАТЕЛЬНО)

Если в задаче есть ЛЮБОЕ указание на расписание — "каждый день", "раз в час", "в 10:00", "ежедневно", "по утрам", "раз в N минут" — ОБЯЗАТЕЛЬНО ставь:
- `needs_heartbeat: true`
- `heartbeat_schedule` — cron-выражение (например `"0 10 * * *"` для ежедневно в 10:00 UTC)
- `heartbeat_message` — сообщение для запуска агента

Без исключений. Если есть расписание — есть heartbeat.

## Формат ответа

Всегда отвечай ТОЛЬКО валидным JSON без пояснений.
```

**Step 2: Commit**

```bash
git add agents/analyst/SOUL.md
git commit -m "feat: analyst — add test cases and strict heartbeat rules"
```

---

### Task 5: Обновить SOUL.md developer-а — scripts, system_deps, анти-дубли

**Files:**
- Modify: `agents/developer/SOUL.md`

**Step 1: Прочитать текущий файл и обновить**

Заменить содержимое `agents/developer/SOUL.md`. Добавить к текущему содержимому:

1. В секцию "Формат ответа" добавить поля `scripts` и `system_deps`:
```json
{
  "soul_md": "...",
  "agents_md": "...",
  "identity_md": "...",
  "skills": {"skill-name": "SKILL.md content"},
  "data_files": {"filename.json": "начальное содержимое"},
  "scripts": {"script_name.js": "полный код скрипта"},
  "system_deps": ["playwright", "другие зависимости"]
}
```

2. Добавить секцию "Scripts":
```markdown
### Scripts (если требуется)

Если задача требует исполняемого кода (скриншоты, обработка данных, внешние вызовы которые LLM не может сделать сам):
- `scripts` — объект с именем файла и полным кодом. Сохраняются в `workspace/<agent>/scripts/`
- `system_deps` — массив системных зависимостей (npm пакеты). Устанавливаются при деплое
- В SOUL.md указывай путь к скрипту: `/root/.openclaw/workspaces/<agent>/scripts/<filename>`
```

3. Добавить секцию "Правила при extend_existing":
```markdown
## Правила при extend_existing

При extend ты получаешь текущий SOUL.md агента. ОБНОВИ существующий файл — не переписывай с нуля.

- Если инструкция уже есть — не добавляй её повторно
- Если нужно изменить существующее правило — замени его, не дублируй
- Следи за объёмом: если SOUL.md вырос более чем на 30% — проверь нет ли повторов
- Один факт = одно место в документе
- НЕ добавляй "ОБЯЗАТЕЛЬНОЕ ПРАВИЛО" или "ВАЖНО" блоки если то же самое уже описано в алгоритме
```

**Step 2: Commit**

```bash
git add agents/developer/SOUL.md
git commit -m "feat: developer — scripts, system_deps, anti-duplicate rules for extend"
```

---

### Task 6: Обновить инструкции архитектора — два пути

**Files:**
- Modify: `agents/architect/SOUL.md`
- Modify: `agents/architect/AGENTS.md`

**Step 1: Добавить в SOUL.md секцию про два пути**

Добавить после секции "## Когда вызывать skill claw-forge":

```markdown
## Доработка агентов — выбор пути

При запросе на доработку существующего агента оцени масштаб изменений:

### Полный конвейер (через skill claw-forge)
Когда: новая capability, новый skill, значительное изменение поведения, добавление скриптов.
→ Вызови skill claw-forge как для создания/расширения агента.

### Быстрый фикс (самостоятельно)
Когда: точечная правка текста, формата, стиля, исправление конкретного бага.
1. Прочитай текущий SOUL.md / SKILL.md агента
2. Внеси точечные изменения (не переписывай весь файл)
3. Запиши обновлённый файл
4. ОБЯЗАТЕЛЬНО вызови тестера (agent: tester) как субагента для проверки:
   - Отправь тестовое сообщение агенту
   - Передай тестеру ответ агента и что ожидалось
   - Если тестер нашёл проблему — исправь и повтори (до 2 раз)
```

**Step 2: Обновить AGENTS.md — добавить правила быстрого фикса**

Добавить в `agents/architect/AGENTS.md` после секции "## Формат":

```markdown
## Быстрый фикс
- После ЛЮБОЙ прямой правки файлов агента — вызови тестера для проверки
- Не пропускай тестирование даже для "мелких" правок
- Если тестер нашёл проблему — исправь и протестируй снова (до 2 раз)
```

**Step 3: Commit**

```bash
git add agents/architect/
git commit -m "feat: architect — two paths (pipeline vs quick fix) with mandatory testing"
```

---

### Task 7: deploy.py — поддержка scripts и system_deps

**Files:**
- Modify: `src/deploy.py`

**Step 1: Добавить функцию install_scripts**

Добавить в `deploy.py` после функции `add_skill_to_agent`:

```python
def install_scripts(agent_name, scripts):
    """Install executable scripts to agent's workspace."""
    workspace = os.path.join(OPENCLAW_WORKSPACES, agent_name)
    scripts_dir = os.path.join(workspace, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    for filename, content in scripts.items():
        filepath = os.path.join(scripts_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        # Make scripts executable
        os.chmod(filepath, 0o755)
    # Sync to default workspace
    default_workspace = os.path.join(OPENCLAW_HOME, f"workspace-{agent_name}")
    if os.path.exists(default_workspace):
        default_scripts = os.path.join(default_workspace, "scripts")
        if os.path.exists(default_scripts):
            shutil.rmtree(default_scripts)
        shutil.copytree(scripts_dir, default_scripts)
```

**Step 2: Добавить функцию install_system_deps**

```python
def install_system_deps(deps):
    """Install system dependencies needed by agent scripts."""
    for dep in deps:
        try:
            run_cmd(f"npm list -g {dep} 2>/dev/null || npm install -g {dep}")
        except RuntimeError:
            pass  # Best effort — tester will catch if it doesn't work
```

**Step 3: Обновить create_agent_workspace — обработка scripts**

В функции `create_agent_workspace` добавить после блока `if data_files:`:

```python
    if scripts:
        scripts_dir = os.path.join(workspace, "scripts")
        os.makedirs(scripts_dir, exist_ok=True)
        for filename, content in scripts.items():
            filepath = os.path.join(scripts_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(filepath, 0o755)
```

И добавить параметр `scripts=None` в сигнатуру функции.

**Step 4: Обновить update_agent_files — обработка scripts**

В функции `update_agent_files` добавить параметр `scripts=None` и после блока `if data_files:`:

```python
    if scripts:
        install_scripts(name, scripts)
```

**Step 5: Commit**

```bash
git add src/deploy.py
git commit -m "feat: deploy — scripts installation and system deps support"
```

---

### Task 8: orchestration.py — новый pipeline (основная логика)

**Files:**
- Modify: `src/orchestration.py`

Это самая крупная задача. Изменения:

**Step 1: Обновить build_tester_prompt → build_reviewer_prompt**

Переименовать функцию `build_tester_prompt` в `build_reviewer_prompt`. Обновить промпт — добавить проверки дублей, платформы, раздувания. Добавить параметр `previous_soul_md=None` для проверки раздувания при extend:

```python
def build_reviewer_prompt(requirements, artifacts, previous_soul_md=None):
    """Build reviewer prompt with current artifacts."""
    extend_note = ""
    if previous_soul_md:
        extend_note = f"""
Предыдущий SOUL.md агента (до изменений):
{previous_soul_md}

Проверь: не раздулся ли SOUL.md дублями при обновлении. Если одна и та же инструкция повторяется в нескольких местах — это проблема.
"""

    return f"""Проверь артефакты агента на соответствие требованиям.

Требования:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}
{extend_note}
Проверь:
1. SOUL.md описывает все capabilities из требований?
2. Skills покрывают все needs из требований?
3. Нет ли противоречий в инструкциях?
4. Есть ли AGENTS.md с правилами workspace для агента?
5. Есть ли IDENTITY.md с именем, описанием и эмодзи агента?
6. Агент автономен — нет команд переключения (/main, /set, switch)?
7. Нет ли ДУБЛЕЙ — одинаковых по смыслу инструкций в разных местах SOUL.md?
8. Платформо-специфика: для Telegram не экранировать # (писать #AI, не \\#AI), parse_mode корректен?
9. YAGNI — нет лишних возможностей за рамками требований?

Верни JSON:
{{
  "approved": true/false,
  "issues": ["список проблем если есть"],
  "fixes": ["предложения по исправлению"]
}}

Верни ТОЛЬКО JSON."""
```

**Step 2: Обновить build_validator_prompt → build_tester_prompt**

Заменить функцию `build_validator_prompt` на новую `build_tester_prompt`:

```python
def build_tester_prompt(requirements, agent_response):
    """Build tester prompt — evaluates real agent response."""
    return f"""Проверь реальный ответ агента на тестовое сообщение.

Тестовое сообщение: {requirements.get('test_message', 'не указано')}
Ожидаемое поведение: {requirements.get('expected_behavior', 'не указано')}

Реальный ответ агента:
{agent_response}

Полные требования:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

Проверь:
1. Ответ содержит все ожидаемые элементы из expected_behavior?
2. Формат соответствует требованиям?
3. Нет заглушек, "н/д", пустых полей где должны быть данные?
4. Ответ на правильном языке?
5. Нет сообщений об ошибках или traceback?

Верни JSON:
{{
  "approved": true/false,
  "agent_response_preview": "первые 300 символов ответа",
  "issues": ["конкретные проблемы"],
  "reason": "общая оценка"
}}

Верни ТОЛЬКО JSON."""
```

**Step 3: Обновить run_pipeline — новая логика**

Переписать основную функцию `run_pipeline`. Ключевые изменения:

1. Аналитик — без изменений в вызове, но теперь ожидаем `test_message` и `expected_behavior` в ответе
2. Developer — добавить обработку `scripts` и `system_deps`
3. Заменить tester → reviewer (статика, до 3 retry)
4. После reviewer approve — deploy
5. Добавить реальный тестовый запуск агента через `deploy.call_agent()`
6. Тестер (LLM) оценивает ответ агента (до 2 retry)
7. Обновить формирование уведомлений

Основная структура нового `run_pipeline`:

```python
def run_pipeline(task_description):
    # 1. Analyst (без изменений)
    requirements = call_agent_with_retry("analyst", analyst_prompt)

    # 2. Handle reuse/automation_only (без изменений)

    # 3. Developer
    artifacts = call_agent_with_retry("developer", developer_prompt)

    # 4. Reviewer cycle (до 3 retry)
    previous_soul_md = ...  # для extend: текущий SOUL.md
    max_reviewer_retries = 3
    for attempt in range(max_reviewer_retries + 1):
        review = call_agent_with_retry("reviewer",
            build_reviewer_prompt(requirements, artifacts, previous_soul_md))
        if review.get("approved"):
            break
        if attempt < max_reviewer_retries:
            artifacts = call_agent_with_retry("developer", fix_prompt)
            continue
        return {"action": "rejected", ...}

    # 5. Deploy
    if requirements.get("decision") == "extend_existing":
        deploy_result = deploy_extension(requirements, artifacts)
    else:
        deploy_result = deploy_new_agent(requirements, artifacts)

    # 6. Install scripts and deps
    agent_name = deploy_result["agent_name"]
    if artifacts.get("scripts"):
        deploy.install_scripts(agent_name, artifacts["scripts"])
    if artifacts.get("system_deps"):
        deploy.install_system_deps(artifacts["system_deps"])

    # 7. Tester — real agent run (до 2 retry)
    max_tester_retries = 2
    test_message = requirements.get("test_message")
    if test_message:
        for attempt in range(max_tester_retries + 1):
            agent_response = deploy.call_agent(agent_name, test_message)
            test_report = call_agent_with_retry("tester",
                build_tester_prompt(requirements, agent_response))
            if test_report.get("approved"):
                break
            if attempt < max_tester_retries:
                # Developer fixes based on real response
                fix_prompt = build_runtime_fix_prompt(
                    artifacts, test_report, agent_response)
                artifacts = call_agent_with_retry("developer", fix_prompt)
                # Reviewer re-checks
                review = call_agent_with_retry("reviewer",
                    build_reviewer_prompt(requirements, artifacts))
                # Re-deploy
                deploy.update_agent_files(agent_name, ...)
                continue
            # All retries exhausted
            return {"action": "created_with_issues", ...}

    # 8. Return result with test info
    return {
        "action": deploy_result["action"],
        "agent_name": agent_name,
        "test_report": test_report if test_message else None,
        "message": format_notification(deploy_result, requirements, test_report)
    }
```

**Step 4: Добавить функции build_runtime_fix_prompt и format_notification**

```python
def build_runtime_fix_prompt(artifacts, test_report, agent_response):
    """Build developer fix prompt based on real agent behavior."""
    return f"""Тестер проверил реальное поведение агента и нашёл проблемы.

Реальный ответ агента:
{agent_response[:1000]}

Проблемы от тестера: {json.dumps(test_report.get('issues', []), ensure_ascii=False)}
Оценка: {test_report.get('reason', '')}

Исходные артефакты:
{json.dumps(artifacts, ensure_ascii=False, indent=2)}

Исправь артефакты чтобы агент отвечал корректно. Верни обновлённый JSON в том же формате.
ВАЖНО: не дублируй инструкции, делай точечные правки."""


def format_notification(deploy_result, requirements, test_report):
    """Format user notification with test results."""
    action = deploy_result["action"]
    name = deploy_result["agent_name"]

    if action == "created":
        msg = f"Агент '{name}' создан и готов к работе."
    elif action == "extended":
        msg = f"Агент '{name}' обновлён."
    else:
        msg = f"Операция '{action}' завершена для '{name}'."

    if test_report and test_report.get("approved"):
        test_msg = requirements.get("test_message", "")
        reason = test_report.get("reason", "")
        msg += f"\nТест пройден: отправил \"{test_msg}\" — {reason}"

    if action == "created":
        msg += "\nЕсли есть токен Telegram-бота — пришли его чтобы привязать."

    return msg
```

**Step 5: Обновить вызовы в main.py**

В `cmd_create` обновить формирование уведомления — использовать `result.get("message")` напрямую (format_notification уже вызвана в run_pipeline).

**Step 6: Commit**

```bash
git add src/orchestration.py src/main.py
git commit -m "feat: pipeline v2 — reviewer + runtime tester + scripts support"
```

---

### Task 9: Обновить промпт аналитика в orchestration.py

**Files:**
- Modify: `src/orchestration.py` (analyst_prompt в run_pipeline)

**Step 1: Обновить JSON-шаблон аналитика**

В `run_pipeline`, в `analyst_prompt` добавить поля в JSON-шаблон:

```python
  "test_message": "тестовое сообщение для проверки агента",
  "expected_behavior": "описание ожидаемого поведения при получении test_message"
```

Убрать `"skill"` из допустимых значений `agent_type`:
```python
  "agent_type": "interactive_agent" | "automation",
```

Обновить правило heartbeat — заменить текущее описание на:
```
- РАСПИСАНИЕ: если в задаче есть ЛЮБОЕ указание на расписание ("каждый день", "раз в час", "в 10:00", "ежедневно", "по утрам") — ОБЯЗАТЕЛЬНО ставь needs_heartbeat=true и заполняй heartbeat_schedule и heartbeat_message. Без исключений.
```

**Step 2: Commit**

```bash
git add src/orchestration.py
git commit -m "feat: analyst prompt — test cases, strict heartbeat, remove skill type"
```

---

### Task 10: Обновить промпт developer-а в orchestration.py

**Files:**
- Modify: `src/orchestration.py` (developer_prompt в run_pipeline)

**Step 1: Обновить developer_prompt**

Добавить в developer_prompt информацию о scripts и system_deps:

```python
    developer_prompt = f"""Требования от аналитика:
{json.dumps(requirements, ensure_ascii=False, indent=2)}
{current_soul_context}
Сгенерируй конфигурацию агента по своим инструкциям.
{heartbeat_note}

Если задача требует исполняемых скриптов — добавь их в поле "scripts".
Если скрипты требуют системных зависимостей — добавь их в поле "system_deps".

Верни ТОЛЬКО JSON."""
```

**Step 2: Commit**

```bash
git add src/orchestration.py
git commit -m "feat: developer prompt — scripts and system_deps support"
```

---

### Task 11: Деплой и проверка на сервере

**Files:**
- Нет изменений в файлах — операции на сервере

**Step 1: Push и pull**

```bash
git push
ssh root@194.113.37.137 "cd /opt/clawforge && git pull && rm -rf src/__pycache__"
```

**Step 2: Обновить агентов на сервере**

```bash
ssh root@194.113.37.137 "cd /opt/clawforge && python3 setup.py --update"
```

**Step 3: Проверить что reviewer и tester на месте**

```bash
ssh root@194.113.37.137 "ls /root/.openclaw/workspaces/reviewer/SOUL.md /root/.openclaw/workspaces/tester/SOUL.md"
```

**Step 4: Проверить содержимое**

```bash
ssh root@194.113.37.137 "head -3 /root/.openclaw/workspaces/reviewer/SOUL.md"
ssh root@194.113.37.137 "head -3 /root/.openclaw/workspaces/tester/SOUL.md"
```

Expected: `# Reviewer — ClawForge` и `# Tester — ClawForge`

**Step 5: Удалить старого validator с сервера**

```bash
ssh root@194.113.37.137 "openclaw agents delete validator --force 2>/dev/null; rm -rf /root/.openclaw/workspaces/validator /root/.openclaw/agents/validator"
```

**Step 6: Проверить что старый tester на сервере стал reviewer**

```bash
ssh root@194.113.37.137 "grep -l 'Reviewer' /root/.openclaw/workspaces/reviewer/SOUL.md"
```

---

### Task 12: Интеграционный тест — запустить конвейер

**Step 1: Протестировать создание простого агента**

Через Telegram отправить архитектору задачу на создание простого агента (например thesis_maker или аналогичного). Проверить:

- [ ] Конвейер запускается
- [ ] Аналитик возвращает test_message и expected_behavior
- [ ] Reviewer проверяет артефакты (не rubber stamp)
- [ ] Агент деплоится
- [ ] Тестер отправляет реальное сообщение и проверяет ответ
- [ ] Уведомление содержит результат теста
- [ ] Логи в pipeline.log отражают новые этапы (reviewer вместо tester, tester вместо validator)

**Step 2: Протестировать extend**

Отправить задачу на доработку созданного агента. Проверить:

- [ ] Reviewer проверяет на дубли
- [ ] SOUL.md не раздулся
- [ ] Тестер проверяет реальное поведение

---

### Task 13: Обновить документацию

**Files:**
- Modify: `README.md`
- Modify: `README_RU.md`
- Modify: `docs/ARCHITECTURE.md` (если существует)
- Modify: `docs/ARCHITECTURE_RU.md` (если существует)

**Step 1: Обновить описание конвейера во всех файлах**

Заменить упоминания 5 агентов на 4. Обновить схему конвейера:
- `analyst → developer → tester → validator` → `analyst → developer → reviewer → tester`
- Добавить описание двух путей (конвейер + быстрый фикс)
- Обновить описание ролей

**Step 2: Commit**

```bash
git add README.md README_RU.md docs/
git commit -m "docs: update pipeline v2 — 4 agents, reviewer + runtime tester"
```

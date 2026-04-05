# Передача секретов в пайплайне — План реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Architect передаёт секреты в пайплайн через отдельный параметр `--secrets`, LLM-агенты видят только плейсхолдеры `<SECRET:name>`, подстановка реальных значений происходит в Python-коде перед деплоем.

**Architecture:** Новый модуль-уровень state в `orchestration.py` хранит секреты на время работы `run_pipeline()`. Функция `substitute_secrets()` проходит по артефактам Developer-а и заменяет `<SECRET:name>` на реальные значения. Промпты Analyst и Developer инструктируют использовать плейсхолдеры. Architect собирает секреты из чата до запуска пайплайна.

**Tech Stack:** Python 3, regex, JSON CLI parsing.

**Design doc:** `docs/plans/2026-04-05-pipeline-secrets-design.md`

---

### Task 1: Функция substitute_secrets() и маскировка логов

**Files:**
- Modify: `src/orchestration.py` — добавить регулярки, функции, module-level state

**Step 1: Добавить импорты и module-level state**

В `src/orchestration.py` после существующих импортов (перед `PIPELINE_STEP_DELAY = 2`) добавить:

```python
# Module-level state for secrets during pipeline run.
# Set in run_pipeline(), cleared in finally block.
# Used by log masking to avoid passing secrets through every layer.
_PIPELINE_SECRETS = {}

SECRET_PLACEHOLDER_RE = re.compile(r'<SECRET:([a-z][a-z0-9_]*)>')
MALFORMED_PLACEHOLDER_RE = re.compile(r'<SECRET:')
```

**Step 2: Добавить функцию substitute_secrets()**

Добавить после `format_agent_files_for_prompt()`:

```python
def substitute_secrets(artifacts, secrets):
    """Replace <SECRET:name> placeholders in artifacts with real values.

    Raises ValueError if placeholder found but no matching secret provided,
    or if malformed placeholders remain after substitution.
    """
    missing = set()

    def replace(text):
        if not isinstance(text, str):
            return text
        def sub(m):
            name = m.group(1)
            if name not in secrets:
                missing.add(name)
                return m.group(0)
            return secrets[name]
        return SECRET_PLACEHOLDER_RE.sub(sub, text)

    for key in ["soul_md", "agents_md", "identity_md"]:
        if key in artifacts:
            artifacts[key] = replace(artifacts[key])

    for nested_key in ["skills", "data_files", "scripts"]:
        if nested_key in artifacts and isinstance(artifacts[nested_key], dict):
            for fname, content in artifacts[nested_key].items():
                artifacts[nested_key][fname] = replace(content)

    if missing:
        raise ValueError(f"Missing secrets: {', '.join(sorted(missing))}")

    # Check for malformed placeholders left unreplaced
    for key in ["soul_md", "agents_md", "identity_md"]:
        if key in artifacts and isinstance(artifacts[key], str):
            if MALFORMED_PLACEHOLDER_RE.search(artifacts[key]):
                raise ValueError(f"Malformed secret placeholder in {key}")
    for nested_key in ["skills", "data_files", "scripts"]:
        if nested_key in artifacts and isinstance(artifacts[nested_key], dict):
            for fname, content in artifacts[nested_key].items():
                if isinstance(content, str) and MALFORMED_PLACEHOLDER_RE.search(content):
                    raise ValueError(f"Malformed secret placeholder in {nested_key}/{fname}")

    return artifacts
```

**Step 3: Добавить функцию mask_secrets_in_text()**

Добавить сразу после `substitute_secrets()`:

```python
def mask_secrets_in_text(text):
    """Replace secret values with *** in text using _PIPELINE_SECRETS.

    Only masks values with length >= 8 to avoid accidentally masking
    common words.
    """
    if not _PIPELINE_SECRETS:
        return text
    for value in _PIPELINE_SECRETS.values():
        if value and len(value) >= 8:
            text = text.replace(value, "***")
    return text
```

**Step 4: Проверить синтаксис Python**

Run: `python3 -c "import ast; ast.parse(open('d:/dev/ClawForge/src/orchestration.py').read()); print('ok')"`
Expected: `ok`

**Step 5: Коммит**

```bash
cd d:/dev/ClawForge
git add src/orchestration.py
git commit -m "feat: add substitute_secrets() and mask_secrets_in_text() utilities"
```

---

### Task 2: Интеграция secrets в run_pipeline и log_pipeline_event

**Files:**
- Modify: `src/orchestration.py` — сигнатура run_pipeline, установка _PIPELINE_SECRETS, вызов substitute_secrets перед deploy, маскировка в log_pipeline_event

**Step 1: Обновить сигнатуру run_pipeline()**

Найти:
```python
def run_pipeline(task_description):
    """Run the full creation pipeline: analyst -> developer -> reviewer -> deploy -> tester."""
```

Заменить на:
```python
def run_pipeline(task_description, secrets=None):
    """Run the full creation pipeline: analyst -> developer -> reviewer -> deploy -> tester.

    Args:
        task_description: user task text (may contain <SECRET:name> placeholders)
        secrets: dict mapping secret names to real values. Used to substitute
                 placeholders in artifacts before deploy. Never passed to LLMs.
    """
    global _PIPELINE_SECRETS
    _PIPELINE_SECRETS = secrets or {}
    try:
        return _run_pipeline_impl(task_description)
    finally:
        _PIPELINE_SECRETS = {}
```

**Step 2: Переименовать тело функции в _run_pipeline_impl**

Переименовать старую функцию `run_pipeline` (её тело) в `_run_pipeline_impl`. То есть текущее тело `run_pipeline` становится `_run_pipeline_impl(task_description)`.

Найти (после добавления нового run_pipeline):
```python
def run_pipeline(task_description, secrets=None):
    ...
    try:
        return _run_pipeline_impl(task_description)
    finally:
        _PIPELINE_SECRETS = {}
```

И ниже старое тело — переименовать `def run_pipeline(task_description):` (которое раньше было единственным) в `def _run_pipeline_impl(task_description):`. Если тело стоит рядом — оставить одно определение с новым именем.

ВАЖНО: убедиться что в файле осталось ровно одно определение `run_pipeline` (новое обёртка) и одно `_run_pipeline_impl` (старое тело).

**Step 3: Вызвать substitute_secrets перед deploy**

Найти блок после Reviewer approved (приблизительно строка 410 в orchestration.py, после `for reviewer_attempt in range(max_reviewer_retries + 1):` цикла и его break/return):

```python
    # 7. Deploy
    agent_name = requirements["agent_name"]

    if requirements.get("decision") == "extend_existing":
        deploy_result = deploy_extension(requirements, artifacts)
    else:
        deploy_result = deploy_new_agent(requirements, artifacts)
```

Перед этим блоком добавить:

```python
    # Substitute secrets before deploy
    try:
        artifacts = substitute_secrets(artifacts, _PIPELINE_SECRETS)
    except ValueError as e:
        return {
            "action": "rejected",
            "agent_name": requirements.get("agent_name", "?"),
            "issues": [str(e)],
            "message": (
                f"Не удалось создать агента: в артефактах остались "
                f"нераскрытые секреты ({e}). Это внутренняя ошибка пайплайна. "
                f"Попробуй создать агента заново."
            )
        }
```

**Step 4: Добавить маскировку в log_pipeline_event**

Найти:

```python
def log_pipeline_event(agent_name, prompt, response, status):
    """Log pipeline events to file."""
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "pipeline.log")

    timestamp = datetime.datetime.now().isoformat()
    prompt_short = prompt[:200].replace('\n', ' ')
    response_short = response[:500].replace('\n', ' ')
```

Заменить строки `prompt_short` и `response_short` на:

```python
    timestamp = datetime.datetime.now().isoformat()
    prompt_short = mask_secrets_in_text(prompt[:200].replace('\n', ' '))
    response_short = mask_secrets_in_text(response[:500].replace('\n', ' '))
```

**Step 5: Проверить синтаксис**

Run: `python3 -c "import ast; ast.parse(open('d:/dev/ClawForge/src/orchestration.py').read()); print('ok')"`
Expected: `ok`

**Step 6: Коммит**

```bash
cd d:/dev/ClawForge
git add src/orchestration.py
git commit -m "feat: run_pipeline accepts secrets, substitutes before deploy, masks in logs"
```

---

### Task 3: Обновить промпты Analyst и Developer для работы с плейсхолдерами

**Files:**
- Modify: `src/orchestration.py` — правила в analyst_prompt и developer_prompt

**Step 1: Обновить правило про секреты в analyst_prompt**

Найти в analyst_prompt (примерно строка 286):

```
- НИКОГДА не включай токены, ключи и секреты в heartbeat_message или requirements. Агент читает токен из openclaw.json самостоятельно.
```

Заменить на:

```
- НИКОГДА не включай токен Telegram-бота в heartbeat_message или requirements — агент читает его из openclaw.json. Для других внешних секретов (пароли, API-ключи) используй плейсхолдеры <SECRET:name> как описано ниже.
- Плейсхолдеры секретов: если в задаче встречаешь <SECRET:name> — НЕ пытайся раскрыть или угадать значение. Это указатель на внешний секрет. В requirements используй этот же плейсхолдер как есть. Developer получит тот же плейсхолдер, подстановка реального значения происходит автоматически перед деплоем.
```

**Step 2: Обновить developer_prompt**

Найти (примерно строка 358 после формирования `reference_context`):

```python
    developer_prompt = f"""Требования от аналитика:
{json.dumps(requirements, ensure_ascii=False, indent=2)}
{current_agent_context}{reference_context}
Сгенерируй конфигурацию агента по своим инструкциям.
{heartbeat_note}
Если задача требует исполняемых скриптов — добавь их в поле "scripts".
Если скрипты требуют системных зависимостей — добавь их в поле "system_deps".

Верни ТОЛЬКО JSON."""
```

Заменить на:

```python
    developer_prompt = f"""Требования от аналитика:
{json.dumps(requirements, ensure_ascii=False, indent=2)}
{current_agent_context}{reference_context}
Сгенерируй конфигурацию агента по своим инструкциям.
{heartbeat_note}
Если задача требует исполняемых скриптов — добавь их в поле "scripts".
Если скрипты требуют системных зависимостей — добавь их в поле "system_deps".

Плейсхолдеры секретов: если в requirements или в data_files тебе нужен пароль, токен или API-ключ — используй плейсхолдер вида <SECRET:name> (где name — snake_case идентификатор, например <SECRET:caldav_password>). НЕ подставляй placeholder-строки типа YOUR_PASSWORD_HERE, TODO, CHANGEME, REPLACE_ME — они не будут заменены и агент упадёт при первом запуске. Только формат <SECRET:name>. Имя должно совпадать с именем плейсхолдера из requirements.

Верни ТОЛЬКО JSON."""
```

**Step 3: Проверить синтаксис**

Run: `python3 -c "import ast; ast.parse(open('d:/dev/ClawForge/src/orchestration.py').read()); print('ok')"`
Expected: `ok`

**Step 4: Коммит**

```bash
cd d:/dev/ClawForge
git add src/orchestration.py
git commit -m "feat: instruct Analyst and Developer to use <SECRET:name> placeholders"
```

---

### Task 4: Добавить --secrets в main.py

**Files:**
- Modify: `src/main.py` — аргумент --secrets, парсинг JSON, передача в run_pipeline

**Step 1: Добавить аргумент в парсер**

Найти в `main()`:

```python
    p_create = subparsers.add_parser("create", help="Create a new agent from task description")
    p_create.add_argument("--task", required=True, help="Task description")
    p_create.add_argument("--notify", help="Notify target after completion (e.g. telegram:541534272)")
    p_create.set_defaults(func=cmd_create)
```

Добавить `--secrets` перед `p_create.set_defaults`:

```python
    p_create = subparsers.add_parser("create", help="Create a new agent from task description")
    p_create.add_argument("--task", required=True, help="Task description")
    p_create.add_argument("--notify", help="Notify target after completion (e.g. telegram:541534272)")
    p_create.add_argument("--secrets", default="{}", help="JSON object with secrets to substitute into agent artifacts")
    p_create.set_defaults(func=cmd_create)
```

**Step 2: Парсить secrets в cmd_create**

Найти начало `cmd_create`:

```python
def cmd_create(args):
    if args.notify:
```

Добавить парсинг перед `if args.notify:`:

```python
def cmd_create(args):
    try:
        secrets = json.loads(args.secrets)
        if not isinstance(secrets, dict):
            raise ValueError("secrets must be a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Invalid --secrets JSON: {e}")
        sys.exit(1)

    if args.notify:
```

**Step 3: Передать secrets в run_pipeline**

Найти ОБА вызова `orchestration.run_pipeline(args.task)` в `cmd_create`:

1. Внутри child fork:
```python
            result = orchestration.run_pipeline(args.task)
```

2. В else-ветке (без notify):
```python
    else:
        result = orchestration.run_pipeline(args.task)
```

Заменить на:

1.
```python
            result = orchestration.run_pipeline(args.task, secrets)
```

2.
```python
    else:
        result = orchestration.run_pipeline(args.task, secrets)
```

**Step 4: Проверить синтаксис**

Run: `python3 -c "import ast; ast.parse(open('d:/dev/ClawForge/src/main.py').read()); print('ok')"`
Expected: `ok`

**Step 5: Коммит**

```bash
cd d:/dev/ClawForge
git add src/main.py
git commit -m "feat: main.py accepts --secrets JSON and passes to pipeline"
```

---

### Task 5: Обновить skill claw-forge с параметром --secrets

**Files:**
- Modify: `skills/claw-forge/SKILL.md` — команда create с --secrets

**Step 1: Обновить команду create**

Найти в `skills/claw-forge/SKILL.md`:

```markdown
## Создать агента или автоматизацию

Когда пользователь описывает задачу и нужно создать агента:

\`\`\`bash
python3 /opt/clawforge/src/main.py create --task "<описание задачи пользователя>" --notify telegram:{{TELEGRAM_USER_ID}}
\`\`\`

Скрипт запустится в фоне. НЕ жди завершения — она работает в фоне.
Результат придёт пользователю в чат автоматически.
```

Заменить на:

```markdown
## Создать агента или автоматизацию

Когда пользователь описывает задачу и нужно создать агента:

\`\`\`bash
python3 /opt/clawforge/src/main.py create \
  --task "<описание задачи с плейсхолдерами <SECRET:name> вместо реальных секретов>" \
  --secrets '<JSON с секретами или {}>' \
  --notify telegram:{{TELEGRAM_USER_ID}}
\`\`\`

**Секреты:** если пользователь упомянул пароли, токены или API-ключи — вынеси их в отдельный JSON, в описании задачи замени на плейсхолдеры `<SECRET:name>`.

Пример с секретом:
\`\`\`bash
python3 /opt/clawforge/src/main.py create \
  --task "Создай агента calendario. Логин: user@yandex.ru, пароль: <SECRET:caldav_password>" \
  --secrets '{"caldav_password":"lercvpyhlsvplqym"}' \
  --notify telegram:{{TELEGRAM_USER_ID}}
\`\`\`

Если секретов нет — передавай пустой объект `--secrets '{}'`.

Скрипт запустится в фоне. НЕ жди завершения — она работает в фоне.
Результат придёт пользователю в чат автоматически.
```

**Step 2: Коммит**

```bash
cd d:/dev/ClawForge
git add skills/claw-forge/SKILL.md
git commit -m "feat: skill claw-forge — document --secrets parameter for create"
```

---

### Task 6: Добавить правило сбора секретов в Architect SOUL.md

**Files:**
- Modify: `agents/architect/SOUL.md` — добавить секцию про сбор секретов

**Step 1: Добавить секцию про секреты**

В `agents/architect/SOUL.md` найти секцию "### Шаг 2: Подтверди перед запуском" (примерно строка 120):

```markdown
### Шаг 2: Подтверди перед запуском

После получения ответов — ОБЯЗАТЕЛЬНО:
1. Кратко резюмируй что понял (1-2 предложения)
2. Спроси: "Запускаю создание? Или хочешь ещё что-то обсудить/уточнить?"
3. Жди явного подтверждения ("да", "запускай", "ок")
4. ТОЛЬКО после подтверждения вызови skill claw-forge
```

Перед этой секцией добавить новую секцию:

```markdown
### Сбор секретов (перед запуском)

Перед вызовом skill claw-forge проверь: упоминал ли пользователь пароли, токены, API-ключи, секреты для внешних сервисов (не путать с токеном Telegram-бота — он обрабатывается отдельно после создания).

Если да:
1. Вынеси каждый секрет в отдельную пару ключ-значение, где ключ — snake_case имя (например `caldav_password`, `openai_api_key`, `smtp_password`), значение — реальный секрет
2. В описании задачи замени реальные значения на плейсхолдеры вида `<SECRET:имя>`
3. Передай secrets в skill отдельным параметром

Если задача требует секрет, но пользователь его не прислал — СНАЧАЛА запроси его в чате, получи, потом запускай конвейер.

Это применяется и для создания нового агента, и для доработки существующего.

```

**Step 2: Коммит**

```bash
cd d:/dev/ClawForge
git add agents/architect/SOUL.md
git commit -m "feat: architect — collect secrets from chat before pipeline launch"
```

---

### Task 7: Финальная проверка и деплой

**Files:**
- None (проверка существующих)

**Step 1: Проверить синтаксис Python всех изменённых файлов**

Run:
```bash
python3 -c "import ast; ast.parse(open('d:/dev/ClawForge/src/orchestration.py').read()); print('orchestration.py ok')"
python3 -c "import ast; ast.parse(open('d:/dev/ClawForge/src/main.py').read()); print('main.py ok')"
```
Expected:
```
orchestration.py ok
main.py ok
```

**Step 2: Проверить что все коммиты на месте**

Run: `cd d:/dev/ClawForge && git log --oneline -8`
Expected: 6 новых коммитов сверху (tasks 1-6).

**Step 3: Push и деплой**

```bash
cd d:/dev/ClawForge
git push
ssh root@194.113.37.137 "cd /opt/clawforge && git pull && rm -rf src/__pycache__ && python3 setup.py --update"
```

Expected: `=== Update complete ===`

**Step 4: Smoke-тест на сервере**

Run:
```bash
ssh root@194.113.37.137 "cd /opt/clawforge && python3 -c \"import sys; sys.path.insert(0, 'src'); from orchestration import substitute_secrets, SECRET_PLACEHOLDER_RE, mask_secrets_in_text; print('imports ok')\""
```
Expected: `imports ok`

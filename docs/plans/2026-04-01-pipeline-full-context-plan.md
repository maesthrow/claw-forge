# Улучшение пайплайна: полная загрузка контекста агентов — План реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Developer при extend_existing и create_new с reference_agents получает все файлы агента, Architect загружает контекст агента перед выбором пути доработки.

**Architecture:** Новая функция `load_agent_files()` в orchestration.py собирает все файлы из workspace агента. Промпты Developer и Reviewer формируются с полным контекстом. Инструкции агентов (SOUL.md, AGENTS.md) обновляются для поддержки новых сценариев.

**Tech Stack:** Python 3, OpenClaw workspace файловая система, Markdown инструкции агентов.

**Design doc:** `docs/plans/2026-04-01-pipeline-full-context-design.md`

---

### Task 1: Функция load_agent_files() в orchestration.py

**Files:**
- Modify: `src/orchestration.py` — добавить функцию после `validate_agent_name()` (после строки 33)

**Step 1: Написать функцию load_agent_files()**

Добавить в `src/orchestration.py` после функции `validate_agent_name()`:

```python
def load_agent_files(workspace_path):
    """Load all agent files from workspace for context passing.
    
    Returns dict with file contents:
    {
        "SOUL.md": "...",
        "AGENTS.md": "...",
        "IDENTITY.md": "...",
        "skills": {"skill-name/SKILL.md": "..."},
        "scripts": {"script.js": "..."}
    }
    """
    files = {}
    
    # Core markdown files
    for fname in ["SOUL.md", "AGENTS.md", "IDENTITY.md"]:
        fpath = os.path.join(workspace_path, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                files[fname] = f.read()
        except FileNotFoundError:
            pass
    
    # Skills
    skills = {}
    skills_dir = os.path.join(workspace_path, "skills")
    if os.path.isdir(skills_dir):
        for skill_name in os.listdir(skills_dir):
            skill_md = os.path.join(skills_dir, skill_name, "SKILL.md")
            try:
                with open(skill_md, "r", encoding="utf-8") as f:
                    skills[f"skills/{skill_name}/SKILL.md"] = f.read()
            except FileNotFoundError:
                pass
    if skills:
        files["skills"] = skills
    
    # Scripts
    scripts = {}
    scripts_dir = os.path.join(workspace_path, "scripts")
    if os.path.isdir(scripts_dir):
        for script_name in os.listdir(scripts_dir):
            script_path = os.path.join(scripts_dir, script_name)
            if os.path.isfile(script_path):
                try:
                    with open(script_path, "r", encoding="utf-8") as f:
                        scripts[f"scripts/{script_name}"] = f.read()
                except (FileNotFoundError, UnicodeDecodeError):
                    pass
    if scripts:
        files["scripts"] = scripts
    
    return files
```

**Step 2: Написать функцию format_agent_files_for_prompt()**

Добавить сразу после `load_agent_files()`:

```python
def format_agent_files_for_prompt(files, label):
    """Format loaded agent files into a prompt block.
    
    Args:
        files: dict from load_agent_files()
        label: context label, e.g. "Текущие файлы агента (ОБНОВИ их, не переписывай с нуля)"
    """
    parts = [f"\n{label}:\n"]
    
    # Core files
    for fname in ["SOUL.md", "AGENTS.md", "IDENTITY.md"]:
        if fname in files:
            parts.append(f"=== {fname} ===\n{files[fname]}\n")
    
    # Skills
    if "skills" in files:
        for skill_path, content in files["skills"].items():
            parts.append(f"=== {skill_path} ===\n{content}\n")
    
    # Scripts
    if "scripts" in files:
        for script_path, content in files["scripts"].items():
            parts.append(f"=== {script_path} ===\n{content}\n")
    
    return "\n".join(parts)
```

**Step 3: Проверить что файл не сломан**

Run: `cd /opt/clawforge && python3 -c "import src.orchestration; print('ok')"`
Expected: `ok`

**Step 4: Коммит**

```bash
git add src/orchestration.py
git commit -m "feat: add load_agent_files() and format_agent_files_for_prompt()"
```

---

### Task 2: Полная загрузка контекста при extend_existing

**Files:**
- Modify: `src/orchestration.py` — заменить блок загрузки current_soul_context (строки 256-265) и обновить промпт Developer-а

**Step 1: Заменить загрузку current_soul_context на current_agent_context**

В функции `run_pipeline()` найти блок (строки 256-265):

```python
    # For extend: include current SOUL.md so developer can update it
    current_soul_context = ""
    if requirements.get("decision") == "extend_existing" and requirements.get("extend_agent"):
        agent_info = registry.get_agent(requirements["extend_agent"])
        if agent_info and agent_info.get("workspace_path"):
            soul_path = os.path.join(agent_info["workspace_path"], "SOUL.md")
            try:
                with open(soul_path, "r", encoding="utf-8") as f:
                    current_soul_context = f"\nТекущий SOUL.md агента (обнови его, не пиши с нуля):\n{f.read()}\n"
            except FileNotFoundError:
                pass
```

Заменить на:

```python
    # For extend: include all current agent files so developer can update them
    current_agent_context = ""
    previous_agent_files = None
    if requirements.get("decision") == "extend_existing" and requirements.get("extend_agent"):
        agent_info = registry.get_agent(requirements["extend_agent"])
        if agent_info and agent_info.get("workspace_path"):
            previous_agent_files = load_agent_files(agent_info["workspace_path"])
            if previous_agent_files:
                current_agent_context = format_agent_files_for_prompt(
                    previous_agent_files,
                    "Текущие файлы агента (ОБНОВИ их, не переписывай с нуля)"
                )
```

**Step 2: Обновить промпт Developer-а**

Найти (строка 267):

```python
    developer_prompt = f"""Требования от аналитика:
{json.dumps(requirements, ensure_ascii=False, indent=2)}
{current_soul_context}
```

Заменить на:

```python
    developer_prompt = f"""Требования от аналитика:
{json.dumps(requirements, ensure_ascii=False, indent=2)}
{current_agent_context}
```

**Step 3: Обновить переменную previous_soul_md для Reviewer**

Найти (строки 282-284):

```python
    # Save previous SOUL.md for extend comparison
    previous_soul_md = None
    if current_soul_context:
        previous_soul_md = current_soul_context
```

Заменить на:

```python
    # Save previous agent files for extend comparison by reviewer
    previous_agent_context = None
    if previous_agent_files:
        previous_agent_context = format_agent_files_for_prompt(
            previous_agent_files,
            "Предыдущие файлы агента (до изменений)"
        )
```

**Step 4: Обновить вызовы build_reviewer_prompt**

Найти все вызовы `build_reviewer_prompt` в `run_pipeline()` и заменить `previous_soul_md` на `previous_agent_context`:

1. Строка 289-290:
```python
        review = call_agent_with_retry("reviewer",
            build_reviewer_prompt(requirements, artifacts, previous_soul_md))
```
→
```python
        review = call_agent_with_retry("reviewer",
            build_reviewer_prompt(requirements, artifacts, previous_agent_context))
```

2. Строка 367-368:
```python
                review = call_agent_with_retry("reviewer",
                    build_reviewer_prompt(requirements, artifacts, previous_soul_md))
```
→
```python
                review = call_agent_with_retry("reviewer",
                    build_reviewer_prompt(requirements, artifacts, previous_agent_context))
```

**Step 5: Обновить функцию build_reviewer_prompt**

Найти (строка 35):

```python
def build_reviewer_prompt(requirements, artifacts, previous_soul_md=None):
    """Build reviewer prompt — static checks on artifacts."""
    extend_note = ""
    if previous_soul_md:
        extend_note = f"""
Предыдущий SOUL.md агента (до изменений):
{previous_soul_md}

Проверь: не раздулся ли SOUL.md дублями при обновлении. Если одна и та же инструкция повторяется в нескольких местах — это проблема.
"""
```

Заменить на:

```python
def build_reviewer_prompt(requirements, artifacts, previous_agent_context=None):
    """Build reviewer prompt — static checks on artifacts."""
    extend_note = ""
    if previous_agent_context:
        extend_note = f"""
{previous_agent_context}

Проверь: не раздулись ли файлы дублями при обновлении. Если одна и та же инструкция повторяется в нескольких местах — это проблема. Если skills или scripts не изменились — они должны остаться идентичными оригиналу.
"""
```

**Step 6: Проверить что файл не сломан**

Run: `cd /opt/clawforge && python3 -c "import src.orchestration; print('ok')"`
Expected: `ok`

**Step 7: Коммит**

```bash
git add src/orchestration.py
git commit -m "feat: extend_existing loads all agent files for Developer and Reviewer"
```

---

### Task 3: Загрузка файлов референсных агентов при create_new

**Files:**
- Modify: `src/orchestration.py` — добавить блок загрузки reference_agents после формирования current_agent_context

**Step 1: Добавить загрузку референсов**

В `run_pipeline()`, после блока загрузки `current_agent_context` (новый код из Task 2) и перед формированием `developer_prompt`, добавить:

```python
    # For create_new: load reference agent files if specified
    reference_context = ""
    if requirements.get("decision") == "create_new" and requirements.get("reference_agents"):
        ref_parts = []
        for ref_name in requirements["reference_agents"]:
            ref_agent = registry.get_agent(ref_name)
            if ref_agent and ref_agent.get("workspace_path"):
                ref_files = load_agent_files(ref_agent["workspace_path"])
                if ref_files:
                    ref_parts.append(f"--- Агент: {ref_name} ---\n")
                    for fname in ["SOUL.md", "AGENTS.md", "IDENTITY.md"]:
                        if fname in ref_files:
                            ref_parts.append(f"=== {fname} ===\n{ref_files[fname]}\n")
                    if "skills" in ref_files:
                        for skill_path, content in ref_files["skills"].items():
                            ref_parts.append(f"=== {skill_path} ===\n{content}\n")
                    if "scripts" in ref_files:
                        for script_path, content in ref_files["scripts"].items():
                            ref_parts.append(f"=== {script_path} ===\n{content}\n")
        if ref_parts:
            reference_context = (
                "\nФайлы похожего агента для РЕФЕРЕНСА "
                "(используй как образец структуры и стиля, "
                "но создавай новые файлы под новые требования, НЕ копируй):\n\n"
                + "\n".join(ref_parts)
            )
```

**Step 2: Добавить reference_context в промпт Developer-а**

Обновить формирование `developer_prompt` (результат Task 2):

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

**Step 3: Проверить что файл не сломан**

Run: `cd /opt/clawforge && python3 -c "import src.orchestration; print('ok')"`
Expected: `ok`

**Step 4: Коммит**

```bash
git add src/orchestration.py
git commit -m "feat: create_new loads reference agent files for Developer"
```

---

### Task 4: Обновить Analyst SOUL.md

**Files:**
- Modify: `agents/analyst/SOUL.md`

**Step 1: Добавить правило reference_agents**

В `agents/analyst/SOUL.md` найти секцию "## Принятие решений", после пункта `create_new` добавить:

```markdown
  При create_new: если в системе есть агент, который решает **очень близкую задачу** и его структура реально полезна как образец — обязательно укажи его в `reference_agents`. Не указывай агентов которые просто "тоже работают с текстом" или "тоже используют API". Пример хорошего референса: есть `currency_tracker`, создаётся `stock_tracker` — оба трекеры с подпиской и рассылкой. Пример плохого: есть `currency_tracker`, создаётся `quiz_bot` — ничего общего кроме Telegram.
```

**Step 2: Коммит**

```bash
git add agents/analyst/SOUL.md
git commit -m "feat: analyst — explicit reference_agents usage rule"
```

---

### Task 5: Обновить Developer SOUL.md

**Files:**
- Modify: `agents/developer/SOUL.md`

**Step 1: Дополнить правило extend**

В `agents/developer/SOUL.md` найти в конце файла:

```markdown
При extend: ОБНОВИ существующий файл — не переписывай с нуля. Если инструкция уже есть — не добавляй повторно. Если нужно изменить — замени, не дублируй.
```

Заменить на:

```markdown
При extend: ты получаешь ВСЕ текущие файлы агента (SOUL.md, AGENTS.md, IDENTITY.md, skills, scripts). Обновляй каждый файл точечно — не переписывай с нуля. Если файл не требует изменений — верни его как есть. Не удаляй существующие skills и scripts если это не требуется явно. Если инструкция уже есть — не добавляй повторно. Если нужно изменить — замени, не дублируй.

При create_new с референсом: ты можешь получить файлы похожего агента — используй их как образец структуры и стиля, но создавай новые файлы под новые требования. Не копируй референс — вдохновляйся.
```

**Step 2: Коммит**

```bash
git add agents/developer/SOUL.md
git commit -m "feat: developer — full file context rules for extend and reference"
```

---

### Task 6: Обновить Reviewer SOUL.md

**Files:**
- Modify: `agents/reviewer/SOUL.md`

**Step 1: Дополнить проверку extend**

В `agents/reviewer/SOUL.md` найти пункт 11:

```markdown
11. **Раздувание при extend** — если предоставлен предыдущий SOUL.md и новый значительно больше, проверь что рост обоснован новым функционалом, а не дублями.
```

Заменить на:

```markdown
11. **Раздувание при extend** — если предоставлены предыдущие файлы агента и новые значительно больше, проверь что рост обоснован новым функционалом, а не дублями. Проверяй все файлы, не только SOUL.md. Если skills или scripts не изменились — они должны остаться идентичными оригиналу.
```

**Step 2: Коммит**

```bash
git add agents/reviewer/SOUL.md
git commit -m "feat: reviewer — check all files for bloat on extend"
```

---

### Task 7: Обновить Architect SOUL.md и AGENTS.md

**Files:**
- Modify: `agents/architect/SOUL.md` — секция "Доработка агентов — выбор пути"
- Modify: `agents/architect/AGENTS.md` — секция "Быстрый фикс"

**Step 1: Заменить секцию доработки в SOUL.md**

В `agents/architect/SOUL.md` найти секцию (строки 69-86):

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
4. ОБЯЗАТЕЛЬНО проверь результат:
   - Сбрось сессию агента: `/new` или через sessions tool — чтобы агент подхватил изменённые файлы
   - Запусти агента как субагента с тестовым сообщением, дождись ответа и сам оцени результат
   - Если результат не тот — исправь и проверь снова (до 2 раз)
   ВАЖНО: для запуска субагентов используй нативный tool запуска субагентов. НЕ используй exec с CLI-командами — они не дожидаются результата.
```

Заменить на:

```markdown
## Доработка агентов — выбор пути

При запросе на доработку существующего агента:

### Шаг 0: Загрузи контекст агента (ОБЯЗАТЕЛЬНО)
Прочитай все файлы агента — SOUL.md, AGENTS.md, IDENTITY.md, skills, scripts.
Пойми текущее состояние прежде чем что-то менять или запускать конвейер.

### Шаг 1: Оцени масштаб и выбери путь

**Полный конвейер (через skill claw-forge)**
Когда: новая capability, новый skill, значительное изменение поведения, добавление скриптов.
→ Вызови skill claw-forge. В описании задачи кратко опиши текущее состояние агента, чтобы Analyst получил контекст.

**Быстрый фикс (самостоятельно)**
Когда: точечная правка текста, формата, стиля, исправление конкретного бага.
1. Внеси точечные изменения в нужные файлы (не переписывай весь файл)
2. Запиши обновлённые файлы
3. ОБЯЗАТЕЛЬНО проверь результат:
   - Сбрось сессию агента: `/new` или через sessions tool — чтобы агент подхватил изменённые файлы
   - Запусти агента как субагента с тестовым сообщением, дождись ответа и сам оцени результат
   - Если результат не тот — исправь и проверь снова (до 2 раз)
   ВАЖНО: для запуска субагентов используй нативный tool запуска субагентов. НЕ используй exec с CLI-командами — они не дожидаются результата.
```

**Step 2: Обновить секцию быстрого фикса в AGENTS.md**

В `agents/architect/AGENTS.md` найти:

```markdown
## Быстрый фикс
- После ЛЮБОЙ прямой правки файлов агента — вызови тестера для проверки
- Не пропускай тестирование даже для «мелких» правок
- Если тестер нашёл проблему — исправь и протестируй снова (до 2 раз)
```

Заменить на:

```markdown
## Быстрый фикс
- Перед правкой — загрузи и прочитай все файлы агента (SOUL.md, AGENTS.md, IDENTITY.md, skills, scripts)
- После ЛЮБОЙ прямой правки файлов агента — вызови тестера для проверки
- Не пропускай тестирование даже для «мелких» правок
- Если тестер нашёл проблему — исправь и протестируй снова (до 2 раз)
```

**Step 3: Коммит**

```bash
git add agents/architect/SOUL.md agents/architect/AGENTS.md
git commit -m "feat: architect — load full agent context before choosing fix path"
```

---

### Task 8: Финальная проверка

**Step 1: Проверить синтаксис Python**

Run: `cd /opt/clawforge && python3 -c "import src.orchestration; print('ok')"`
Expected: `ok`

**Step 2: Проверить что все файлы агентов валидные**

Run: `cd /opt/clawforge && for f in agents/*/SOUL.md agents/*/AGENTS.md; do echo "=== $f ===" && head -1 "$f"; done`
Expected: заголовки всех файлов без ошибок

**Step 3: Финальный коммит не нужен — все изменения уже закоммичены по задачам**

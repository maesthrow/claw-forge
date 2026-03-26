# Pipeline Retry Resilience — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Разделить API-ошибки и JSON-ошибки в пайплайне, добавить экспоненциальный backoff для rate limit и превентивную задержку между шагами.

**Architecture:** Вся логика в `orchestration.py`. Новая функция `is_api_error()` детектит ошибки API. Новая `_call_with_api_retry()` оборачивает `deploy.call_agent()` с backoff. `call_agent_with_retry()` переработана — API-retry отделён от JSON-retry. `run_pipeline()` получает `time.sleep()` между шагами.

**Tech Stack:** Python 3.10+, стандартная библиотека (json, time)

**Design doc:** `docs/plans/2026-03-26-pipeline-retry-resilience-design.md`

---

### Task 1: Добавить `is_api_error()` и `_call_with_api_retry()`

**Files:**
- Modify: `src/orchestration.py:1-10` (imports)
- Modify: `src/orchestration.py:437-463` (новые функции перед `call_agent_with_retry`)

**Step 1: Добавить `import time` в imports**

```python
import datetime
import json
import os
import re
import time

import deploy
import registry
```

**Step 2: Добавить `is_api_error()` после `parse_json_response` (после строки 434)**

```python
def is_api_error(response):
    """Detect OpenClaw API errors (rate limit, timeouts) vs actual LLM responses."""
    text = response.strip()
    if text.startswith("\u26a0\ufe0f"):
        return True
    api_markers = ["rate limit", "try again later", "connection refused", "service unavailable"]
    return any(m in text.lower() for m in api_markers)
```

**Step 3: Добавить `_call_with_api_retry()` после `is_api_error`**

```python
def _call_with_api_retry(agent_name, prompt, max_retries=5):
    """Call agent, retrying on API errors with exponential backoff."""
    for attempt in range(max_retries + 1):
        response = deploy.call_agent(agent_name, prompt)
        if not is_api_error(response):
            return response
        if attempt < max_retries:
            delay = 5 * (3 ** attempt)  # 5s, 15s, 45s, 135s, 405s
            log_pipeline_event(
                agent_name, "api_retry", response,
                f"api_error attempt {attempt + 1}/{max_retries}, waiting {delay}s"
            )
            time.sleep(delay)
    return response
```

**Step 4: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('src/orchestration.py').read()); print('OK')"`
Expected: `OK`

---

### Task 2: Переработать `call_agent_with_retry()`

**Files:**
- Modify: `src/orchestration.py` — заменить текущую `call_agent_with_retry` целиком

**Step 1: Заменить `call_agent_with_retry` на новую версию**

```python
def call_agent_with_retry(agent_name, prompt, max_retries=2):
    """Call agent and parse JSON response.

    Two-phase retry:
    - Phase 1: API-level retry with backoff (rate limit, timeouts) — handled by _call_with_api_retry
    - Phase 2: JSON-level retry with explicit instruction (LLM returned non-JSON)
    """
    response = _call_with_api_retry(agent_name, prompt)
    log_pipeline_event(agent_name, prompt, response, "ok")

    try:
        return parse_json_response(response)
    except (json.JSONDecodeError, ValueError) as e:
        log_pipeline_event(agent_name, prompt, response, f"parse_error: {e}")

    # Retry with explicit JSON instruction
    for attempt in range(max_retries):
        retry_prompt = (
            f"Предыдущий ответ не удалось распарсить как JSON. "
            f"Верни ТОЛЬКО валидный JSON без какого-либо текста до или после. "
            f"Никаких пояснений, только JSON.\n\n"
            f"Исходный запрос:\n{prompt}"
        )
        response = _call_with_api_retry(agent_name, retry_prompt)
        log_pipeline_event(agent_name, f"retry_{attempt + 1}", response, "retry")

        try:
            return parse_json_response(response)
        except (json.JSONDecodeError, ValueError):
            continue

    raise ValueError(f"Agent {agent_name} failed to return valid JSON after {max_retries} retries")
```

**Step 2: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('src/orchestration.py').read()); print('OK')"`
Expected: `OK`

---

### Task 3: Добавить задержку между шагами пайплайна

**Files:**
- Modify: `src/orchestration.py:68-270` (функция `run_pipeline`)

**Step 1: Добавить константу в начало файла (после imports)**

```python
PIPELINE_STEP_DELAY = 2  # seconds between pipeline steps to avoid rate limits
```

**Step 2: Добавить `time.sleep(PIPELINE_STEP_DELAY)` в `run_pipeline`**

Места вставки (после каждого `call_agent_with_retry`):

1. После `requirements = call_agent_with_retry("analyst", analyst_prompt)` (строка ~109):
```python
    requirements = call_agent_with_retry("analyst", analyst_prompt)
    time.sleep(PIPELINE_STEP_DELAY)
```

2. После `artifacts = call_agent_with_retry("developer", developer_prompt)` (строка ~206):
```python
    artifacts = call_agent_with_retry("developer", developer_prompt)
    time.sleep(PIPELINE_STEP_DELAY)
```

3. В tester/validator цикле — после каждого `call_agent_with_retry`:
   - После `test_report = call_agent_with_retry("tester", ...)` (основной вызов и в while-цикле)
   - После `artifacts = call_agent_with_retry("developer", fix_prompt)` (tester fix)
   - После `validation = call_agent_with_retry("validator", ...)`
   - После `artifacts = call_agent_with_retry("developer", fix_prompt)` (validator fix)

Каждый `call_agent_with_retry` в `run_pipeline` должен иметь `time.sleep(PIPELINE_STEP_DELAY)` после себя, **кроме** последнего перед deploy (validator approve → break → deploy, задержка не нужна).

**Step 3: Проверить синтаксис**

Run: `python -c "import ast; ast.parse(open('src/orchestration.py').read()); print('OK')"`
Expected: `OK`

---

### Task 4: Коммит и деплой

**Step 1: Проверить diff**

Run: `git diff src/orchestration.py`

Убедиться:
- `import time` добавлен
- `PIPELINE_STEP_DELAY = 2` добавлен
- `is_api_error()` добавлена
- `_call_with_api_retry()` добавлена
- `call_agent_with_retry()` переработана
- `time.sleep(PIPELINE_STEP_DELAY)` в `run_pipeline` после каждого вызова агента

**Step 2: Коммит**

```bash
git add src/orchestration.py
git commit -m "fix: separate API errors from JSON parse errors, add exponential backoff"
```

**Step 3: Деплой (после подтверждения пользователя)**

```bash
git push
ssh root@194.113.37.137 "cd /opt/clawforge && git pull && rm -rf src/__pycache__"
```

**Step 4: Верификация на сервере**

```bash
ssh root@194.113.37.137 "cd /opt/clawforge && grep -n 'is_api_error\|_call_with_api_retry\|PIPELINE_STEP_DELAY' src/orchestration.py"
```

Expected: все три функции/константы найдены в файле.
